from __future__ import annotations

import json
from pathlib import Path

from avatar_service.core.config import Settings
from avatar_service.models.schemas import SessionState, SpeechTask


class LocalFileStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.settings.ensure_directories()

    def session_path(self, session_id: str) -> Path:
        return self.settings.session_root / f"{session_id}.json"

    def task_path(self, task_id: str) -> Path:
        return self.settings.task_root / f"{task_id}.json"

    def audio_path(self, session_id: str, task_id: str) -> Path:
        session_audio_root = self.settings.audio_root / session_id
        session_audio_root.mkdir(parents=True, exist_ok=True)
        return session_audio_root / f"{task_id}.mp3"

    def save_session(self, session: SessionState) -> None:
        self._write_json(self.session_path(session.session_id), session.model_dump(mode="json"))

    def load_session(self, session_id: str) -> SessionState | None:
        path = self.session_path(session_id)
        if not path.exists():
            return None
        return SessionState.model_validate_json(path.read_text(encoding="utf-8"))

    def save_task(self, task: SpeechTask) -> None:
        self._write_json(self.task_path(task.task_id), task.model_dump(mode="json"))

    def load_task(self, task_id: str) -> SpeechTask | None:
        path = self.task_path(task_id)
        if not path.exists():
            return None
        return SpeechTask.model_validate_json(path.read_text(encoding="utf-8"))

    def _write_json(self, path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(path.suffix + ".tmp")
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp_path.replace(path)
