from __future__ import annotations

import logging

from fastapi import Depends, FastAPI, Request, status
from fastapi.staticfiles import StaticFiles

from avatar_service.core.config import Settings
from avatar_service.models.schemas import (
    BroadcastRequest,
    CommandRequest,
    HealthResponse,
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
    TaskQueryResponse,
)
from avatar_service.services.avatar import AvatarService
from avatar_service.services.storage import LocalFileStore
from avatar_service.services.tts import QwenTTSProvider, TTSProvider
from avatar_service.services.voice_profile import RuntimeVoiceProfileConfig

def get_service(request: Request) -> AvatarService:
    return request.app.state.avatar_service


def _sanitize_runtime_header(value: str | None, max_len: int) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned or len(cleaned) > max_len:
        return None
    if any(ord(ch) < 32 for ch in cleaned):
        return None
    return cleaned


def _extract_runtime_voice_profile(request: Request) -> RuntimeVoiceProfileConfig | None:
    base_url = _sanitize_runtime_header(request.headers.get("x-avatar-vlm-base-url"), 2048)
    api_key = _sanitize_runtime_header(request.headers.get("x-avatar-vlm-api-key"), 4096)
    model = _sanitize_runtime_header(request.headers.get("x-avatar-vlm-model"), 128)
    provider = _sanitize_runtime_header(request.headers.get("x-avatar-vlm-provider"), 64)
    if not base_url and not api_key and not model:
        return None
    return RuntimeVoiceProfileConfig(
        api_base_url=base_url,
        api_key=api_key,
        model=model,
        provider_id=provider,
    )


def create_app(
    settings: Settings | None = None,
    tts_provider: TTSProvider | None = None,
) -> FastAPI:
    settings = settings or Settings()
    settings.ensure_directories()
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
    store = LocalFileStore(settings)
    avatar_service = AvatarService(
        settings=settings,
        store=store,
        tts_provider=tts_provider or QwenTTSProvider(),
    )

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Independent avatar speech task service for deterministic narration workflows.",
    )
    app.state.avatar_service = avatar_service
    app.mount("/media", StaticFiles(directory=settings.audio_root), name="media")

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(status="ok", app_name=settings.app_name, version=settings.app_version)

    # Formal API
    @app.post("/api/avatar/session/load", response_model=SessionState, status_code=status.HTTP_201_CREATED)
    async def load_session(payload: SessionLoadRequest, service: AvatarService = Depends(get_service)) -> SessionState:
        return service.load_session(payload)

    @app.post("/api/avatar/project-intro", response_model=SpeechTask)
    async def project_intro(
        payload: ProjectIntroRequest,
        request: Request,
        service: AvatarService = Depends(get_service),
    ) -> SpeechTask:
        return await service.project_intro(
            payload,
            runtime_profile=_extract_runtime_voice_profile(request),
        )

    @app.post("/api/avatar/ppt-explain", response_model=SpeechTask)
    async def ppt_explain(
        payload: PPTExplainRequest,
        request: Request,
        service: AvatarService = Depends(get_service),
    ) -> SpeechTask:
        return await service.ppt_explain(
            payload,
            runtime_profile=_extract_runtime_voice_profile(request),
        )

    @app.post("/api/avatar/broadcast", response_model=SpeechTask)
    async def broadcast(
        payload: BroadcastRequest,
        request: Request,
        service: AvatarService = Depends(get_service),
    ) -> SpeechTask:
        return await service.broadcast(
            payload,
            runtime_profile=_extract_runtime_voice_profile(request),
        )

    @app.post("/api/avatar/mode/switch", response_model=SessionState)
    async def switch_mode_request(
        payload: ModeSwitchRequest,
        request: Request,
        service: AvatarService = Depends(get_service),
    ) -> SessionState:
        return await service.switch_mode_request(
            payload,
            runtime_profile=_extract_runtime_voice_profile(request),
        )

    @app.post("/api/avatar/command", response_model=SpeechTask)
    async def handle_command_request(
        payload: CommandRequest,
        request: Request,
        service: AvatarService = Depends(get_service),
    ) -> SpeechTask:
        return await service.handle_command_request(
            payload,
            runtime_profile=_extract_runtime_voice_profile(request),
        )

    @app.get("/api/avatar/task/{task_id}", response_model=TaskQueryResponse)
    async def query_task(task_id: str, service: AvatarService = Depends(get_service)) -> TaskQueryResponse:
        return TaskQueryResponse.model_validate(service.get_task(task_id).model_dump())

    # Legacy compatibility API
    @app.post("/sessions", response_model=SessionState, status_code=status.HTTP_201_CREATED, deprecated=True)
    async def create_session(request: SessionCreateRequest, service: AvatarService = Depends(get_service)) -> SessionState:
        return service.create_session(request)

    @app.get("/sessions/{session_id}", response_model=SessionState, deprecated=True)
    async def get_session(session_id: str, service: AvatarService = Depends(get_service)) -> SessionState:
        return service.get_session(session_id)

    @app.post("/sessions/{session_id}/opening", response_model=SpeechTask, deprecated=True)
    async def create_opening(
        session_id: str,
        payload: OpeningBroadcastRequest,
        service: AvatarService = Depends(get_service),
    ) -> SpeechTask:
        return await service.create_opening_task(session_id, payload)

    @app.post("/sessions/{session_id}/slides", response_model=SpeechTask, deprecated=True)
    async def create_slide(
        session_id: str,
        payload: SlideBroadcastRequest,
        service: AvatarService = Depends(get_service),
    ) -> SpeechTask:
        return await service.create_slide_task(session_id, payload)

    @app.post("/sessions/{session_id}/results", response_model=SpeechTask, deprecated=True)
    async def create_result(
        session_id: str,
        payload: ResultStatusRequest,
        service: AvatarService = Depends(get_service),
    ) -> SpeechTask:
        return await service.create_result_task(session_id, payload)

    @app.post("/sessions/{session_id}/mode", response_model=SpeechTask, deprecated=True)
    async def switch_mode(
        session_id: str,
        payload: ModeSwitchRequest,
        service: AvatarService = Depends(get_service),
    ) -> SpeechTask:
        return await service.switch_mode(session_id, payload)

    @app.post("/sessions/{session_id}/commands", response_model=SpeechTask, deprecated=True)
    async def handle_command(
        session_id: str,
        payload: CommandRequest,
        service: AvatarService = Depends(get_service),
    ) -> SpeechTask:
        return await service.handle_command(session_id, payload)

    @app.get("/tasks/{task_id}", response_model=SpeechTask, deprecated=True)
    async def get_task(task_id: str, service: AvatarService = Depends(get_service)) -> SpeechTask:
        return service.get_task(task_id)

    return app


app = create_app()
