from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..domain.models import ArtifactType, PipelineResult, TeachingIntent
from ..infrastructure.llm import ModelTimeoutError, ProviderUnavailableError
from .pipeline_orchestrator import PipelineOrchestrator, _OUTLINE_MAX_TOKENS


@dataclass
class JobArtifactStatus:
    type: str
    status: str = "queued"
    error: Optional[str] = None


@dataclass
class CoursewareJob:
    job_id: str
    session_id: str
    intent: TeachingIntent
    indexes: List[str]
    output_types: List[ArtifactType]
    status: str = "queued"
    stage: str = "queued"
    progress: int = 0
    error: Optional[str] = None
    cancel_requested: bool = False
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    version_id: Optional[str] = None
    result: Optional[PipelineResult] = None
    artifact_statuses: List[JobArtifactStatus] = field(default_factory=list)


class CoursewareJobManager:
    def __init__(self, pipeline: PipelineOrchestrator):
        self.pipeline = pipeline
        self._jobs: Dict[str, CoursewareJob] = {}
        self._tasks: Dict[str, asyncio.Task[None]] = {}

    def create_job(
        self,
        *,
        intent: TeachingIntent,
        session_id: str,
        indexes: Optional[List[str]] = None,
        output_types: Optional[List[ArtifactType]] = None,
    ) -> CoursewareJob:
        normalized_indexes = self.pipeline._normalize_indexes(indexes)
        normalized_output_types = output_types or [
            ArtifactType.PPTX,
            ArtifactType.DOCX,
            ArtifactType.GAME_HTML,
            ArtifactType.ANIMATION_HTML,
        ]
        job = CoursewareJob(
            job_id=f"job_{uuid.uuid4().hex[:10]}",
            session_id=session_id,
            intent=intent,
            indexes=normalized_indexes,
            output_types=normalized_output_types,
            artifact_statuses=[
                JobArtifactStatus(type=artifact_type.value)
                for artifact_type in normalized_output_types
            ],
        )
        self._jobs[job.job_id] = job
        self._tasks[job.job_id] = asyncio.create_task(self._run_job(job))
        return job

    def get_job(self, job_id: str) -> Optional[CoursewareJob]:
        return self._jobs.get(job_id)

    def cancel_job(self, job_id: str) -> Optional[CoursewareJob]:
        job = self._jobs.get(job_id)
        if job is None:
            return None
        job.cancel_requested = True
        job.updated_at = time.time()
        task = self._tasks.get(job_id)
        if task and not task.done():
            task.cancel()
        if job.status == "queued":
            job.status = "cancelled"
            job.stage = "cancelled"
            job.progress = 100
            job.finished_at = time.time()
        return job

    def retry_job(self, job_id: str) -> Optional[CoursewareJob]:
        job = self._jobs.get(job_id)
        if job is None:
            return None
        return self.create_job(
            intent=job.intent.model_copy(deep=True),
            session_id=job.session_id,
            indexes=list(job.indexes),
            output_types=list(job.output_types),
        )

    async def _run_job(self, job: CoursewareJob) -> None:
        result = PipelineResult(session_id=job.session_id)
        try:
            self._set_stage(job, "normalize_input", 5, status="running")
            result.session_id = job.session_id

            self._ensure_not_cancelled(job)
            self._set_stage(job, "retrieve_context", 15)
            rag_context = await self.pipeline._retrieve_context(job.intent, job.indexes)

            self._ensure_not_cancelled(job)
            self._set_stage(job, "generate_outline", 35)
            prompt = self.pipeline._build_outline_prompt(job.intent, rag_context)
            raw_outline = await asyncio.to_thread(
                self.pipeline.llm.generate,
                prompt,
                task="outline",
                max_tokens=_OUTLINE_MAX_TOKENS,
                expect_json=True,
                json_schema={"required_keys": ["slides"]},
                timeout_sec=self.pipeline._outline_timeout_sec(),
                cache=False,
            )
            plan = self.pipeline.normalizer.normalize_plan(raw_outline, job.intent)
            plan.rag_context = rag_context
            result.plan = plan

            total_artifacts = max(1, len(job.output_types))
            for index, artifact_type in enumerate(job.output_types):
                self._ensure_not_cancelled(job)
                artifact_status = next(
                    (item for item in job.artifact_statuses if item.type == artifact_type.value),
                    None,
                )
                if artifact_status is not None:
                    artifact_status.status = "running"
                    artifact_status.error = None
                progress = 40 + int((index / total_artifacts) * 45)
                self._set_stage(job, f"generate_{artifact_type.value}", progress)

                generator = self.pipeline.generators.get(artifact_type)
                if generator is None:
                    message = f"No generator registered for {artifact_type.value}"
                    if artifact_status is not None:
                        artifact_status.status = "failed"
                        artifact_status.error = message
                    result.errors.append(message)
                    continue

                try:
                    artifact = await self.pipeline._generate_one(generator, plan, job.session_id)
                    result.artifacts.append(artifact)
                    self.pipeline.store.save(job.session_id, artifact)
                    if artifact_status is not None:
                        artifact_status.status = "done"
                except Exception as exc:
                    if artifact_status is not None:
                        artifact_status.status = "failed"
                        artifact_status.error = str(exc)
                    result.errors.append(str(exc))

            self._ensure_not_cancelled(job)
            self._set_stage(job, "persist_version", 95)
            result.version_id = self.pipeline.store.create_snapshot(
                job.session_id,
                f"Generation v{result.plan.plan_version}" if result.plan else "Generation",
                plan=result.plan,
                artifacts=result.artifacts,
            )
            result.total_time_sec = max(0.0, time.time() - job.created_at)

            job.result = result
            job.version_id = result.version_id
            self._set_stage(job, "completed", 100, status="succeeded")
            job.finished_at = time.time()
        except asyncio.CancelledError:
            job.result = result
            self._set_stage(job, "cancelled", min(job.progress, 100), status="cancelled")
            job.error = "Job cancelled"
            job.finished_at = time.time()
        except ModelTimeoutError as exc:
            result.errors.append(f"Planning timed out: {exc}")
            job.result = result
            job.error = f"Planning timed out: {exc}"
            self._set_stage(job, job.stage or "generate_outline", job.progress or 35, status="failed")
            job.finished_at = time.time()
        except ProviderUnavailableError as exc:
            result.errors.append(f"Provider unavailable: {exc}")
            job.result = result
            job.error = f"Provider unavailable: {exc}"
            self._set_stage(job, job.stage or "generate_outline", job.progress or 35, status="failed")
            job.finished_at = time.time()
        except Exception as exc:
            result.errors.append(str(exc))
            job.result = result
            job.error = str(exc)
            self._set_stage(job, job.stage or "failed", job.progress, status="failed")
            job.finished_at = time.time()

    def _ensure_not_cancelled(self, job: CoursewareJob) -> None:
        if job.cancel_requested:
            raise asyncio.CancelledError()

    @staticmethod
    def _set_stage(job: CoursewareJob, stage: str, progress: int, *, status: Optional[str] = None) -> None:
        job.stage = stage
        job.progress = max(0, min(100, progress))
        job.updated_at = time.time()
        if status is not None:
            job.status = status
            if status == "running" and job.started_at is None:
                job.started_at = job.updated_at
