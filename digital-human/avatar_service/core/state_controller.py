from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from avatar_service.models.enums import AvatarState, ModeType
from avatar_service.models.schemas import SessionState, SpeechTask

if TYPE_CHECKING:
    from avatar_service.core.script_planner import ScriptPlan


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class StateController:
    """Owns avatar state mapping and session transition rules."""

    def mode_switch_avatar_state(self, target_mode: ModeType) -> AvatarState:
        if target_mode == ModeType.PAUSED:
            return AvatarState.PAUSED
        if target_mode == ModeType.IDLE:
            return AvatarState.IDLE
        if target_mode == ModeType.INTERACTION:
            return AvatarState.AWAITING_COMMAND
        return AvatarState.SPEAKING

    def apply_task(self, session: SessionState, task: SpeechTask, plan: ScriptPlan | None = None) -> SessionState:
        prior_mode = session.current_mode
        if task.mode == ModeType.PAUSED:
            session.previous_mode = prior_mode
        elif task.mode != prior_mode:
            session.previous_mode = prior_mode

        session.mode = task.mode
        session.current_mode = task.mode
        session.avatar_state = task.avatar_state
        if plan is None or plan.updates_current_slide:
            session.current_slide_no = task.slide_no if task.slide_no is not None else session.current_slide_no
        session.last_task_id = task.task_id
        session.last_subtitle = task.subtitle
        if plan and plan.last_event_name:
            session.last_event = plan.last_event_name
        if plan and plan.is_intro:
            session.last_intro_task_id = task.task_id
            session.last_intro_subtitle = task.subtitle
        session.updated_at = utcnow()
        return session
