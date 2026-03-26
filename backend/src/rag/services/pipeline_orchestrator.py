"""
Async pipeline orchestrator - the ONLY orchestration file.

Key design:
  1. Planning (serial): intent -> RAG retrieval -> LLM outline -> schema normalization
  2. Generation (parallel): PPT, DOCX, Game execute concurrently via asyncio.gather
  3. Persistence: results saved to ArtifactStore with version snapshot
  4. Cascade-aware: RefineRequest with CascadeLevel determines which generators re-run
  5. Streaming: generate_stream() yields SSE events for real-time frontend updates

All other modules are pure functions/services - this is the only place that
knows the full workflow.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any, AsyncIterator, Dict, List, Optional

from ..domain.models import (
    ArtifactType,
    CascadeLevel,
    CoursewarePlan,
    GeneratedArtifact,
    PipelineResult,
    RefineRequest,
    RetrievalPlan,
    RetrievalStrategy,
    TeachingIntent,
)
from ..infrastructure.cache import EmbeddingCache
from ..infrastructure.llm import LLMRouter
from ..infrastructure.persistence.version_store import SQLiteArtifactStore
from .schema_normalizer import SchemaNormalizer

logger = logging.getLogger("pipeline")

# Outline generation prompt template
_OUTLINE_PROMPT = """你是一位资深的高中生物教学专家。请根据以下教学要素和参考资料，生成结构化课件大纲。
## 教学要素
{intent_summary}

## 参考资料（来自知识库检索）
{rag_context}

## 输出要求
请仅输出严格 JSON，结构如下：
{{
    "slides": [
        {{
            "title": "幻灯片标题",
            "bullet_points": ["要点1", "要点2", "要点3"],
            "notes": "讲解备注",
            "layout": "content",
            "visual_suggestion": "建议配图或动画描述"
        }}
    ],
    "lesson_plan_sections": [
        {{
            "section": "教学环节名称",
            "duration": "时长",
            "content": "教学内容",
            "method": "教学方法"
        }}
    ],
    "games": [
        {{
            "type": "quiz|matching|sorting|fill_blank|true_false|flashcard|flow_fill",
            "topic": "游戏主题",
            "questions": [
                {{"question": "题目", "options": ["A", "B", "C", "D"], "answer": "A"}}
            ]
        }}
    ],
    "animation_steps": [
        {{
            "icon": "🔬",
            "title": "步骤简称（4-8字）",
            "description": "该步骤的详细说明，1-2句话"
        }}
    ]
}}

