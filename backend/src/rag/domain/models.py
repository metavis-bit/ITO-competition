"""
Core domain models — the single source of truth for all data shapes.

All cross-module boundaries must use these types. No raw dicts.

Merges concepts from:
  - wym/schemas.py (EvidenceItem, QueryOutput)
  - wym/dialogue/intent_extractor.py (TeachingIntent)
  - wym/courseware_pipeline.py (CoursewareResult)
  - main/tools/SQL.py (session & version structures)
  - main/api/dispatch.py (CascadeLevel)
"""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ── Document & Chunk ──────────────────────────────────────────

class DocumentMeta(BaseModel):
    """Metadata attached to every document chunk."""
    source: str = ""
    rel_path: str = ""
    abs_path: str = ""
    file_type: str = ""
    page: Optional[int] = None
    slide: Optional[int] = None
    sheet: Optional[str] = None
    frame_ts: Optional[float] = None
    timestamp: Optional[str] = None
    chunk_index: Optional[int] = None
    chunk_count: Optional[int] = None
    doc_id: str = ""
    modality: str = "text"           # text | image | audio | video | table
    confidence: float = 1.0
    warnings: List[str] = Field(default_factory=list)


class DocumentChunk(BaseModel):
    """A single chunk of a parsed document, optionally with vectors."""
    chunk_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    text: str
    meta: DocumentMeta = Field(default_factory=DocumentMeta)
    dense_vector: Optional[List[float]] = None
    sparse_vector: Optional[Dict[int, float]] = None
    content_hash: str = ""           # SHA-256 of text, for dedup


class ParsedDocument(BaseModel):
    """Result of parsing a single file into chunks."""
    doc_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    source_path: str
    file_type: str
    chunks: List[DocumentChunk] = Field(default_factory=list)
    parse_warnings: List[str] = Field(default_factory=list)
    parse_duration_ms: float = 0.0


# ── Retrieval ─────────────────────────────────────────────────

class RetrievalStrategy(str, Enum):
    FAST = "fast"               # dense only, no rerank
    BALANCED = "balanced"       # hybrid + rerank top-20
    HIGH_RECALL = "high_recall" # full hybrid + rerank top-50 + neighbor expansion


class RetrievedChunk(BaseModel):
    """A chunk returned from retrieval, with scores."""
    chunk: DocumentChunk
    score: float = 0.0
    retrieval_method: str = ""   # dense | sparse | bm25 | fused
    rerank_score: Optional[float] = None


class RetrievalPlan(BaseModel):
    """Specifies what and how to retrieve."""
    query: str
    sub_queries: List[str] = Field(default_factory=list)
    strategy: RetrievalStrategy = RetrievalStrategy.BALANCED
    indexes: List[str] = Field(default_factory=lambda: ["kb"])
    top_k: int = 6


class RetrievalResult(BaseModel):
    """Complete result of a retrieval operation."""
    plan: RetrievalPlan
    chunks: List[RetrievedChunk] = Field(default_factory=list)
    latency_ms: float = 0.0


# ── Teaching Intent ───────────────────────────────────────────

class GameTypeEnum(str, Enum):
    QUIZ = "quiz"
    MATCHING = "matching"
    SORTING = "sorting"
    FILL_BLANK = "fill_blank"
    TRUE_FALSE = "true_false"
    FLASHCARD = "flashcard"
    FLOW_FILL = "flow_fill"


