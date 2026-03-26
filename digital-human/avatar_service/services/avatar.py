from __future__ import annotations

import logging

from fastapi import HTTPException, status

from avatar_service.core.command_router import CommandRouter
from avatar_service.core.config import Settings
from avatar_service.core.script_normalizer import ScriptNormalizer
from avatar_service.core.script_planner import ScriptPlanner
from avatar_service.core.session_manager import SessionManager
from avatar_service.core.state_controller import StateController
from avatar_service.core.task_manager import TaskManager
from avatar_service.models.schemas import (
    BroadcastRequest,
    CommandRequest,
    ModeSwitchRequest,
    OpeningBroadcastRequest,
    PPTExplainRequest,
    ProjectIntroRequest,
    ResultStatusRequest,
    SessionCreateRequest,
    SessionLoadRequest,
    SessionState,
    SlideBroadcastRequest,
    SpeechTask,
)
from avatar_service.services.storage import LocalFileStore
from avatar_service.services.tts import TTSProvider

logger = logging.getLogger(__name__)


class AvatarService:
    """High-level orchestrator that coordinates planning, state and task execution."""

    def __init__(self, settings: Settings, store: LocalFileStore, tts_provider: TTSProvider) -> None:
        self.settings = settings
        self.store = store
        self.tts_provider = tts_provider

        self.state_controller = StateController()
        self.normalizer = ScriptNormalizer()
        self.command_router = CommandRouter()
        self.script_planner = ScriptPlanner(self.normalizer, self.state_controller)
        self.session_manager = SessionManager(store, self.state_controller)
        self.task_manager = TaskManager(
            store,
            tts_provider,
            audio_root=settings.audio_root,
            default_voice=settings.default_voice,
            default_speed=settings.default_speed,
        )

    def create_session(self, request: SessionCreateRequest) -> SessionState:
        session = self.session_manager.create_session(request)
        logger.info("Created session %s", session.session_id)
        return session

    def load_session(self, request: SessionLoadRequest) -> SessionState:
        session = self.session_manager.load_session_content(request)
        logger.info("Loaded session %s with %s slides and %s events", session.session_id, len(session.ppt_scripts), len(session.result_events.events))
        return session

    def get_session(self, session_id: str) -> SessionState:
        return self.session_manager.get_session(session_id)

    def get_task(self, task_id: str) -> SpeechTask:
        return self.task_manager.get_task(task_id)

    async def create_opening_task(self, session_id: str, request: OpeningBroadcastRequest) -> SpeechTask:
        self.get_session(session_id)
        plan = self.script_planner.plan_opening(request)
        return await self._execute_plan(session_id, plan)

    async def create_slide_task(self, session_id: str, request: SlideBroadcastRequest) -> SpeechTask:
        self.get_session(session_id)
        plan = self.script_planner.plan_slide(request)
        return await self._execute_plan(session_id, plan)

    async def create_result_task(self, session_id: str, request: ResultStatusRequest) -> SpeechTask:
        self.get_session(session_id)
        plan = self.script_planner.plan_result(request)
        return await self._execute_plan(session_id, plan)

    async def project_intro(self, request: ProjectIntroRequest) -> SpeechTask:
        intro = self.session_manager.get_project_intro(request.session_id)
        plan = self.script_planner.plan_project_intro(intro, request.voice, request.speed)
        return await self._execute_plan(request.session_id, plan)

    async def ppt_explain(self, request: PPTExplainRequest) -> SpeechTask:
        script = self.session_manager.get_ppt_script(request.session_id, request.slide_no)
        plan = self.script_planner.plan_ppt_explain(script, request.level, request.voice, request.speed)
        return await self._execute_plan(request.session_id, plan)

    async def broadcast(self, request: BroadcastRequest) -> SpeechTask:
        event = self.session_manager.get_result_event(request.session_id, request.event)
        plan = self.script_planner.plan_broadcast(event, request.voice, request.speed)
        return await self._execute_plan(request.session_id, plan)

    async def switch_mode(self, session_id: str, request: ModeSwitchRequest) -> SpeechTask:
        session = self.get_session(session_id)
        plan = self.script_planner.plan_mode_switch(request, session.current_slide_no)
        return await self._execute_plan(session_id, plan)

    async def switch_mode_request(self, request: ModeSwitchRequest) -> SessionState:
        session_id = self._require_formal_session_id(request.session_id, "mode switch")
        session = self.get_session(session_id)
        plan = self.script_planner.plan_mode_switch(request, session.current_slide_no)
        task = await self._execute_plan(session_id, plan)
        return self.session_manager.get_session(task.session_id)

    async def handle_command(self, session_id: str, request: CommandRequest) -> SpeechTask:
        session = self.get_session(session_id)
        resolution = self.command_router.route(session, request)
        return await self._execute_command_resolution(session_id, resolution, request)

    async def handle_command_request(self, request: CommandRequest) -> SpeechTask:
        session_id = self._require_formal_session_id(request.session_id, "command")
        return await self.handle_command(session_id, request)

    def _require_formal_session_id(self, session_id: str | None, operation: str) -> str:
        if session_id and session_id.strip():
            return session_id
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"session_id is required for formal {operation} requests.",
        )

    async def _execute_plan(self, session_id: str, plan) -> SpeechTask:
        task = await self.task_manager.create_task(session_id, plan)
        self.session_manager.apply_task(session_id, task, plan)
        return task

    async def _execute_command_resolution(self, session_id: str, resolution, request: CommandRequest) -> SpeechTask:
        if resolution.kind == "project_intro":
            intro = self.session_manager.get_project_intro(session_id)
            plan = self.script_planner.plan_project_intro(intro, request.voice, request.speed)
            return await self._execute_plan(session_id, plan)

        if resolution.kind == "ppt_explain":
            script = self.session_manager.get_ppt_script(session_id, resolution.slide_no)
            plan = self.script_planner.plan_ppt_explain(script, resolution.explain_level, request.voice, request.speed)
            return await self._execute_plan(session_id, plan)

        if resolution.kind == "broadcast":
            event = self.session_manager.get_result_event(session_id, resolution.event_name)
            plan = self.script_planner.plan_broadcast(event, request.voice, request.speed)
            return await self._execute_plan(session_id, plan)

        if resolution.kind == "mode_switch":
            mode_request = ModeSwitchRequest(
                session_id=session_id,
                mode=resolution.target_mode,
                target_mode=resolution.target_mode,
                reason=request.params.get("reason") if isinstance(request.params.get("reason"), str) else None,
                speed=request.speed,
            )
            session = self.get_session(session_id)
            plan = self.script_planner.plan_mode_switch(mode_request, session.current_slide_no)
            return await self._execute_plan(session_id, plan)

        plan = self.script_planner.plan_command(resolution, request.voice, request.speed)
        return await self._execute_plan(session_id, plan)
