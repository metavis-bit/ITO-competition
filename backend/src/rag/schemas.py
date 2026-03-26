from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class EvidenceItem(BaseModel):
    pk: str
    score: float
    text: str
    meta: Dict[str, Any] = Field(default_factory=dict)


class QueryOutput(BaseModel):
    answer: str
    evidence: List[EvidenceItem] = Field(default_factory=list)
    prompt: Optional[str] = None
    trace: Optional[List[Dict[str, Any]]] = None