注意：
- 幻灯片数量控制在 {page_range} 页
- 第一页为封面，最后一页为总结
- 每页要点不超过 5 条
- 必须包含互动游戏设计
- animation_steps 按知识点逻辑拆解为 4-8 步，每步配一个相关 emoji
- 只输出 JSON，不要添加其他内容"""


class PipelineOrchestrator:
    """
    Central orchestrator for the courseware generation pipeline.

    This is the main entry point for all generation workflows.
    """

    def __init__(
        self,
        *,
        llm: LLMRouter,
        retriever: Any = None,       # RetrievalPipeline (Phase 6) or RAGEngine
        normalizer: SchemaNormalizer,
        generators: Optional[List[Any]] = None,
        store: Optional[SQLiteArtifactStore] = None,
        embedding_cache: Optional[EmbeddingCache] = None,
    ):
        self.llm = llm
        self.retriever = retriever
        self.normalizer = normalizer
        self.generators: Dict[ArtifactType, Any] = {}
        if generators:
            for g in generators:
                self.generators[g.artifact_type()] = g
        self.store = store or SQLiteArtifactStore()
        self.embedding_cache = embedding_cache

    async def generate(
        self,
        intent: TeachingIntent,
        *,
        session_id: str,
        indexes: Optional[List[str]] = None,
        output_types: Optional[List[ArtifactType]] = None,
    ) -> PipelineResult:
        """
        Full pipeline: plan 鈫?generate (parallel) 鈫?persist.

        Args:
            intent: What to teach.
            session_id: Session identifier.
            indexes: Which RAG indexes to search.
            output_types: Which artifacts to generate.

        Returns:
            PipelineResult with plan and all generated artifacts.
        """
        t0 = time.time()
        intent = self._enforce_biology_subject(intent)
        indexes = self._normalize_indexes(indexes)
        output_types = output_types or [
            ArtifactType.PPTX,
            ArtifactType.DOCX,
            ArtifactType.GAME_HTML,
            ArtifactType.ANIMATION_HTML,
        ]
        result = PipelineResult(session_id=session_id)

        # 鈹€鈹€ Phase 1: Planning (serial) 鈹€鈹€
        try:
            plan = await self._plan(intent, indexes)
            result.plan = plan
        except Exception as e:
            logger.error("Planning failed: %s", e, exc_info=True)
            result.errors.append(f"Planning failed: {e}")
            result.total_time_sec = time.time() - t0
            return result

        # 鈹€鈹€ Phase 2: Generation (parallel) 鈹€鈹€
        tasks = []
        for atype in output_types:
            gen = self.generators.get(atype)
            if gen:
                tasks.append(self._generate_one(gen, plan, session_id))
            else:
                logger.warning("No generator registered for %s", atype.value)

        if tasks:
            artifacts = await asyncio.gather(*tasks, return_exceptions=True)
            for a in artifacts:
                if isinstance(a, Exception):
                    result.errors.append(str(a))
                    logger.error("Generation error: %s", a)
                elif isinstance(a, GeneratedArtifact):
                    result.artifacts.append(a)

        # 鈹€鈹€ Phase 3: Persist 鈹€鈹€
        for a in result.artifacts:
            self.store.save(session_id, a)

        version_id = self.store.create_snapshot(
            session_id,
            f"Generation v{plan.plan_version}",
            plan=plan,
            artifacts=result.artifacts,
        )
        result.version_id = version_id
        result.total_time_sec = time.time() - t0

        logger.info(
            "Pipeline completed for session %s: %d artifacts in %.1fs",
            session_id, len(result.artifacts), result.total_time_sec,
        )
        return result

    async def generate_stream(
        self,
        intent: TeachingIntent,
        *,
        session_id: str,
        indexes: Optional[List[str]] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        SSE streaming version 鈥?yields events for real-time frontend updates.

        Events:
          - OUTLINE_CHUNK: partial outline text
          - OUTLINE_DONE: completed plan
          - ARTIFACT_DONE: a single artifact completed
          - PIPELINE_DONE: all done
          - ERROR: something failed
        """
        intent = self._enforce_biology_subject(intent)
        indexes = self._normalize_indexes(indexes)

        # Phase A: Stream outline
        try:
            rag_context = await self._retrieve_context(intent, indexes)
            prompt = self._build_outline_prompt(intent, rag_context)

            outline_text = ""
            for chunk in self.llm.generate_stream(
                prompt, task="outline", max_tokens=4096
            ):
                outline_text += chunk
                yield {"event": "OUTLINE_CHUNK", "data": {"chunk": chunk}}

            # Normalize
            plan = self.normalizer.normalize_plan(outline_text, intent)
            # Streaming output can be truncated/non-JSON; retry once with strict JSON mode.
            if not plan.slides:
                logger.warning(
                    "Streaming outline parse produced 0 slides, retrying with non-stream JSON call"
                )
                raw_outline = await asyncio.to_thread(
                    self.llm.generate,
                    prompt,
                    task="outline",
                    max_tokens=4096,
                    expect_json=True,
                    json_schema={"required_keys": ["slides"]},
                    cache=False,
                )
                plan = self.normalizer.normalize_plan(raw_outline, intent)
            if not plan.slides:
                raise ValueError("Outline generation failed: could not parse valid slides JSON")
            plan.rag_context = rag_context

            yield {
                "event": "OUTLINE_DONE",
                "data": {
                    "plan": plan.model_dump(),
                    "slide_count": len(plan.slides),
                    "game_count": len(plan.game_specs),
                },
            }
        except Exception as e:
            logger.error("Streaming outline failed: %s", e, exc_info=True)
            yield {"event": "ERROR", "data": {"error": str(e)}}
            return

        # Phase B: Parallel generation
        async def _run_artifact_job(atype: ArtifactType, gen: Any):
            artifact = await self._generate_one(gen, plan, session_id)
            return atype, artifact

        task_list: List[asyncio.Task] = []
        for atype, gen in self.generators.items():
            task_list.append(asyncio.create_task(_run_artifact_job(atype, gen)))

        artifacts: List[GeneratedArtifact] = []
        for finished in asyncio.as_completed(task_list):
            try:
                atype, artifact = await finished
                artifacts.append(artifact)
                self.store.save(session_id, artifact)
                yield {
                    "event": "ARTIFACT_DONE",
                    "data": {
                        "artifact_type": atype.value,
                        "file_path": artifact.file_path,
                        "time_sec": artifact.generation_time_sec,
                    },
                }
            except Exception as e:
                yield {
                    "event": "ERROR",
                    "data": {"error": str(e)},
                }

        # Phase C: Persist snapshot

        version_id = self.store.create_snapshot(
            session_id, "Streaming generation", plan=plan, artifacts=artifacts
        )

        yield {
            "event": "PIPELINE_DONE",
            "data": {
                "session_id": session_id,
                "version_id": version_id,
                "artifact_count": len(artifacts),
            },
        }

    async def refine(
        self,
        request: RefineRequest,
        previous: PipelineResult,
    ) -> PipelineResult:
        """
        Cascade-aware refinement.

        Level 1-2: re-plan outline with feedback, regenerate targeted artifacts
        Level 3:   swap PPT template only (reuse existing plan)
        Level 4:   regenerate only the specified target_types
        Level 5:   finalize 鈥?no LLM call, just asset assembly
        """
        if previous.plan is None:
            return PipelineResult(
                session_id=request.session_id,
                errors=["No previous plan to refine"],
            )

        if request.cascade_level in (CascadeLevel.FIRST_GEN, CascadeLevel.OUTLINE_CHANGE):
            # Re-plan with feedback injected into context
            enhanced_intent = previous.plan.intent.model_copy()
            enhanced_intent.special_requirements += f"\n\n教师修改意见: {request.feedback}"
            return await self.generate(
                enhanced_intent,
                session_id=request.session_id,
                output_types=request.target_types,
            )

        elif request.cascade_level == CascadeLevel.TEMPLATE_SWAP:
            # Reuse existing plan, regenerate PPT only
            result = PipelineResult(
                session_id=request.session_id, plan=previous.plan
            )
            ppt_gen = self.generators.get(ArtifactType.PPTX)
            if ppt_gen:
                try:
                    artifact = await self._generate_one(
                        ppt_gen, previous.plan, request.session_id
                    )
                    result.artifacts.append(artifact)
                    self.store.save(request.session_id, artifact)
                except Exception as e:
                    result.errors.append(str(e))
            # Carry forward unchanged artifacts
            for a in previous.artifacts:
                if a.artifact_type != ArtifactType.PPTX:
                    result.artifacts.append(a)
            self.store.create_snapshot(
                request.session_id, "Template swap", plan=previous.plan, artifacts=result.artifacts
            )
            return result

        elif request.cascade_level == CascadeLevel.LOCAL_EDIT:
            # Regenerate only target types
            result = PipelineResult(
                session_id=request.session_id, plan=previous.plan
            )
            tasks = [
                self._generate_one(self.generators[t], previous.plan, request.session_id)
                for t in request.target_types
                if t in self.generators
            ]
            artifacts = await asyncio.gather(*tasks, return_exceptions=True)
            changed_types = set()
            for a in artifacts:
                if isinstance(a, GeneratedArtifact):
                    result.artifacts.append(a)
                    self.store.save(request.session_id, a)
                    changed_types.add(a.artifact_type)
                elif isinstance(a, Exception):
                    result.errors.append(str(a))
            # Carry forward unchanged
            for a in previous.artifacts:
                if a.artifact_type not in changed_types:
                    result.artifacts.append(a)
            self.store.create_snapshot(
                request.session_id, f"Local edit: {request.feedback[:50]}",
                plan=previous.plan, artifacts=result.artifacts
            )
            return result

        else:
            # Level 5: Asset finalize 鈥?placeholder
            return PipelineResult(
                session_id=request.session_id,
                plan=previous.plan,
                artifacts=previous.artifacts,
            )

    async def _plan(
        self, intent: TeachingIntent, indexes: List[str]
    ) -> CoursewarePlan:
        """Serial planning: retrieve 鈫?generate outline 鈫?normalize."""
        # 1. RAG retrieval
        rag_context = await self._retrieve_context(intent, indexes)

        # 2. LLM outline generation
        prompt = self._build_outline_prompt(intent, rag_context)
        raw_outline = await asyncio.to_thread(
            self.llm.generate,
            prompt,
            task="outline",
            max_tokens=4096,
            expect_json=True,
            json_schema={"required_keys": ["slides"]},
        )

        # 3. Schema normalization
        plan = self.normalizer.normalize_plan(raw_outline, intent)
        plan.rag_context = rag_context
        return plan

    async def _retrieve_context(
        self, intent: TeachingIntent, indexes: List[str]
    ) -> str:
        """Retrieve RAG context for outline generation."""
        if self.retriever is None:
            logger.warning("No retriever configured, skipping RAG")
            return ""

        query = self._build_retrieval_query(intent)

        try:
            raw_context = ""
            # RetrievalPipeline.retrieve_text() is the convenience method
            if hasattr(self.retriever, "retrieve_text"):
                text = await asyncio.to_thread(
                    self.retriever.retrieve_text,
                    query,
                    indexes=indexes,
                    top_k=10,
                )
                raw_context = text or ""
            # Fallback: RAGEngine.retrieve() returns List[EvidenceItem]
            elif hasattr(self.retriever, "retrieve"):
                result = await asyncio.to_thread(
                    self.retriever.retrieve,
                    query,
                    top_k=10,
                )
                if isinstance(result, list):
                    raw_context = "\n\n".join(
                        getattr(item, "text", str(item)) for item in result
                    )
                elif hasattr(result, "chunks"):
                    raw_context = "\n\n".join(c.chunk.text for c in result.chunks[:10])

            return self._compact_rag_context(raw_context)
        except Exception as e:
            logger.warning("RAG retrieval failed (continuing without): %s", e)
            return ""

    async def _generate_one(
        self, gen: Any, plan: CoursewarePlan, session_id: str
    ) -> GeneratedArtifact:
        """Run one generator in a thread (CPU/IO-bound)."""
        output_dir = f"outputs/{session_id}"
        return await asyncio.to_thread(gen.generate, plan, output_dir)

    def _build_outline_prompt(
        self, intent: TeachingIntent, rag_context: str
    ) -> str:
        """Build the outline generation prompt."""
        domain_hint = (
            "项目主题: 智绘生物。"
            "知识库范围: 高中生物《分子与细胞》《遗传与进化》, "
            "重点含中心法则、DNA复制、转录、翻译、减数分裂。"
        )
        return _OUTLINE_PROMPT.format(
            intent_summary=f"{intent.summary_text()}\n{domain_hint}",
            rag_context=rag_context or "（无参考资料）",
            page_range=intent.page_range,
        )

    @staticmethod
    def _enforce_biology_subject(intent: TeachingIntent) -> TeachingIntent:
        """Project constraint: this deployment currently uses biology-only knowledge bases."""
        updates: Dict[str, Any] = {}
        if (intent.subject or "").strip() != "生物":
            updates["subject"] = "生物"
        if not (intent.topic or intent.chapter):
            updates["topic"] = "智绘生物"
        return intent.model_copy(update=updates) if updates else intent

    @staticmethod
    def _normalize_indexes(indexes: Optional[List[str]]) -> List[str]:
        values = indexes or ["kb"]
        cleaned: List[str] = []
        seen = set()
        for item in values:
            key = str(item or "").strip()
            if not key or key in seen:
                continue
            seen.add(key)
            cleaned.append(key)
        if "kb" not in seen:
            cleaned.insert(0, "kb")
        return cleaned

    @staticmethod
    def _build_retrieval_query(intent: TeachingIntent) -> str:
        kb_focus = "分子与细胞 遗传与进化 中心法则 DNA复制 转录 翻译 减数分裂"
        parts = [
            "智绘生物",
            "高中生物",
            kb_focus,
            intent.topic or intent.chapter,
            intent.teaching_goal,
            " ".join(intent.key_focus),
            " ".join(intent.difficulties),
            intent.target_audience,
            intent.grade_level,
        ]
        merged = " ".join(p.strip() for p in parts if p and p.strip())
        return re.sub(r"\s+", " ", merged).strip() or "智绘生物 高中生物"

    @staticmethod
    def _compact_rag_context(text: str, *, max_chars: int = 6000, max_blocks: int = 10) -> str:
        if not text:
            return ""

        raw_blocks = [b.strip() for b in re.split(r"\n\s*\n+", text) if b.strip()]
        unique_blocks: List[str] = []
        seen = set()
        for block in raw_blocks:
            normalized = re.sub(r"\s+", " ", block).strip().lower()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            unique_blocks.append(block)
            if len(unique_blocks) >= max_blocks:
                break

        compact_blocks: List[str] = []
        total = 0
        for block in unique_blocks:
            remain = max_chars - total
            if remain <= 0:
                break
            clipped = block if len(block) <= remain else block[:remain].rstrip()
            if clipped:
                compact_blocks.append(clipped)
                total += len(clipped)

        return "\n\n".join(compact_blocks)
