from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class RerankerConfig:
    name_or_path: str
    device: str = "cpu"
    batch_size: int = 32


class CrossEncoderReranker:
    """Cross-encoder reranker wrapper (e.g., bge-reranker-large)."""

    def __init__(self, cfg: RerankerConfig):
        self.cfg = cfg
        self._model = None

    def _ensure(self):
        if self._model is not None:
            return
        from sentence_transformers import CrossEncoder

        self._model = CrossEncoder(self.cfg.name_or_path, device=self.cfg.device)

    def rerank(
        self,
        query: str,
        items: List[Tuple[str, str, Dict[str, Any], float]],
        top_n: int,
    ) -> List[Tuple[str, str, Dict[str, Any], float]]:
        """Rerank items by cross-encoder score.

        items: list of (pk, text, meta, score)
        returns: top_n items with score replaced by rerank score.
        """
        if not items:
            return []
        self._ensure()
        assert self._model is not None

        pairs = [(query, it[1]) for it in items]
        scores = self._model.predict(pairs, batch_size=int(self.cfg.batch_size))
        scored: List[Tuple[str, str, Dict[str, Any], float]] = []
        for it, sc in zip(items, scores):
            scored.append((it[0], it[1], it[2], float(sc)))
        scored.sort(key=lambda x: x[3], reverse=True)
        return scored[: int(top_n)]
