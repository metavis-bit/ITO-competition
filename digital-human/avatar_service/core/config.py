from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field, model_validator


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


class Settings(BaseModel):
    app_name: str = "Avatar Service"
    app_version: str = "0.1.0"
    storage_root: Path = Field(default_factory=lambda: Path.cwd() / "data")
    audio_root: Path | None = None
    session_dir_name: str = "sessions"
    task_dir_name: str = "tasks"
    audio_dir_name: str = "audio"
    default_voice: str = "Cherry"
    default_speed: str = "+0%"
    log_level: str = "INFO"
    allow_text_only_fallback_on_tts_error: bool = Field(
        default_factory=lambda: _env_bool("AVATAR_ALLOW_TEXT_ONLY_FALLBACK", True)
    )
    voice_profile_enabled: bool = Field(
        default_factory=lambda: _env_bool("AVATAR_VOICE_PROFILE_ENABLED", True)
    )
    voice_profile_api_base_url: str | None = Field(
        default_factory=lambda: os.getenv("AVATAR_VOICE_PROFILE_BASE_URL") or os.getenv("OPENAI_BASE_URL")
    )
    voice_profile_api_key: str | None = Field(
        default_factory=lambda: os.getenv("AVATAR_VOICE_PROFILE_API_KEY") or os.getenv("OPENAI_API_KEY")
    )
    voice_profile_model: str = Field(default_factory=lambda: os.getenv("AVATAR_VOICE_PROFILE_MODEL", "gpt-4o-mini"))
    voice_profile_timeout_sec: float = Field(
        default_factory=lambda: _env_float("AVATAR_VOICE_PROFILE_TIMEOUT_SEC", 20.0)
    )
    voice_profile_max_image_chars: int = Field(
        default_factory=lambda: _env_int("AVATAR_VOICE_PROFILE_MAX_IMAGE_CHARS", 400000)
    )

    @model_validator(mode="after")
    def resolve_paths(self) -> "Settings":
        if self.audio_root is None:
            self.audio_root = self.storage_root / self.audio_dir_name
        return self

    @property
    def session_root(self) -> Path:
        return self.storage_root / self.session_dir_name

    @property
    def task_root(self) -> Path:
        return self.storage_root / self.task_dir_name

    def ensure_directories(self) -> None:
        self.storage_root.mkdir(parents=True, exist_ok=True)
        self.session_root.mkdir(parents=True, exist_ok=True)
        self.task_root.mkdir(parents=True, exist_ok=True)
        self.audio_root.mkdir(parents=True, exist_ok=True)
