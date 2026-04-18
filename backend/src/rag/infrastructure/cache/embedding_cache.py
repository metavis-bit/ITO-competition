"""
Embedding cache — content-hash dedup for both ingestion and query.

Before embedding any text, compute SHA-256. If already embedded, skip.
Eliminates duplicate work during re-ingestion and repeated queries.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("embedding_cache")


class EmbeddingCache:
    """
    Disk-backed embedding cache: {content_hash → (dense_vector, sparse_vector, timestamp)}

    On startup, loads index from JSON. Persists on explicit call or context manager exit.
    For competition demo: simple JSON file. For production: swap to Redis/SQLite.
    """

    def __init__(self, cache_dir: str = "./rag_store/cache"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self.cache_dir / "embedding_index.json"
        self._index: Dict[str, Dict] = self._load_index()
        self._dirty = False

    @staticmethod
    def content_hash(text: str) -> str:
        """Compute SHA-256 hash of normalized text."""
        return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()

    def get(self, text: str) -> Optional[Tuple[List[float], Optional[Dict[int, float]]]]:
        """
        Look up cached embedding for given text.

        Returns:
            (dense_vector, sparse_vector) if cached, else None.
            sparse_vector may be None if not stored.
        """
        h = self.content_hash(text)
        entry = self._index.get(h)
        if entry:
            sparse = entry.get("sparse")
            # sparse vectors stored as {str_key: float} in JSON, convert back to {int: float}
            if sparse and isinstance(sparse, dict):
                sparse = {int(k): v for k, v in sparse.items()}
            return entry["dense"], sparse
        return None

    def put(
        self,
        text: str,
        dense: List[float],
        sparse: Optional[Dict[int, float]] = None,
    ) -> None:
        """Cache an embedding result."""
        h = self.content_hash(text)
        # Convert sparse keys to strings for JSON serialization
        sparse_json = None
        if sparse is not None:
            sparse_json = {str(k): v for k, v in sparse.items()}
        self._index[h] = {
            "dense": dense,
            "sparse": sparse_json,
            "ts": time.time(),
        }
        self._dirty = True

    def batch_filter_uncached(
        self, texts: List[str]
    ) -> Tuple[List[str], List[int], List[Tuple[List[float], Optional[Dict[int, float]]]]]:
        """
        Partition texts into cached and uncached.

        Returns:
            (uncached_texts, uncached_indices, cached_results)
            where cached_results[i] corresponds to the i-th text that was cached.
        """
        uncached_texts: List[str] = []
        uncached_indices: List[int] = []
        cached_results: List[Tuple[List[float], Optional[Dict[int, float]]]] = []

        for i, t in enumerate(texts):
            hit = self.get(t)
            if hit is None:
                uncached_texts.append(t)
                uncached_indices.append(i)

        return uncached_texts, uncached_indices, cached_results

    def batch_put(
        self,
        texts: List[str],
        dense_vectors: List[List[float]],
        sparse_vectors: Optional[List[Optional[Dict[int, float]]]] = None,
    ) -> None:
        """Cache a batch of embedding results."""
        for i, text in enumerate(texts):
            sparse = sparse_vectors[i] if sparse_vectors and i < len(sparse_vectors) else None
            self.put(text, dense_vectors[i], sparse)

    def persist(self) -> None:
        """Write cache index to disk."""
        if not self._dirty:
            return
        try:
            self._index_path.write_text(
                json.dumps(self._index, ensure_ascii=False),
                encoding="utf-8",
            )
            self._dirty = False
            logger.debug("Embedding cache persisted (%d entries)", len(self._index))
        except Exception as e:
            logger.error("Failed to persist embedding cache: %s", e)

    def _load_index(self) -> Dict:
        """Load cache index from disk."""
        if self._index_path.exists():
            try:
                data = json.loads(self._index_path.read_text(encoding="utf-8"))
                logger.info("Loaded embedding cache with %d entries", len(data))
                return data
            except Exception as e:
                logger.warning("Failed to load embedding cache: %s", e)
        return {}

    @property
    def size(self) -> int:
        """Number of cached entries."""
        return len(self._index)

    def evict_older_than(self, max_age_sec: float = 86400 * 7) -> int:
        """Remove cache entries older than max_age_sec. Returns count removed."""
        cutoff = time.time() - max_age_sec
        expired = [k for k, v in self._index.items() if v.get("ts", 0) < cutoff]
        for k in expired:
            del self._index[k]
        if expired:
            self._dirty = True
        return len(expired)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.persist()
