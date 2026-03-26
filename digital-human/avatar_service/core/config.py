from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field, model_validator


class Settings(BaseModel):
    app_name: str = "Avatar Service"
    app_version: str = "0.1.0"
    storage_root: Path = Field(default_factory=lambda: Path.cwd() / "data")
    audio_root: Path | None = None
    session_dir_name: str = "sessions"
    task_dir_name: str = "tasks"
    audio_dir_name: str = "audio"
    default_voice: str = "zh-CN-XiaoxiaoNeural"
    default_speed: str = "+0%"
    log_level: str = "INFO"

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