class TeachingIntent(BaseModel):
    """
    Merged superset of:
      - wym dialogue/intent_extractor.py TeachingIntent (subject, grade, knowledge_points...)
      - main tools/intent_engine.py 10-item slots (theme, audience, page_range...)

    This is the canonical representation of what the teacher wants.
    """
    # ── Core fields (wym-origin) ──
    subject: str = ""
    grade_level: str = ""
    chapter: str = ""
    knowledge_points: List[Dict[str, Any]] = Field(default_factory=list)
    teaching_logic: List[str] = Field(default_factory=list)
    key_focus: List[str] = Field(default_factory=list)
    difficulties: List[str] = Field(default_factory=list)
    suggested_activities: List[str] = Field(default_factory=list)

    # ── Extended fields (main-origin 10-item slots) ──
    topic: str = ""                  # 教学主题 (maps to main "theme")
    target_audience: str = ""        # 授课对象 (maps to main "audience")
    teaching_goal: str = ""          # 教学目标 (maps to main "teaching_objectives")
    duration_minutes: int = 45
    page_range: str = "10-15"        # 课件页数
    required_knowledge: str = ""     # 必备知识
    style: str = ""                  # 教学风格/思路
    game_types: List[GameTypeEnum] = Field(default_factory=list)
    special_requirements: str = ""   # 其他要求
    reference_files: List[Dict[str, Any]] = Field(default_factory=list)

    # ── Raw LLM output for debugging ──
    raw_json: Dict[str, Any] = Field(default_factory=dict)

    def missing_fields(self) -> List[str]:
        """Return names of required-but-empty fields."""
        required = {
            "topic": self.topic,
            "teaching_goal": self.teaching_goal,
            "target_audience": self.target_audience,
        }
        return [k for k, v in required.items() if not str(v).strip()]

    def summary_text(self) -> str:
        """Human-readable summary for confirmation display."""
        lines = [
            f"学科: {self.subject}",
            f"年级: {self.grade_level}",
            f"主题: {self.topic or self.chapter}",
            f"教学目标: {self.teaching_goal}",
            f"授课对象: {self.target_audience}",
            f"重点: {', '.join(self.key_focus)}",
            f"难点: {', '.join(self.difficulties)}",
            f"教学思路: {' → '.join(self.teaching_logic)}",
            f"页数范围: {self.page_range}",
        ]
        if self.game_types:
            lines.append(f"互动游戏: {', '.join(g.value for g in self.game_types)}")
        return "\n".join(lines)

    def to_extracted_slots(self) -> Dict[str, str]:
        """Convert to main-compatible 10-item extracted_slots dict."""
        return {
            "theme": self.topic or self.chapter,
            "audience": self.target_audience or self.grade_level,
            "page_range": self.page_range,
            "teaching_objectives": self.teaching_goal,
            "key_points": ", ".join(self.key_focus),
            "required_knowledge": self.required_knowledge,
            "teaching_logic": " → ".join(self.teaching_logic) or self.style,
            "interactive_game_types": "|".join(g.value for g in self.game_types),
            "reference_material_purpose": ", ".join(
                r.get("purpose", "") for r in self.reference_files
            ),
            "other_requirements": self.special_requirements,
        }

    @classmethod
    def from_extracted_slots(cls, slots: Dict[str, str]) -> "TeachingIntent":
        """Create from main-compatible extracted_slots dict."""
        game_types = []
        for g in (slots.get("interactive_game_types") or "").split("|"):
            g = g.strip()
            if g:
                try:
                    game_types.append(GameTypeEnum(g))
                except ValueError:
                    pass
        return cls(
            topic=slots.get("theme", ""),
            target_audience=slots.get("audience", ""),
            page_range=slots.get("page_range", "10-15"),
            teaching_goal=slots.get("teaching_objectives", ""),
            key_focus=[k.strip() for k in (slots.get("key_points") or "").split(",") if k.strip()],
            required_knowledge=slots.get("required_knowledge", ""),
            style=slots.get("teaching_logic", ""),
            game_types=game_types,
            special_requirements=slots.get("other_requirements", ""),
        )


# ── Generation (Courseware Plan) ──────────────────────────────

class SlideSpec(BaseModel):
    """Specification for a single slide."""
    slide_number: int
    title: str
    bullet_points: List[str] = Field(default_factory=list)
    notes: str = ""
    layout: str = "content"   # cover | toc | content | summary | interactive
    visual_suggestion: str = ""
    image_path: Optional[str] = None


class CoursewarePlan(BaseModel):
    """
    The stable contract between planner and generators.
    All generators (PPT, DOCX, Game) consume this — never raw LLM output.
    """
    intent: TeachingIntent = Field(default_factory=TeachingIntent)
    rag_context: str = ""
    slides: List[SlideSpec] = Field(default_factory=list)
    lesson_plan_sections: List[Dict[str, Any]] = Field(default_factory=list)
    game_specs: List[Dict[str, Any]] = Field(default_factory=list)
    animation_steps: List[Dict[str, Any]] = Field(default_factory=list)
    raw_llm_output: str = ""
    plan_version: int = 1


class ArtifactType(str, Enum):
    PPTX = "pptx"
    DOCX = "docx"
    GAME_HTML = "game_html"
    ANIMATION_HTML = "animation_html"


class GeneratedArtifact(BaseModel):
    """A single generated file (PPT, Word, game, etc.)."""
    artifact_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:10])
    artifact_type: ArtifactType
    file_path: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    generation_time_sec: float = 0.0
    error: Optional[str] = None


class PipelineResult(BaseModel):
    """Complete result of a pipeline run (plan + all generated artifacts)."""
    session_id: str
    plan: Optional[CoursewarePlan] = None
    artifacts: List[GeneratedArtifact] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    total_time_sec: float = 0.0
    version_id: Optional[str] = None

    def get_artifact(self, t: ArtifactType) -> Optional[GeneratedArtifact]:
        return next((a for a in self.artifacts if a.artifact_type == t), None)


# ── Cascade Dispatch (ported from main/api/dispatch.py) ───────

class CascadeLevel(int, Enum):
    """The 5-level cascade — determines what gets regenerated on edits."""
    FIRST_GEN = 1       # first-time outline generation → full pipeline
    OUTLINE_CHANGE = 2  # outline edit → cascades to PPT + Word
    TEMPLATE_SWAP = 3   # PPT template change only (outline untouched)
    LOCAL_EDIT = 4       # word-only or game-only tweak
    ASSET_FINALIZE = 5   # batch image insertion, final polish


class RefineRequest(BaseModel):
    """Request to refine an existing courseware session."""
    session_id: str
    feedback: str
    cascade_level: CascadeLevel = CascadeLevel.OUTLINE_CHANGE
    target_types: List[ArtifactType] = Field(
        default_factory=lambda: [ArtifactType.PPTX, ArtifactType.DOCX, ArtifactType.GAME_HTML]
    )
