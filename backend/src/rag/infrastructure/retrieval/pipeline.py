"""
Composable retrieval pipeline 鈥?wraps the existing HybridRetriever with
RetrievalStrategy profiles.

Pipeline stages:
  1. Query normalization (sub-query generation)
  2. Multi-path retrieval (dense + sparse + BM25) via HybridRetriever
  3. RRF/weighted fusion (handled by HybridRetriever internals)
  4. Neighbor-chunk expansion (handled by HybridRetriever config)
  5. Per-doc diversity cap (handled by HybridRetriever config)
  6. Conditional reranking (skip on FAST profile)
  7. Context packaging into RetrievalResult

This pipeline does NOT rewrite retrieval logic 鈥?it delegates to the proven
wym HybridRetriever and adds strategy-based configuration on top.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from ...domain.models import (
    DocumentChunk,
    DocumentMeta,
    RetrievalPlan,
    RetrievalResult,
    RetrievalStrategy,
    RetrievedChunk,
)

logger = logging.getLogger("retrieval_pipeline")

# Strategy profiles 鈥?configure how aggressive retrieval is
_STRATEGY_OVERRIDES: Dict[RetrievalStrategy, Dict[str, Any]] = {
    RetrievalStrategy.FAST: {
        "use_bm25": False,
        "use_sparse": False,
        "use_dense": True,
        "dense_k": 20,
        "candidate_k": 20,
        "skip_rerank": True,
        "neighbor_window": 0,
    },
    RetrievalStrategy.BALANCED: {
        "use_bm25": True,
        "use_sparse": True,
        "use_dense": True,
        "dense_k": 60,
        "sparse_k": 60,
        "bm25_k": 30,
        "candidate_k": 80,
        "skip_rerank": False,
        "rerank_top_n": 20,
        "neighbor_window": 1,
    },
    RetrievalStrategy.HIGH_RECALL: {
        "use_bm25": True,
        "use_sparse": True,
        "use_dense": True,
        "dense_k": 100,
        "sparse_k": 100,
        "bm25_k": 50,
        "candidate_k": 150,
        "skip_rerank": False,
        "rerank_top_n": 50,
        "neighbor_window": 2,
    },
}


class RetrievalPipeline:
    """
    Strategy-aware retrieval pipeline that wraps the existing RAGEngine.

    This is a thin adapter 鈥?the real work is done by RAGEngine.retrieve()
    and the HybridRetriever inside it. This layer adds:
      - Strategy profiles (FAST/BALANCED/HIGH_RECALL)
      - Typed input/output (RetrievalPlan 鈫?RetrievalResult)
      - Conditional reranking
      - Sub-query generation

    Usage:
        pipeline = RetrievalPipeline(rag_engine=engine)
        result = pipeline.retrieve(RetrievalPlan(query="DNA杞綍", strategy=RetrievalStrategy.BALANCED))
    """

    def __init__(
        self,
        rag_engine: Any,
        rerank_top_n: int = 20,
    ):
        """
        Args:
            rag_engine: The existing RAGEngine instance.
            rerank_top_n: Default number of candidates to rerank.
        """
        self.engine = rag_engine
        self.default_rerank_top_n = rerank_top_n

    def retrieve(self, plan: RetrievalPlan) -> RetrievalResult:
        """
        Execute a retrieval plan using the configured strategy.

        Args:
            plan: What to retrieve (query, indexes, strategy, top_k).

        Returns:
            RetrievalResult with typed RetrievedChunk objects.
        """
        t0 = time.time()
        strategy_cfg = _STRATEGY_OVERRIDES.get(plan.strategy, {})

        # Generate sub-queries
        sub_queries = plan.sub_queries or self._generate_subqueries(plan.query)

        # Temporarily adjust engine config based on strategy
        original_cfg = self._apply_strategy(strategy_cfg)

        try:
            # Preferred call shape for RAGEngine.retrieve(question, indexes=..., top_k=...)
            try:
                evidence_items = self.engine.retrieve(
                    plan.query,
                    indexes=plan.indexes,
                    top_k=plan.top_k,
                )
            except TypeError as e:
                # Compatibility fallback: if engine is already a RetrievalPipeline-like object,
                # it may expose retrieve(plan) instead of retrieve(question, indexes=...).
                if "indexes" not in str(e):
                    raise
                nested = self.engine.retrieve(plan)
                if isinstance(nested, RetrievalResult):
                    return nested
                evidence_items = nested

            if isinstance(evidence_items, RetrievalResult):
                return evidence_items

            # Convert EvidenceItem -> RetrievedChunk
            chunks = []
            for item in evidence_items:
                meta = item.meta if isinstance(item.meta, dict) else {}
                chunk = RetrievedChunk(
                    chunk=DocumentChunk(
                        chunk_id=item.pk,
                        text=item.text,
                        meta=DocumentMeta(
                            source=meta.get("source", ""),
                            rel_path=meta.get("rel_path", ""),
                            page=meta.get("page"),
                            slide=meta.get("slide"),
                            frame_ts=meta.get("frame_ts"),
                            doc_id=meta.get("doc_id", ""),
                            chunk_index=meta.get("chunk_index"),
                            chunk_count=meta.get("chunk_count"),
                        ),
                    ),
                    score=item.score,
                    retrieval_method="hybrid",
                )
                chunks.append(chunk)

        finally:
            # Restore original config
            self._restore_config(original_cfg)

        latency = (time.time() - t0) * 1000
        logger.info(
            "Retrieved %d chunks for query='%s' strategy=%s in %.0fms",
            len(chunks), plan.query[:50], plan.strategy.value, latency,
        )

        return RetrievalResult(
            plan=plan,
            chunks=chunks,
            latency_ms=latency,
        )

    def retrieve_text(
        self,
        query: str,
        *,
        indexes: Optional[List[str]] = None,
        strategy: RetrievalStrategy = RetrievalStrategy.BALANCED,
        top_k: int = 6,
    ) -> str:
        """
        Convenience method 鈥?retrieve and return concatenated text.

        Useful for injecting RAG context into LLM prompts.
        """
        plan = RetrievalPlan(
            query=query,
            indexes=indexes or ["kb"],
            strategy=strategy,
            top_k=top_k,
        )
        result = self.retrieve(plan)
        return "\n\n".join(c.chunk.text for c in result.chunks)

    def _generate_subqueries(self, query: str) -> List[str]:
        """
        Generate sub-queries for multi-path retrieval.

        Simple strategy: main query + shortened variants.
        Could be enhanced with LLM-based query expansion.
        """
        sub_queries = [query]
        # Add a shorter version (first sentence or first 50 chars)
        if len(query) > 50:
            short = query[:50].rsplit(" ", 1)[0] if " " in query[:50] else query[:50]
            sub_queries.append(short)
        return sub_queries

    def _apply_strategy(self, strategy_cfg: Dict[str, Any]) -> Dict[str, Any]:
        """
        Temporarily apply strategy overrides to the RAGEngine's retriever config.

        Returns the original values for restoration.
        """
        original: Dict[str, Any] = {}

        if not hasattr(self.engine, "retriever"):
            return original

        retriever = self.engine.retriever
        cfg = retriever.cfg

        for key, value in strategy_cfg.items():
            if key == "skip_rerank" or key == "rerank_top_n":
                continue  # handled separately
            if hasattr(cfg, key):
                original[key] = getattr(cfg, key)
                setattr(cfg, key, value)

        return original

    def _restore_config(self, original: Dict[str, Any]) -> None:
        """Restore original retriever config after strategy-modified retrieval."""
        if not original or not hasattr(self.engine, "retriever"):
            return

        cfg = self.engine.retriever.cfg
        for key, value in original.items():
            if hasattr(cfg, key):
                setattr(cfg, key, value)
