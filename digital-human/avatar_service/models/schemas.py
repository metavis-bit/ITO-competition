from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from avatar_service.models.enums import (
    AvatarState,
    CommandType,
    coerce_mode,
    DurationSource,
    EventType,
    ModeType,
    ResultLevel,
    TaskStatus,
)


class ProjectIntroPayload(BaseModel):
    title: str = Field(..., min_length=1)
    summary: str = Field(..., min_length=1)
    highlights: list[str] = Field(default_factory=list)
    voice: str | None = None
    speed: str | float | None = None


class PPTScriptItem(BaseModel):
    slide_no: int = Field(..., ge=1)
    title: str | None = None
    bullets: list[str] = Field(default_factory=list)
    speaker_notes: str | None = None
    summary: str | None = None
    voice: str | None = None
    speed: str | float | None = None


class ResultEventItem(BaseModel):
    event: str = Field(..., min_length=1)
    result_level: ResultLevel
    summary: str = Field(..., min_length=1)
    details: list[str] = Field(default_factory=list)
    next_action: str | None = None
    slide_no: int | None = Field(default=None, ge=1)
    voice: str | None = None
    speed: str | float | None = None


class ResultEventsPayload(BaseModel):
    events: list[ResultEventItem] = Field(default_factory=list)


class SessionCreateRequest(BaseModel):
    session_id: str | None = Field(default=None, description="Optional external session id.")
    project_id: str | None = Field(default=None, description="Upstream project id.")
    initial_mode: ModeType = Field(default=ModeType.IDLE)
    metadata: dict[str, str] = Field(default_factory=dict)

    @field_validator("initial_mode", mode="before")
    @classmethod
    def normalize_initial_mode(cls, value: str | ModeType) -> ModeType:
        return coerce_mode(value)


class SessionLoadRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    project_id: str | None = None
    project_intro: ProjectIntroPayload
    ppt_scripts: list[PPTScriptItem] = Field(..., min_length=1)
    result_events: ResultEventsPayload
    initial_mode: ModeType = ModeType.IDLE
    metadata: dict[str, str] = Field(default_factory=dict)

    @field_validator("initial_mode", mode="before")
    @classmethod
    def normalize_initial_mode(cls, value: str | ModeType) -> ModeType:
        return coerce_mode(value)


class SessionState(BaseModel):
    session_id: str
    project_id: str | None = None
    mode: ModeType = ModeType.IDLE
    current_mode: ModeType = ModeType.IDLE
    previous_mode: ModeType | None = None
    avatar_state: AvatarState = AvatarState.IDLE
    current_slide_no: int | None = None
    last_task_id: str | None = None
    last_subtitle: str | None = None
    last_event: str | None = None
    last_intro_task_id: str | None = None
    last_intro_subtitle: str | None = None
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, str] = Field(default_factory=dict)
    project_intro: ProjectIntroPayload | None = None
    ppt_scripts: list[PPTScriptItem] = Field(default_factory=list)
    result_events: ResultEventsPayload = Field(default_factory=ResultEventsPayload)

    @field_validator("mode", "current_mode", "previous_mode", mode="before")
    @classmethod
    def normalize_modes(cls, value: str | ModeType | None) -> ModeType | None:
        return coerce_mode(value)


class OpeningBroadcastRequest(BaseModel):
    title: str = Field(..., min_length=1, description="Project or lesson title.")
    summary: str = Field(..., min_length=1, description="Opening summary.")
    highlights: list[str] = Field(default_factory=list, description="Key points to highlight.")
    voice: str | None = Field(default=None, description="Optional edge-tts voice.")
    speed: str | float | None = Field(default=None, description="Optional speaking speed.")


class SlideBroadcastRequest(BaseModel):
    slide_no: int = Field(..., ge=1)
    title: str | None = Field(default=None, description="Slide title.")
    bullets: list[str] = Field(default_factory=list, description="Structured bullet points.")
    speaker_notes: str | None = Field(default=None, description="Extra explanation notes.")
    voice: str | None = Field(default=None, description="Optional edge-tts voice.")
    speed: str | float | None = Field(default=None, description="Optional speaking speed.")


class ResultStatusRequest(BaseModel):
    result_level: ResultLevel
    summary: str = Field(..., min_length=1)
    details: list[str] = Field(default_factory=list)
    next_action: str | None = Field(default=None)
    slide_no: int | None = Field(default=None, ge=1)
    voice: str | None = Field(default=None, description="Optional edge-tts voice.")
    speed: str | float | None = Field(default=None, description="Optional speaking speed.")


class ProjectIntroRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    voice: str | None = None
    speed: str | float | None = None


class PPTExplainRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    slide_no: int = Field(..., ge=1)
    level: Literal["full", "summary"] = "full"
    voice: str | None = None
    speed: str | float | None = None


class BroadcastRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    event: str = Field(..., min_length=1)
    voice: str | None = None
    speed: str | float | None = None


class ModeSwitchRequest(BaseModel):
    session_id: str | None = None
    target_mode: ModeType | None = Field(default=None, description="Legacy field for backward compatibility.")
    mode: ModeType | None = Field(default=None, description="New field for the formal API.")
    reason: str | None = Field(default=None, description="Optional reason for mode switch.")
    speed: str | float | None = Field(default=None, description="Optional speaking speed.")

    @model_validator(mode="after")
    def validate_mode(self) -> "ModeSwitchRequest":
        if self.mode is None and self.target_mode is None:
            raise ValueError("Either mode or target_mode must be provided.")
        if self.mode is None:
            self.mode = coerce_mode(self.target_mode)
        if self.target_mode is None:
            self.target_mode = coerce_mode(self.mode)
        self.mode = coerce_mode(self.mode)
        self.target_mode = coerce_mode(self.target_mode)
        return self


class CommandRequest(BaseModel):
    session_id: str | None = None
    command: CommandType
    slide_no: int | None = Field(default=None, ge=1, description="Optional explicit slide target.")
    params: dict[str, Any] = Field(default_factory=dict)
    voice: str | None = Field(default=None, description="Optional edge-tts voice.")
    speed: str | float | None = Field(default=None, description="Optional speaking speed.")

    @property
    def effective_slide_no(self) -> int | None:
        param_slide = self.params.get("slide_no")
        if isinstance(param_slide, int):
            return param_slide
        return self.slide_no

    @property
    def effective_event(self) -> str | None:
        param_event = self.params.get("event")
        if isinstance(param_event, str) and param_event.strip():
            return param_event.strip()
        return None

    @property
    def effective_mode(self) -> ModeType | None:
        param_mode = self.params.get("mode")
        if param_mode is None:
            return None
        return coerce_mode(param_mode)


class SpeechTask(BaseModel):
    task_id: str
    session_id: str
    event_type: EventType
    audio_url: str | None = None
    subtitle: str
    avatar_state: AvatarState
    mode: ModeType
    voice: str | None = None
    speed: str | None = None
    slide_no: int | None = None
    status: TaskStatus
    duration_sec: float = Field(default=0.0, ge=0.0)
    duration_source: DurationSource = DurationSource.ESTIMATED
    cache_hit: bool = False
    created_at: datetime
    updated_at: datetime
    error_message: str | None = None
    error_code: str | None = None


class TaskQueryResponse(SpeechTask):
    """Formal response model for task query. Keeps SpeechTask as the wire shape."""


class HealthResponse(BaseModel):
    status: str
    app_name: str
    version: str
