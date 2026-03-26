from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, status

from avatar_service.core.script_planner import ScriptPlan
from avatar_service.models.enums import AvatarState, DurationSource, TaskStatus
from avatar_service.models.schemas import SpeechTask
from avatar_service.services.storage import LocalFileStore
from avatar_service.services.tts import CachedTTSService, TTSError, TTSProvider

logger = logging.getLogger(__name__)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TaskManager:
    """Create, persist and complete speech tasks."""

    def __init__(
        self,
        store: LocalFileStore,
        tts_provider: TTSProvider,
        audio_root: Path,
        default_voice: str,
        default_speed: str,
    ) -> None:
        self.store = store
        self.default_voice = default_voice
        self.default_speed = default_speed
        self.tts_service = CachedTTSService(tts_provider, audio_root=audio_root, default_speed=default_speed)

    def get_task(self, task_id: str) -> SpeechTask:
        task = self.store.load_task(task_id)
        if task is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")
        return task

    async def create_task(self, session_id: str, plan: ScriptPlan) -> SpeechTask:
        now = utcnow()
        task = SpeechTask(
            task_id=uuid4().hex,
            session_id=session_id,
            event_type=plan.event_type,
            audio_url=None,
            subtitle=plan.subtitle,
            avatar_state=plan.avatar_state,
            mode=plan.mode,
            voice=plan.voice or self.default_voice,
            speed=None,
            slide_no=plan.slide_no,
            status=TaskStatus.PENDING,
            duration_sec=0.0,
            duration_source=DurationSource.ESTIMATED,
            cache_hit=False,
            created_at=now,
            updated_at=now,
            error_message=None,
            error_code=None,
        )
        self.store.save_task(task)

        try:
            task.status = TaskStatus.RUNNING
            task.updated_at = utcnow()
            self.store.save_task(task)

            synth_result = await self.tts_service.synthesize(
                text=plan.subtitle,
                voice=task.voice,
                speed=plan.speed or self.default_speed,
            )
            task.audio_url = synth_result.audio_url
            task.duration_sec = synth_result.duration_sec
            task.duration_source = synth_result.duration_source
            task.cache_hit = synth_result.cache_hit
            task.speed = synth_result.speed
            task.status = TaskStatus.SUCCESS
            task.updated_at = utcnow()
        except TTSError as exc:
            logger.exception("Failed to create speech task %s", task.task_id)
            task.status = TaskStatus.FAILED
            task.avatar_state = AvatarState.ERROR
            task.error_message = exc.message
            task.error_code = exc.code
            task.updated_at = utcnow()
            self.store.save_task(task)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "task_id": task.task_id,
                    "error_code": exc.code,
                    "error_message": exc.message,
                },
            ) from exc
        except Exception as exc:  # pragma: no cover
            logger.exception("Failed to create speech task %s", task.task_id)
            task.status = TaskStatus.FAILED
            task.avatar_state = AvatarState.ERROR
            task.error_message = str(exc)
            task.error_code = "TTS_UNKNOWN_ERROR"
            task.updated_at = utcnow()
            self.store.save_task(task)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "task_id": task.task_id,
                    "error_code": "TTS_UNKNOWN_ERROR",
                    "error_message": str(exc),
                },
            ) from exc

        self.store.save_task(task)
        return task
