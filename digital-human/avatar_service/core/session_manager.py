from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import HTTPException, status

from avatar_service.core.state_controller import StateController
from avatar_service.core.script_planner import ScriptPlan
from avatar_service.models.enums import AvatarState
from avatar_service.models.schemas import (
    ProjectIntroPayload,
    ResultEventItem,
    SessionCreateRequest,
    SessionLoadRequest,
    SessionState,
    SpeechTask,
    PPTScriptItem,
)
from avatar_service.services.storage import LocalFileStore


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SessionManager:
    """Manage session lifecycle, loaded content and persistence."""

    def __init__(self, store: LocalFileStore, state_controller: StateController) -> None:
        self.store = store
        self.state_controller = state_controller

    def create_session(self, request: SessionCreateRequest) -> SessionState:
        now = utcnow()
        session = SessionState(
            session_id=request.session_id or uuid4().hex,
            project_id=request.project_id,
            mode=request.initial_mode,
            current_mode=request.initial_mode,
            previous_mode=None,
            avatar_state=AvatarState.IDLE,
            current_slide_no=None,
            last_task_id=None,
            last_subtitle=None,
            last_event=None,
            last_intro_task_id=None,
            last_intro_subtitle=None,
            created_at=now,
            updated_at=now,
            metadata=request.metadata,
        )
        self.store.save_session(session)
        return session

    def load_session_content(self, request: SessionLoadRequest) -> SessionState:
        existing = self.store.load_session(request.session_id)
        now = utcnow()
        created_at = existing.created_at if existing else now
        session = SessionState(
            session_id=request.session_id,
            project_id=request.project_id,
            mode=request.initial_mode,
            current_mode=request.initial_mode,
            previous_mode=None,
            avatar_state=AvatarState.IDLE,
            current_slide_no=None,
            last_task_id=None,
            last_subtitle=None,
            last_event=None,
            last_intro_task_id=None,
            last_intro_subtitle=None,
            created_at=created_at,
            updated_at=now,
            metadata=request.metadata,
            project_intro=request.project_intro,
            ppt_scripts=sorted(request.ppt_scripts, key=lambda item: item.slide_no),
            result_events=request.result_events,
        )
        self.store.save_session(session)
        return session

    def get_session(self, session_id: str) -> SessionState:
        session = self.store.load_session(session_id)
        if session is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found.")
        return session

    def get_project_intro(self, session_id: str) -> ProjectIntroPayload:
        session = self.get_session(session_id)
        if session.project_intro is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project intro not loaded.")
        return session.project_intro

    def get_ppt_script(self, session_id: str, slide_no: int) -> PPTScriptItem:
        session = self.get_session(session_id)
        for item in session.ppt_scripts:
            if item.slide_no == slide_no:
                return item
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Slide {slide_no} not found.")

    def get_result_event(self, session_id: str, event_name: str) -> ResultEventItem:
        session = self.get_session(session_id)
        for item in session.result_events.events:
            if item.event == event_name:
                return item
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Event '{event_name}' not found.")

    def apply_task(self, session_id: str, task: SpeechTask, plan: ScriptPlan | None = None) -> SessionState:
        session = self.get_session(session_id)
        updated_session = self.state_controller.apply_task(session, task, plan)
        self.store.save_session(updated_session)
        return updated_session
