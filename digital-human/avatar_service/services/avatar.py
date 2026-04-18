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
from avatar_service.models.enums import AvatarState, CommandType, ModeType
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
from avatar_service.services.tts import RuntimeTTSConfig, TTSProvider
from avatar_service.services.voice_profile import AvatarVoiceProfileService, RuntimeVoiceProfileConfig
from avatar_service.core.command_router import CommandResolution

logger = logging.getLogger(__name__)


class AvatarService:
    """High-level orchestrator that coordinates planning, state and task execution."""

    def __init__(self, settings: Settings, store: LocalFileStore, tts_provider: TTSProvider) -> None:
        self.settings = settings
        self.store = store
        self.tts_provider = tts_provider
        self.voice_profile_service = AvatarVoiceProfileService(settings)

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
            allow_text_only_fallback_on_tts_error=settings.allow_text_only_fallback_on_tts_error,
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

    async def create_opening_task(
        self,
        session_id: str,
        request: OpeningBroadcastRequest,
        runtime_profile: RuntimeVoiceProfileConfig | None = None,
    ) -> SpeechTask:
        self.get_session(session_id)
        plan = self.script_planner.plan_opening(request)
        return await self._execute_plan(session_id, plan, runtime_profile=runtime_profile)

    async def create_slide_task(
        self,
        session_id: str,
        request: SlideBroadcastRequest,
        runtime_profile: RuntimeVoiceProfileConfig | None = None,
    ) -> SpeechTask:
        self.get_session(session_id)
        plan = self.script_planner.plan_slide(request)
        return await self._execute_plan(session_id, plan, runtime_profile=runtime_profile)

    async def create_result_task(
        self,
        session_id: str,
        request: ResultStatusRequest,
        runtime_profile: RuntimeVoiceProfileConfig | None = None,
    ) -> SpeechTask:
        self.get_session(session_id)
        plan = self.script_planner.plan_result(request)
        return await self._execute_plan(session_id, plan, runtime_profile=runtime_profile)

    async def project_intro(
        self,
        request: ProjectIntroRequest,
        runtime_profile: RuntimeVoiceProfileConfig | None = None,
    ) -> SpeechTask:
        session = self.get_session(request.session_id)
        intro = self.session_manager.get_project_intro(request.session_id)

        effective_intro = intro
        try:
            generated_intro = await self.voice_profile_service.generate_project_intro_script(
                title=intro.title,
                summary=intro.summary,
                highlights=intro.highlights,
                metadata=session.metadata,
                runtime_profile=runtime_profile,
            )
            if generated_intro:
                update_payload: dict[str, object] = {}
                next_summary = generated_intro.get("summary")
                if isinstance(next_summary, str) and next_summary.strip():
                    update_payload["summary"] = next_summary.strip()
                next_highlights = generated_intro.get("highlights")
                if isinstance(next_highlights, list):
                    cleaned_highlights = [
                        item.strip()[:40]
                        for item in next_highlights
                        if isinstance(item, str) and item.strip()
                    ][:4]
                    if cleaned_highlights:
                        update_payload["highlights"] = cleaned_highlights
                if update_payload:
                    effective_intro = intro.model_copy(update=update_payload)
        except Exception as exc:  # pragma: no cover
            logger.warning("Dynamic project intro generation failed for session %s: %s", request.session_id, exc)

        plan = self.script_planner.plan_project_intro(effective_intro, request.voice, request.speed)
        return await self._execute_plan(request.session_id, plan, runtime_profile=runtime_profile)

    async def ppt_explain(
        self,
        request: PPTExplainRequest,
        runtime_profile: RuntimeVoiceProfileConfig | None = None,
    ) -> SpeechTask:
        session = self.get_session(request.session_id)
        script = self.session_manager.get_ppt_script(request.session_id, request.slide_no)

        effective_script = script
        try:
            generated_script = await self.voice_profile_service.generate_slide_explain_script(
                slide_no=script.slide_no,
                level=request.level,
                title=script.title,
                bullets=script.bullets,
                speaker_notes=script.speaker_notes,
                summary=script.summary,
                metadata=session.metadata,
                runtime_profile=runtime_profile,
            )
            if generated_script:
                update_payload: dict[str, object] = {}
                next_notes = generated_script.get("speaker_notes")
                if isinstance(next_notes, str) and next_notes.strip():
                    update_payload["speaker_notes"] = next_notes.strip()
                next_summary = generated_script.get("summary")
                if isinstance(next_summary, str) and next_summary.strip():
                    update_payload["summary"] = next_summary.strip()
                if update_payload:
                    effective_script = script.model_copy(update=update_payload)
        except Exception as exc:  # pragma: no cover
            logger.warning("Dynamic slide script generation failed for session %s: %s", request.session_id, exc)

        plan = self.script_planner.plan_ppt_explain(effective_script, request.level, request.voice, request.speed)
        return await self._execute_plan(request.session_id, plan, runtime_profile=runtime_profile)

    async def broadcast(
        self,
        request: BroadcastRequest,
        runtime_profile: RuntimeVoiceProfileConfig | None = None,
    ) -> SpeechTask:
        try:
            event = self.session_manager.get_result_event(request.session_id, request.event)
        except HTTPException as exc:
            if exc.status_code != status.HTTP_404_NOT_FOUND:
                raise
            # Unknown event names are treated as direct ad-hoc speech, not status template.
            direct_resolution = CommandResolution(
                kind="direct_speech",
                command=CommandType.BROADCAST_EVENT,
                mode=ModeType.INTERACTION,
                avatar_state=AvatarState.SPEAKING,
                subtitle=request.event,
                command_family="official",
            )
            direct_plan = self.script_planner.plan_command(direct_resolution, request.voice, request.speed)
            return await self._execute_plan(request.session_id, direct_plan, runtime_profile=runtime_profile)
        plan = self.script_planner.plan_broadcast(event, request.voice, request.speed)
        return await self._execute_plan(request.session_id, plan, runtime_profile=runtime_profile)

    async def switch_mode(
        self,
        session_id: str,
        request: ModeSwitchRequest,
        runtime_profile: RuntimeVoiceProfileConfig | None = None,
    ) -> SpeechTask:
        session = self.get_session(session_id)
        plan = self.script_planner.plan_mode_switch(request, session.current_slide_no)
        return await self._execute_plan(session_id, plan, runtime_profile=runtime_profile)

    async def switch_mode_request(
        self,
        request: ModeSwitchRequest,
        runtime_profile: RuntimeVoiceProfileConfig | None = None,
    ) -> SessionState:
        session_id = self._require_formal_session_id(request.session_id, "mode switch")
        session = self.get_session(session_id)
        plan = self.script_planner.plan_mode_switch(request, session.current_slide_no)
        task = await self._execute_plan(session_id, plan, runtime_profile=runtime_profile)
        return self.session_manager.get_session(task.session_id)

    async def handle_command(
        self,
        session_id: str,
        request: CommandRequest,
        runtime_profile: RuntimeVoiceProfileConfig | None = None,
    ) -> SpeechTask:
        session = self.get_session(session_id)
        resolution = self.command_router.route(session, request)
        return await self._execute_command_resolution(
            session_id,
            resolution,
            request,
            runtime_profile=runtime_profile,
        )

    async def handle_command_request(
        self,
        request: CommandRequest,
        runtime_profile: RuntimeVoiceProfileConfig | None = None,
    ) -> SpeechTask:
        session_id = self._require_formal_session_id(request.session_id, "command")
        return await self.handle_command(session_id, request, runtime_profile=runtime_profile)

    def _require_formal_session_id(self, session_id: str | None, operation: str) -> str:
        if session_id and session_id.strip():
            return session_id
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"session_id is required for formal {operation} requests.",
        )

    async def _execute_plan(
        self,
        session_id: str,
        plan,
        runtime_profile: RuntimeVoiceProfileConfig | None = None,
    ) -> SpeechTask:
        session = self.get_session(session_id)
        try:
            voice_profile = await self.voice_profile_service.resolve_voice(
                session_id=session_id,
                explicit_voice=plan.voice,
                metadata=session.metadata,
                default_voice=self.settings.default_voice,
                runtime_profile=runtime_profile,
            )
            plan.voice = voice_profile.voice
            if plan.speed is None and voice_profile.speed:
                plan.speed = voice_profile.speed
            self.session_manager.update_session_metadata(
                session_id,
                self.voice_profile_service.metadata_patch(voice_profile),
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("Voice profile resolution failed for session %s: %s", session_id, exc)

        runtime_tts = RuntimeTTSConfig(
            api_base_url=runtime_profile.api_base_url if runtime_profile else None,
            api_key=runtime_profile.api_key if runtime_profile else None,
            model=runtime_profile.model if runtime_profile else None,
            provider_id=runtime_profile.provider_id if runtime_profile else None,
        )
        task = await self.task_manager.create_task(session_id, plan, runtime_tts=runtime_tts)
        self.session_manager.apply_task(session_id, task, plan)
        return task

    async def _execute_command_resolution(
        self,
        session_id: str,
        resolution,
        request: CommandRequest,
        runtime_profile: RuntimeVoiceProfileConfig | None = None,
    ) -> SpeechTask:
        if resolution.kind == "project_intro":
            intro = self.session_manager.get_project_intro(session_id)
            plan = self.script_planner.plan_project_intro(intro, request.voice, request.speed)
            return await self._execute_plan(session_id, plan, runtime_profile=runtime_profile)

        if resolution.kind == "ppt_explain":
            script = self.session_manager.get_ppt_script(session_id, resolution.slide_no)
            plan = self.script_planner.plan_ppt_explain(script, resolution.explain_level, request.voice, request.speed)
            return await self._execute_plan(session_id, plan, runtime_profile=runtime_profile)

        if resolution.kind == "broadcast":
            event = self.session_manager.get_result_event(session_id, resolution.event_name)
            plan = self.script_planner.plan_broadcast(event, request.voice, request.speed)
            return await self._execute_plan(session_id, plan, runtime_profile=runtime_profile)

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
            return await self._execute_plan(session_id, plan, runtime_profile=runtime_profile)

        plan = self.script_planner.plan_command(resolution, request.voice, request.speed)
        return await self._execute_plan(session_id, plan, runtime_profile=runtime_profile)
