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
from avatar_service.services.tts import EdgeTTSProvider, TTSProvider

def get_service(request: Request) -> AvatarService:
    return request.app.state.avatar_service


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
        tts_provider=tts_provider or EdgeTTSProvider(),
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
    async def load_session(request: SessionLoadRequest, service: AvatarService = Depends(get_service)) -> SessionState:
        return service.load_session(request)

    @app.post("/api/avatar/project-intro", response_model=SpeechTask)
    async def project_intro(request: ProjectIntroRequest, service: AvatarService = Depends(get_service)) -> SpeechTask:
        return await service.project_intro(request)

    @app.post("/api/avatar/ppt-explain", response_model=SpeechTask)
    async def ppt_explain(request: PPTExplainRequest, service: AvatarService = Depends(get_service)) -> SpeechTask:
        return await service.ppt_explain(request)

    @app.post("/api/avatar/broadcast", response_model=SpeechTask)
    async def broadcast(request: BroadcastRequest, service: AvatarService = Depends(get_service)) -> SpeechTask:
        return await service.broadcast(request)

    @app.post("/api/avatar/mode/switch", response_model=SessionState)
    async def switch_mode_request(request: ModeSwitchRequest, service: AvatarService = Depends(get_service)) -> SessionState:
        return await service.switch_mode_request(request)

    @app.post("/api/avatar/command", response_model=SpeechTask)
    async def handle_command_request(request: CommandRequest, service: AvatarService = Depends(get_service)) -> SpeechTask:
        return await service.handle_command_request(request)

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
        request: OpeningBroadcastRequest,
        service: AvatarService = Depends(get_service),
    ) -> SpeechTask:
        return await service.create_opening_task(session_id, request)

    @app.post("/sessions/{session_id}/slides", response_model=SpeechTask, deprecated=True)
    async def create_slide(
        session_id: str,
        request: SlideBroadcastRequest,
        service: AvatarService = Depends(get_service),
    ) -> SpeechTask:
        return await service.create_slide_task(session_id, request)

    @app.post("/sessions/{session_id}/results", response_model=SpeechTask, deprecated=True)
    async def create_result(
        session_id: str,
        request: ResultStatusRequest,
        service: AvatarService = Depends(get_service),
    ) -> SpeechTask:
        return await service.create_result_task(session_id, request)

    @app.post("/sessions/{session_id}/mode", response_model=SpeechTask, deprecated=True)
    async def switch_mode(
        session_id: str,
        request: ModeSwitchRequest,
        service: AvatarService = Depends(get_service),
    ) -> SpeechTask:
        return await service.switch_mode(session_id, request)

    @app.post("/sessions/{session_id}/commands", response_model=SpeechTask, deprecated=True)
    async def handle_command(
        session_id: str,
        request: CommandRequest,
        service: AvatarService = Depends(get_service),
    ) -> SpeechTask:
        return await service.handle_command(session_id, request)

    @app.get("/tasks/{task_id}", response_model=SpeechTask, deprecated=True)
    async def get_task(task_id: str, service: AvatarService = Depends(get_service)) -> SpeechTask:
        return service.get_task(task_id)

    return app


app = create_app()
