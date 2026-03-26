from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Protocol


class Embedder(Protocol):
    """Minimal embedder protocol used by this project."""

    def dim(self) -> int:
        ...

    def encode_dense(self, texts: List[str]) -> List[List[float]]:
        ...

    def encode_sparse(self, texts: List[str]) -> Optional[List[Dict[int, float]]]:
        ...


@dataclass
class EmbedderConfig:
    type: str = "sentence_transformer"  # sentence_transformer | bge-m3
    name_or_path: str = ""
    device: str = "cpu"
    batch_size: int = 32

    # For BGE-M3 via FlagEmbedding
    use_fp16: bool = False
    return_colbert: bool = False  # reserved for future
