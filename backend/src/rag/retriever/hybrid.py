from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..embedder.base import Embedder
from ..utils.trace import TraceLog
from ..vector_store.doc_store import LocalDocStore
from ..vector_store.milvus_store import MilvusVectorStore


@dataclass
class HybridRetrieverConfig:
    # Which retrievers to use
    use_bm25: bool = True
    use_dense: bool = True
    use_sparse: bool = True  # requires embedder.encode_sparse + Milvus sparse field

    # Per-retriever recall sizes
    bm25_k: int = 30
    dense_k: int = 60
    sparse_k: int = 60

    # Candidate pool size before rerank
    candidate_k: int = 80

    # Fusion strategy
    fusion: str = "rrf"  # rrf | weighted_sum
    rrf_k: int = 60  # RRF constant
    weights: Dict[str, float] | None = None  # e.g. {"bm25": 0.3, "dense": 0.7, "sparse": 0.5}

    # Milvus native hybrid (dense+sparse) - recommended if Milvus>=2.4 + pymilvus>=2.4
    use_milvus_hybrid: bool = True
    milvus_hybrid_ranker: str = "rrf"  # rrf | weighted
    milvus_hybrid_rrf_k: int = 60
    milvus_hybrid_weights: Optional[List[float]] = None  # [w_dense, w_sparse] for weighted ranker

    # Diversity + neighbor expansion
    max_per_doc_candidates: int = 5  # diversity constraint at candidate stage (0 = disable)
    neighbor_window: int = 1  # expand ±N chunks
    neighbor_decay: float = 0.15  # score decay per chunk distance

    # Score threshold (optional)
    min_fused_score: Optional[float] = None


def _get_weight(name: str, weights: Optional[Dict[str, float]]) -> float:
    if not weights:
        return 1.0
    if name in weights:
        return float(weights[name])
    base = name.split("_", 1)[0]
    if base in weights:
        return float(weights[base])
    return 1.0


def _rrf_fuse(
    ranked_lists: List[Tuple[str, List[Tuple[str, float]]]],
    rrf_k: int = 60,
    weights: Optional[Dict[str, float]] = None,
) -> Dict[str, float]:
    """Reciprocal Rank Fusion.

    ranked_lists: [(name, [(pk, score), ...]), ...]
    weights: optional per-list weights by name.
    """
    fused: Dict[str, float] = {}
    k = int(rrf_k)
    for name, items in ranked_lists:
        w = _get_weight(name, weights)
        for rank, (pk, _score) in enumerate(items, start=1):
            fused[pk] = fused.get(pk, 0.0) + w * (1.0 / (k + rank))
    return fused


def _weighted_sum_fuse(
    ranked_lists: List[Tuple[str, List[Tuple[str, float]]]],
    weights: Optional[Dict[str, float]] = None,
) -> Dict[str, float]:
    """Score-based weighted fusion (normalize each list by max score)."""
    fused: Dict[str, float] = {}
    for name, items in ranked_lists:
        w = _get_weight(name, weights)
        if not items:
            continue
        max_sc = max(sc for _pk, sc in items) or 1.0
        for pk, sc in items:
            fused[pk] = fused.get(pk, 0.0) + w * (float(sc) / max_sc)
    return fused


