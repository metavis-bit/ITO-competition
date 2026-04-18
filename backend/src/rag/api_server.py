from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import FastAPI
from pydantic import BaseModel, Field

from .rag_engine import RAGEngine
from .schemas import EvidenceItem, QueryOutput
from .utils.trace import TraceLog


class QueryRequest(BaseModel):
    question: str
    indexes: List[str] = Field(default_factory=lambda: ["kb", "uploads"])
    top_k: int = 6
    with_prompt: bool = False
    with_trace: bool = True


class IngestRequest(BaseModel):
    dir_path: str
    index: str
    source_type: str = "uploads"
    session_id: str = "demo"
    reset: bool = False


class RetrieveRequest(BaseModel):
    question: str
    indexes: List[str] = Field(default_factory=lambda: ["kb", "uploads"])
    top_k: int = 6
    with_trace: bool = True


class RetrieveOutput(BaseModel):
    evidence: List[EvidenceItem] = Field(default_factory=list)
    trace: Optional[List[Dict[str, Any]]] = None


class IngestItem(BaseModel):
    text: str
    meta: Dict[str, Any] = Field(default_factory=dict)


class IngestItemsRequest(BaseModel):
    items: List[IngestItem]
    index: str
    source_type: str = "uploads"
    session_id: str = "demo"
    reset: bool = False


def create_app(cfg_path: str = "config.yaml") -> FastAPI:
    app = FastAPI(title="Edu-RAG API")
    engine = RAGEngine(cfg_path)

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.post("/query", response_model=QueryOutput)
    def query(req: QueryRequest):
        return engine.answer(
            req.question,
            indexes=req.indexes,
            top_k=int(req.top_k),
            with_prompt=bool(req.with_prompt),
            with_trace=bool(req.with_trace),
        )

    @app.post("/retrieve", response_model=RetrieveOutput)
    def retrieve(req: RetrieveRequest):
        trace = TraceLog() if req.with_trace else None
        ev = engine.retrieve(req.question, indexes=req.indexes, top_k=int(req.top_k), trace=trace)
        out = RetrieveOutput(evidence=ev)
        if trace is not None:
            out.trace = trace.steps
        return out

    @app.post("/ingest")
    def ingest(req: IngestRequest):
        if req.reset:
            engine.reset_index(req.index)
        return engine.ingest_dir(req.dir_path, index=req.index, source_type=req.source_type, session_id=req.session_id)

    @app.post("/ingest_items")
    def ingest_items(req: IngestItemsRequest):
        if req.reset:
            engine.reset_index(req.index)
        payload = [{"text": it.text, "meta": it.meta} for it in req.items]
        return engine.ingest_items(payload, index=req.index, source_type=req.source_type, session_id=req.session_id)

    return app


# Run:
#   uvicorn src.rag.api_server:create_app --factory --host 0.0.0.0 --port 8000
