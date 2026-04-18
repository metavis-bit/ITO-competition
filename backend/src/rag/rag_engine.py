from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .config import ensure_dirs, load_config
from .embedder import BgeM3Embedder, EmbedderConfig
from .generator import GeneratorConfig, QwenGenerator
from .parsers import ParsedDocument, parse_file
from .reranker import CrossEncoderReranker, RerankerConfig
from .retriever import HybridRetriever, HybridRetrieverConfig
from .schemas import EvidenceItem, QueryOutput
from .utils.files import iter_files
from .utils.text import chunk_text_recursive, sanitize_collection_name
from .utils.trace import TraceLog
from .vector_store import LocalDocStore, MilvusConfig, MilvusVectorStore, StoredDoc


def _sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def _default_subqueries(q: str) -> List[str]:
    qs = [q.strip()]
    # add a shorter version to improve recall on long prompts
    if len(qs[0]) > 12:
        qs.append(qs[0][: max(6, len(qs[0]) // 2)])
    # de-dup keep order
    out: List[str] = []
    for x in qs:
        if x and x not in out:
            out.append(x)
    return out[:3]


class RAGEngine:
    """Edu-RAG core engine.

    Key design goals:
    - Modular pipeline (embedder / vector store / retriever / reranker / generator)
    - Multi-modal ingestion -> unified text evidence
    - Hybrid retrieval (dense+sparse via BGE-M3, optional Milvus native hybrid_search)
    - Quality knobs: RRF fusion, diversity constraint, neighbor chunk expansion
    - Integration-friendly: a single python class + optional service/UI
    """

    def __init__(self, cfg_path: str = "config.yaml"):
        self.cfg_path = cfg_path
        self.cfg = load_config(cfg_path)
        ensure_dirs(self.cfg)

        # Paths
        self.store_dir = Path(self.cfg.get("store_dir", "./rag_store")).expanduser()
        self.assets_root = self.store_dir / "assets"
        self.index_root = self.store_dir / "indexes"
        self.assets_root.mkdir(parents=True, exist_ok=True)
        self.index_root.mkdir(parents=True, exist_ok=True)

        # Embedder
        e_cfg = self.cfg.get("embedding_model", {}) or {}
        embed_cfg = EmbedderConfig(
            type=str(e_cfg.get("type", "bge-m3")),
            name_or_path=str(e_cfg.get("name_or_path", "./models/bge-m3")),
            device=str(e_cfg.get("device", "cpu")),
            batch_size=int(e_cfg.get("batch_size", 32)),
            use_fp16=bool(e_cfg.get("use_fp16", False)),
        )
        self.embedder = BgeM3Embedder(embed_cfg)
        self.embed_dim = self.embedder.dim()

        # Vector store (Milvus)
        v_cfg = self.cfg.get("vector_store", {}) or {}
        milvus_cfg = MilvusConfig(
            uri=str(v_cfg.get("uri", str(self.store_dir / "milvus.db"))),
            metric_type=str(v_cfg.get("metric_type", "COSINE")),
            index_type=str(v_cfg.get("index_type", "HNSW")),
            index_params=v_cfg.get("index_params") or {},
            search_params=v_cfg.get("search_params") or {},
            enable_sparse=bool(v_cfg.get("enable_sparse", True)),
            sparse_field=str(v_cfg.get("sparse_field", "sparse_vector")),
            sparse_index_params=v_cfg.get("sparse_index_params") or {"index_type": "SPARSE_INVERTED_INDEX", "params": {"inverted_index_algo": "DAAT_MAXSCORE"}},
            sparse_metric_type=str(v_cfg.get("sparse_metric_type", "IP")),
            pk_field=str(v_cfg.get("pk_field", "pk")),
            dense_field=str(v_cfg.get("dense_field", "vector")),
        )
        self.vstore = MilvusVectorStore(milvus_cfg)

        # Retriever
        r_cfg = self.cfg.get("retrieval", {}) or {}
        retr_cfg = HybridRetrieverConfig(
            use_bm25=bool(r_cfg.get("use_bm25", True)),
            use_dense=bool(r_cfg.get("use_dense", True)),
            use_sparse=bool(r_cfg.get("use_sparse", True)),
            bm25_k=int(r_cfg.get("bm25_k", 30)),
            dense_k=int(r_cfg.get("dense_k", 60)),
            sparse_k=int(r_cfg.get("sparse_k", 60)),
            candidate_k=int(r_cfg.get("candidate_k", 80)),
            fusion=str(r_cfg.get("fusion", "rrf")),
            rrf_k=int(r_cfg.get("rrf_k", 60)),
            weights=r_cfg.get("weights"),
            use_milvus_hybrid=bool(r_cfg.get("use_milvus_hybrid", True)),
            milvus_hybrid_ranker=str(r_cfg.get("milvus_hybrid_ranker", "rrf")),
            milvus_hybrid_rrf_k=int(r_cfg.get("milvus_hybrid_rrf_k", 60)),
            milvus_hybrid_weights=r_cfg.get("milvus_hybrid_weights"),
            max_per_doc_candidates=int(r_cfg.get("max_per_doc_candidates", 5)),
            neighbor_window=int(r_cfg.get("neighbor_window", 1)),
            neighbor_decay=float(r_cfg.get("neighbor_decay", 0.15)),
            min_fused_score=r_cfg.get("min_fused_score"),
        )
        self.retriever = HybridRetriever(retr_cfg, embedder=self.embedder, vstore=self.vstore)

        # Reranker
        rr_cfg = self.cfg.get("reranker", {}) or {}
        self.reranker = CrossEncoderReranker(
            RerankerConfig(
                name_or_path=str(rr_cfg.get("name_or_path", "./models/bge-reranker-large")),
                device=str(rr_cfg.get("device", "cpu")),
                batch_size=int(rr_cfg.get("batch_size", 16)),
            )
        )

        # Generator
        g_cfg = self.cfg.get("generator", {}) or {}
        self.generator = QwenGenerator(
            GeneratorConfig(
                mode=str(g_cfg.get("mode", "local")),
                api_model=str(g_cfg.get("api_model", "gpt-4o-mini")),
                api_base_url_env=str(g_cfg.get("api_base_url_env", "OPENAI_BASE_URL")),
                api_key_env=str(g_cfg.get("api_key_env", "OPENAI_API_KEY")),
                timeout_sec=float(g_cfg.get("timeout_sec", 120.0)),
                local_model_path=str(g_cfg.get("local_model_path", "./models/Qwen2.5-1.5B-Instruct")),
                device=str(g_cfg.get("device", "cpu")),
                max_new_tokens=int(g_cfg.get("max_new_tokens", 512)),
                temperature=float(g_cfg.get("temperature", 0.2)),
            )
        )

        # Prompt
        self.prompt_tpl = str(self.cfg.get("rag_prompt", "")) or self._default_prompt()

    # ---------------------- prompt ----------------------
    def _default_prompt(self) -> str:
        return (
            "你是一个严谨的教学助手。请只基于【证据】回答用户问题，并给出清晰、可执行的结论。\n"
            "如果证据不足，请明确说明‘证据不足’，并给出你还需要哪些资料。\n\n"
            "【证据】\n{context}\n\n"
            "【问题】\n{question}\n\n"
            "【回答要求】\n"
            "- 用中文回答\n"
            "- 需要引用证据编号，如 [1] [2]\n"
        )

    # ---------------------- indexes / docstores ----------------------
    def _index_dir(self, index: str) -> Path:
        return self.index_root / sanitize_collection_name(index)

    def _docstore(self, index: str) -> LocalDocStore:
        return LocalDocStore(str(self._index_dir(index)))

    def list_indexes(self) -> List[str]:
        if not self.index_root.exists():
            return []
        return sorted([p.name for p in self.index_root.iterdir() if p.is_dir()])

    # ---------------------- ingestion ----------------------
    def reset_index(self, index: str) -> None:
        """Drop Milvus collection + delete local store for an index."""
        idx = sanitize_collection_name(index)
        self.vstore.drop_collection(idx)
        d = self._index_dir(idx)
        if d.exists():
            for p in d.rglob("*"):
                try:
                    p.unlink()
                except Exception:
                    pass
            try:
                d.rmdir()
            except Exception:
                pass

    def ingest_dir(
        self,
        dir_path: str,
        *,
        index: str,
        source_type: str,
        session_id: str,
        trace: Optional[TraceLog] = None,
    ) -> Dict[str, Any]:
        """Parse -> chunk -> embed -> write to Milvus + LocalDocStore."""
        index = sanitize_collection_name(index)
        dirp = Path(dir_path)
        if not dirp.exists():
            raise FileNotFoundError(dir_path)

        docstore = self._docstore(index)

        parse_cfg = self.cfg.get("parsing", {}) or {}
        chunk_cfg = self.cfg.get("chunking", {}) or {}
        chunk_size = int(chunk_cfg.get("chunk_size", 600))
        chunk_overlap = int(chunk_cfg.get("chunk_overlap", 80))

        assets_dir = str(self.assets_root / session_id)

        # Ingest
        stored_docs: List[StoredDoc] = []
        dense_batch: List[List[float]] = []
        sparse_batch: List[Dict[int, float]] = []
        pk_batch: List[str] = []

        def _flush():
            nonlocal stored_docs, dense_batch, sparse_batch, pk_batch
            if not pk_batch:
                return
            use_sparse = bool(self.vstore.cfg.enable_sparse)
            self.vstore.upsert(
                index,
                pk_batch,
                dense_batch,
                dim=self.embed_dim,
                sparse_vectors=sparse_batch if (use_sparse and sparse_batch) else None,
            )
            docstore.add_many(stored_docs)
            stored_docs = []
            dense_batch = []
            sparse_batch = []
            pk_batch = []

        embed_bs = int(self.cfg.get("embedding_batch_size", 64))

        file_count = 0
        chunk_count = 0

        for fp in iter_files(str(dirp), exts=None):
            file_count += 1
            try:
                parsed = parse_file(
                    fp,
                    root_dir=str(dirp),
                    source_type=source_type,
                    session_id=session_id,
                    assets_dir=assets_dir,
                    parse_cfg=parse_cfg,
                )
            except Exception as e:
                if trace:
                    trace.add("parse_error", str(e), file=fp)
                continue

            for pd in parsed:
                loc = str(pd.meta.get("loc", pd.meta.get("source", "")))
                part = str(pd.meta.get("part", ""))

                doc_id = _sha1(f"{source_type}|{session_id}|{loc}|{part}")
                chunks = chunk_text_recursive(pd.text, chunk_size=chunk_size, overlap=chunk_overlap)
                if not chunks:
                    continue

                # Embed in mini-batches for speed/memory
                for ci, chunk in enumerate(chunks):
                    pk = _sha1(f"{doc_id}:{ci}")
                    meta = dict(pd.meta)
                    meta.update({
                        "doc_id": doc_id,
                        "chunk_index": ci,
                        "chunk_count": len(chunks),
                    })
                    stored_docs.append(StoredDoc(pk=pk, text=chunk, meta=meta))
                    pk_batch.append(pk)
                    chunk_count += 1

                    # We'll embed in batch flush to avoid per-chunk embedding calls.
                    # Collect raw texts in a temporary list; easiest is to embed when flushing:
                    # But we need embedding vectors now; so keep a parallel list of texts.
                    # Instead, we embed immediately for each chunk group sized embed_bs.
                    # We'll do immediate embedding for simplicity.
                    # (This is still batched because we flush at embed_bs.)
                    if len(pk_batch) == 1:
                        text_batch: List[str] = []
                    # Not used.

                    # We'll postpone embedding until reaching embed_bs: gather texts from stored_docs last N
                    if len(pk_batch) >= embed_bs:
                        texts = [d.text for d in stored_docs]
                        dense_vecs = self.embedder.encode_dense(texts)
                        dense_batch.extend(dense_vecs)
                        sp = self.embedder.encode_sparse(texts) if self.vstore.cfg.enable_sparse else None
                        if sp is not None:
                            sparse_batch.extend(sp)
                        _flush()
                        # reset doc lists already inside _flush()

                # After each parsed doc, embed remaining if pending and batch size not reached
                if pk_batch:
                    texts = [d.text for d in stored_docs]
                    dense_vecs = self.embedder.encode_dense(texts)
                    dense_batch.extend(dense_vecs)
                    sp = self.embedder.encode_sparse(texts) if self.vstore.cfg.enable_sparse else None
                    if sp is not None:
                        sparse_batch.extend(sp)
                    _flush()

        # rebuild BM25
        if trace:
            trace.add("bm25_rebuild", "rebuild bm25")
        docstore.rebuild_bm25()

        return {"index": index, "files": file_count, "chunks": chunk_count, "session_id": session_id}

    def ingest_items(
        self,
        items: Sequence[Dict[str, Any]],
        *,
        index: str,
        source_type: str,
        session_id: str,
        trace: Optional[TraceLog] = None,
    ) -> Dict[str, Any]:
        """Ingest **already-parsed** items.

        This is the most integration-friendly entrypoint for other modules.

        Expected item schema (minimal):
          {
            "text": "...",
            "meta": {"loc": "...", "part": "...", ...}
          }

        - Module2 (multi-modal parsing) can parse files by itself, then call this method
          to push unified evidence into RAG without re-parsing.
        - Module3/4 can add extra meta fields like bind_to/slide_id/knowledge_point.
        """

        index = sanitize_collection_name(index)
        docstore = self._docstore(index)

        chunk_cfg = self.cfg.get("chunking", {}) or {}
        chunk_size = int(chunk_cfg.get("chunk_size", 500))
        chunk_overlap = int(chunk_cfg.get("chunk_overlap", 50))

        embed_bs = int(self.cfg.get("embedding_batch_size", 64))

        stored_docs: List[StoredDoc] = []
        pk_batch: List[str] = []
        text_batch: List[str] = []

        def _flush():
            nonlocal stored_docs, pk_batch, text_batch
            if not pk_batch:
                return
            dense_vecs = self.embedder.encode_dense(text_batch)
            sp = self.embedder.encode_sparse(text_batch) if self.vstore.cfg.enable_sparse else None
            self.vstore.upsert(
                index,
                pk_batch,
                dense_vecs,
                dim=self.embed_dim,
                sparse_vectors=sp,
            )
            docstore.add_many(stored_docs)
            stored_docs = []
            pk_batch = []
            text_batch = []

        item_count = 0
        chunk_count = 0
        for it in items:
            item_count += 1
            text = str((it or {}).get("text") or "").strip()
            if not text:
                continue
            meta = dict((it or {}).get("meta") or {})
            meta.setdefault("source_type", source_type)
            meta.setdefault("session_id", session_id)

            loc = str(meta.get("loc") or meta.get("source") or meta.get("rel_path") or "")
            part = str(meta.get("part") or f"item_{item_count}")
            doc_id = _sha1(f"{source_type}|{session_id}|{loc}|{part}")

            chunks = chunk_text_recursive(text, chunk_size=chunk_size, overlap=chunk_overlap)
            if not chunks:
                continue

            for ci, ch in enumerate(chunks):
                pk = _sha1(f"{doc_id}:{ci}")
                meta2 = dict(meta)
                meta2.update({
                    "doc_id": doc_id,
                    "chunk_index": ci,
                    "chunk_count": len(chunks),
                })
                stored_docs.append(StoredDoc(pk=pk, text=ch, meta=meta2))
                pk_batch.append(pk)
                text_batch.append(ch)
                chunk_count += 1

                if len(pk_batch) >= embed_bs:
                    _flush()

        _flush()

        if trace:
            trace.add("bm25_rebuild", "rebuild bm25")
        docstore.rebuild_bm25()

        return {"index": index, "items": item_count, "chunks": chunk_count, "session_id": session_id}

    def ingest_knowledge_base(self, kb_dir: str, index: str = "kb", session_id: str = "kb") -> Dict[str, Any]:
        trace = TraceLog()
        out = self.ingest_dir(kb_dir, index=index, source_type="knowledge_base", session_id=session_id, trace=trace)
        out["trace"] = trace.steps
        return out

    def ingest_uploads(self, upload_dir: str, index: str = "uploads", session_id: str = "demo") -> Dict[str, Any]:
        trace = TraceLog()
        out = self.ingest_dir(upload_dir, index=index, source_type="uploads", session_id=session_id, trace=trace)
        out["trace"] = trace.steps
        return out

    # ---------------------- retrieval only ----------------------
    def retrieve(
        self,
        question: str,
        *,
        indexes: Sequence[str],
        top_k: int = 6,
        trace: Optional[TraceLog] = None,
    ) -> List[EvidenceItem]:
        question = (question or "").strip()
        if not question:
            return []

        subqueries = _default_subqueries(question)

        candidates: List[Tuple[str, str, Dict[str, Any], float]] = []
        for idx in indexes:
            idx = sanitize_collection_name(idx)
            docstore = self._docstore(idx)
            docstore.load_all()
            cands = self.retriever.retrieve_candidates(
                collection=idx,
                docstore=docstore,
                query=question,
                subqueries=subqueries,
                embed_dim=self.embed_dim,
                trace=trace,
            )
            candidates.extend(cands)

        # Dedup by pk keep max score
        best: Dict[str, Tuple[str, str, Dict[str, Any], float]] = {}
        for pk, text, meta, sc in candidates:
            prev = best.get(pk)
            if prev is None or sc > prev[3]:
                best[pk] = (pk, text, meta, sc)
        merged = list(best.values())
        merged.sort(key=lambda x: x[3], reverse=True)

        # Rerank
        rerank_top_n = int(self.cfg.get("rerank_top_n", max(20, top_k * 5)))
        to_rerank = merged[:rerank_top_n]
        if trace:
            trace.add("rerank", "cross-encoder rerank", candidates=len(to_rerank))
        reranked = self.reranker.rerank(question, to_rerank, top_n=rerank_top_n)

        # Final diversity constraint
        max_per_doc = int((self.cfg.get("final_max_per_doc") or 3))
        final: List[Tuple[str, str, Dict[str, Any], float]] = []
        per_doc: Dict[str, int] = {}
        for pk, text, meta, sc in reranked:
            doc_id = str(meta.get("doc_id", ""))
            if max_per_doc > 0 and doc_id:
                cnt = per_doc.get(doc_id, 0)
                if cnt >= max_per_doc:
                    continue
                per_doc[doc_id] = cnt + 1
            final.append((pk, text, meta, sc))
            if len(final) >= int(top_k):
                break

        return [EvidenceItem(pk=pk, score=float(sc), text=text, meta=meta) for pk, text, meta, sc in final]

    # ---------------------- answer generation ----------------------
    def answer(
        self,
        question: str,
        *,
        indexes: Sequence[str],
        top_k: int = 6,
        with_prompt: bool = False,
        with_trace: bool = False,
    ) -> QueryOutput:
        trace = TraceLog() if with_trace else None
        evidence = self.retrieve(question, indexes=indexes, top_k=top_k, trace=trace)

        # context formatting
        blocks: List[str] = []
        for i, ev in enumerate(evidence, start=1):
            loc = ev.meta.get("loc") or ev.meta.get("source") or ""
            blocks.append(f"[{i}] {loc}\n{ev.text}")
        context = "\n\n".join(blocks)

        prompt = self.prompt_tpl.format(context=context, question=question)
        ans = self.generator.generate(prompt)

        out = QueryOutput(answer=ans, evidence=evidence, prompt=prompt if with_prompt else None)
        if with_trace and trace is not None:
            out.trace = trace.as_dicts()
        return out
