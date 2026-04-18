"""
Infrastructure contracts — Protocol-based for structural subtyping.

Implementations don't need to inherit; they just need to match the
method signatures. Concrete wiring happens only in bootstrap.py.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

from .models import (
    ArtifactType,
    CoursewarePlan,
    DocumentChunk,
    GeneratedArtifact,
    ParsedDocument,
    RetrievalPlan,
    RetrievalResult,
    RetrievedChunk,
)


@runtime_checkable
class Embedder(Protocol):
    """Embeds text into dense and sparse vectors."""

    def embed_texts(self, texts: List[str]) -> List[List[float]]: ...
    def embed_sparse(self, texts: List[str]) -> List[Dict[int, float]]: ...
    def dim(self) -> int: ...


@runtime_checkable
class VectorStore(Protocol):
    """Stores and retrieves vectors."""

    def upsert(self, collection: str, chunks: List[DocumentChunk]) -> int: ...
    def search_dense(
        self, collection: str, vector: List[float], top_k: int
    ) -> List[RetrievedChunk]: ...
    def search_sparse(
        self, collection: str, sparse: Dict[int, float], top_k: int
    ) -> List[RetrievedChunk]: ...
    def delete_collection(self, collection: str) -> None: ...
    def list_collections(self) -> List[str]: ...


@runtime_checkable
class Reranker(Protocol):
    """Re-scores retrieval candidates for relevance."""

    def rerank(
        self, query: str, chunks: List[RetrievedChunk], top_n: int
    ) -> List[RetrievedChunk]: ...


@runtime_checkable
class LLMClient(Protocol):
    """Generates text from a prompt."""

    def generate(
        self, prompt: str, max_tokens: int = 512, temperature: float = 0.2
    ) -> str: ...


@runtime_checkable
class VLMClient(Protocol):
    """Describes images using a vision-language model."""

    def describe_image(self, image_path: str, prompt: str = "") -> str: ...


@runtime_checkable
class Parser(Protocol):
    """Parses a file into a structured document."""

    def supports(self, file_path: str) -> bool: ...
    def parse(self, file_path: str) -> ParsedDocument: ...


@runtime_checkable
class ArtifactGenerator(Protocol):
    """Generates a courseware artifact from a plan."""

    def generate(self, plan: CoursewarePlan, output_dir: str) -> GeneratedArtifact: ...
    def artifact_type(self) -> ArtifactType: ...


@runtime_checkable
class ArtifactStore(Protocol):
    """Persists and retrieves versioned artifacts."""

    def save(self, session_id: str, artifact: GeneratedArtifact) -> str: ...
    def load(
        self,
        session_id: str,
        artifact_type: ArtifactType,
        version: Optional[int] = None,
    ) -> Optional[GeneratedArtifact]: ...
    def list_versions(self, session_id: str) -> List[Dict[str, Any]]: ...
