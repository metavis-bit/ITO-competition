from __future__ import annotations

from typing import Dict, List, Optional

from .base import Embedder, EmbedderConfig


class BgeM3Embedder:
    """BGE-M3 all-in-one embedder.

    - Dense vectors: semantic similarity
    - Sparse vectors: lexical matching (keyword)
    - (Optional) ColBERT vectors: fine-grained token matching (not used in this repo by default)

    This class tries to use `FlagEmbedding.BGEM3FlagModel` first (recommended),
    and falls back to `sentence-transformers` dense-only mode if FlagEmbedding is unavailable.
    """

    def __init__(self, cfg: EmbedderConfig):
        self.cfg = cfg
        self._flag_model = None
        self._st_model = None
        self._dim: Optional[int] = None
        self._init_model()

    def _init_model(self) -> None:
        # Prefer FlagEmbedding for full dense+sparse output.
        try:
            from FlagEmbedding import BGEM3FlagModel  # type: ignore

            self._flag_model = BGEM3FlagModel(
                self.cfg.name_or_path,
                use_fp16=bool(self.cfg.use_fp16),
                device=self.cfg.device,
            )
            # Dense dim: use a tiny encode to infer
            out = self._flag_model.encode(["hello"], return_dense=True, return_sparse=False, return_colbert_vecs=False)
            dense = out["dense_vecs"]
            self._dim = int(len(dense[0]))
            return
        except Exception:
            self._flag_model = None

        # Fallback: sentence-transformers (dense only)
        from sentence_transformers import SentenceTransformer

        self._st_model = SentenceTransformer(self.cfg.name_or_path, device=self.cfg.device)
        self._dim = int(self._st_model.get_sentence_embedding_dimension())

    def dim(self) -> int:
        assert self._dim is not None
        return self._dim

    def encode_dense(self, texts: List[str]) -> List[List[float]]:
        texts = [t if isinstance(t, str) else str(t) for t in texts]
        if self._flag_model is not None:
            out = self._flag_model.encode(
                texts,
                return_dense=True,
                return_sparse=False,
                return_colbert_vecs=False,
            )
            dense = out["dense_vecs"]
            # already numpy arrays
            return [v.tolist() for v in dense]

        assert self._st_model is not None
        vecs = self._st_model.encode(
            texts,
            batch_size=int(self.cfg.batch_size),
            show_progress_bar=False,
            normalize_embeddings=True,
        )
        return [v.tolist() for v in vecs]

    def encode_sparse(self, texts: List[str]) -> Optional[List[Dict[int, float]]]:
        texts = [t if isinstance(t, str) else str(t) for t in texts]
        if self._flag_model is None:
            return None
        out = self._flag_model.encode(
            texts,
            return_dense=False,
            return_sparse=True,
            return_colbert_vecs=False,
        )
        sparse = out.get("sparse_vecs")
        if sparse is None:
            return None
        # FlagEmbedding returns sparse vectors as {token_id: weight, ...} dict
        return [dict(v) for v in sparse]