class HybridRetriever:
    def __init__(self, cfg: HybridRetrieverConfig, *, embedder: Embedder, vstore: MilvusVectorStore):
        self.cfg = cfg
        self.embedder = embedder
        self.vstore = vstore

    def retrieve_candidates(
        self,
        *,
        collection: str,
        docstore: LocalDocStore,
        query: str,
        subqueries: Sequence[str],
        embed_dim: int,
        trace: Optional[TraceLog] = None,
    ) -> List[Tuple[str, str, Dict[str, Any], float]]:
        """Retrieve + fuse into candidate items (pk, text, meta, fused_score)."""

        ranked_lists: List[Tuple[str, List[Tuple[str, float]]]] = []

        # ---- BM25 ----
        if self.cfg.use_bm25:
            if trace:
                trace.add("retrieve_bm25", "bm25 search", top_k=int(self.cfg.bm25_k))
            bm = docstore.bm25_search(query, top_k=int(self.cfg.bm25_k))
            ranked_lists.append(("bm25", bm))

        # ---- Dense / Sparse ----
        # Strategy:
        #  - if sparse enabled and milvus native hybrid available -> call vstore.hybrid_search() per subquery
        #  - else: call dense + sparse separately and fuse with RRF/weighted at the end
        sparse_vecs = self.embedder.encode_sparse(list(subqueries)) if self.cfg.use_sparse else None
        dense_vecs = self.embedder.encode_dense(list(subqueries)) if self.cfg.use_dense else []

        used_milvus_hybrid = False
        if (
            self.cfg.use_sparse
            and self.cfg.use_dense
            and self.cfg.use_milvus_hybrid
            and sparse_vecs is not None
        ):
            # One hybrid list per subquery
            used_milvus_hybrid = True
            if trace:
                trace.add(
                    "retrieve_milvus_hybrid",
                    "milvus hybrid_search (dense+sparse)",
                    subqueries=len(subqueries),
                    top_k=int(max(self.cfg.dense_k, self.cfg.sparse_k)),
                    ranker=self.cfg.milvus_hybrid_ranker,
                )
            # Use a larger top_k for better recall, then fusion across subqueries
            per_q_k = int(max(self.cfg.dense_k, self.cfg.sparse_k))
            for i, (dv, sv, sq) in enumerate(zip(dense_vecs, sparse_vecs, subqueries), start=1):
                res = self.vstore.hybrid_search(
                    collection,
                    query_dense=[dv],
                    query_sparse=[sv],
                    dim=embed_dim,
                    top_k=per_q_k,
                    ranker=self.cfg.milvus_hybrid_ranker,
                    rrf_k=int(self.cfg.milvus_hybrid_rrf_k),
                    weights=self.cfg.milvus_hybrid_weights,
                    dense_k=int(self.cfg.dense_k),
                    sparse_k=int(self.cfg.sparse_k),
                )
                hits = res[0] if res else []
                ranked_lists.append((f"hybrid_q{i}", hits))

        if not used_milvus_hybrid:
            # Dense search
            if self.cfg.use_dense:
                if trace:
                    trace.add("retrieve_dense", "milvus dense search", subqueries=len(subqueries), top_k=int(self.cfg.dense_k))
                if dense_vecs:
                    dense_hits = self.vstore.search_dense(collection, dense_vecs, dim=embed_dim, top_k=int(self.cfg.dense_k))
                    for i, hits in enumerate(dense_hits, start=1):
                        ranked_lists.append((f"dense_q{i}", hits))

            # Sparse search
            if self.cfg.use_sparse and sparse_vecs is not None:
                if trace:
                    trace.add("retrieve_sparse", "milvus sparse search", subqueries=len(subqueries), top_k=int(self.cfg.sparse_k))
                sparse_hits = self.vstore.search_sparse(collection, sparse_vecs, dim=embed_dim, top_k=int(self.cfg.sparse_k))
                for i, hits in enumerate(sparse_hits, start=1):
                    ranked_lists.append((f"sparse_q{i}", hits))

        # ---- Fuse lists ----
        fusion = (self.cfg.fusion or "rrf").lower()
        if trace:
            trace.add("fusion", "fuse ranked lists", fusion=fusion, lists=len(ranked_lists))

        if fusion == "weighted_sum":
            fused_scores = _weighted_sum_fuse(ranked_lists, weights=self.cfg.weights)
        else:
            fused_scores = _rrf_fuse(ranked_lists, rrf_k=int(self.cfg.rrf_k), weights=self.cfg.weights)

        # Optional score threshold
        if self.cfg.min_fused_score is not None:
            thr = float(self.cfg.min_fused_score)
            fused_scores = {pk: sc for pk, sc in fused_scores.items() if sc >= thr}

        # Rank by fused score
        ranked_ids = sorted(fused_scores.items(), key=lambda x: x[1], reverse=True)[: int(self.cfg.candidate_k)]
        pks = [pk for pk, _ in ranked_ids]
        docs = docstore.get_many(pks)
        doc_map = {d.pk: d for d in docs}

        # ---- Diversity constraint at candidate stage ----
        out: List[Tuple[str, str, Dict[str, Any], float]] = []
        if int(self.cfg.max_per_doc_candidates) > 0:
            per_doc: Dict[str, int] = {}
            for pk, sc in ranked_ids:
                d = doc_map.get(pk)
                if d is None:
                    continue
                doc_id = str(d.meta.get("doc_id", ""))
                if doc_id:
                    cnt = per_doc.get(doc_id, 0)
                    if cnt >= int(self.cfg.max_per_doc_candidates):
                        continue
                    per_doc[doc_id] = cnt + 1
                out.append((pk, d.text, d.meta, float(sc)))
        else:
            for pk, sc in ranked_ids:
                d = doc_map.get(pk)
                if d is None:
                    continue
                out.append((pk, d.text, d.meta, float(sc)))

        # ---- Neighbor expansion (add adjacent chunks) ----
        win = int(self.cfg.neighbor_window)
        if win > 0:
            if trace:
                trace.add("neighbor", "expand neighbor chunks", window=win, decay=float(self.cfg.neighbor_decay))

            # Start with current candidates
            best: Dict[str, Tuple[str, str, Dict[str, Any], float]] = {pk: (pk, doc, meta, sc) for pk, doc, meta, sc in out}

            for pk, doc, meta, sc in list(best.values()):
                doc_id = str(meta.get("doc_id", ""))
                ci = meta.get("chunk_index")
                if not doc_id or ci is None:
                    continue
                try:
                    ci_int = int(ci)
                except Exception:
                    continue
                for n in range(ci_int - win, ci_int + win + 1):
                    if n == ci_int:
                        continue
                    nd = docstore.get_by_doc_chunk(doc_id, n)
                    if not nd:
                        continue
                    dist = abs(n - ci_int)
                    nsc = float(sc) * max(0.0, 1.0 - float(self.cfg.neighbor_decay) * dist)
                    prev = best.get(nd.pk)
                    if prev is None or nsc > prev[3]:
                        best[nd.pk] = (nd.pk, nd.text, nd.meta, nsc)

            # keep top candidate_k again
            flat = list(best.values())
            flat.sort(key=lambda x: x[3], reverse=True)
            out = flat[: int(self.cfg.candidate_k)]

        return out