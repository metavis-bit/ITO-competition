from __future__ import annotations

from enum import Enum


class ModeType(str, Enum):
    IDLE = "idle"
    PROJECT_INTRO = "project_intro"
    PPT_EXPLAIN = "ppt_explain"
    RESULT_BROADCAST = "result_broadcast"
    INTERACTION = "interaction"
    PAUSED = "paused"


LEGACY_MODE_ALIASES: dict[str, ModeType] = {
    "presentation": ModeType.PPT_EXPLAIN,
    "result": ModeType.RESULT_BROADCAST,
    "project_intro": ModeType.PROJECT_INTRO,
    "ppt_explain": ModeType.PPT_EXPLAIN,
    "result_broadcast": ModeType.RESULT_BROADCAST,
    "interaction": ModeType.INTERACTION,
    "paused": ModeType.PAUSED,
    "idle": ModeType.IDLE,
}


def coerce_mode(value: str | ModeType | None) -> ModeType | None:
    if value is None or isinstance(value, ModeType):
        return value
    normalized = LEGACY_MODE_ALIASES.get(str(value).strip())
    if normalized is None:
        raise ValueError(f"Unsupported mode: {value}")
    return normalized


class AvatarState(str, Enum):
    IDLE = "idle"
    SPEAKING = "speaking"
    PAUSED = "paused"
    AWAITING_COMMAND = "awaiting_command"
    COMPLETED = "completed"
    ERROR = "error"


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class DurationSource(str, Enum):
    ESTIMATED = "estimated"
    MEASURED = "measured"


class EventType(str, Enum):
    OPENING_OVERVIEW = "opening_overview"
    SLIDE_NARRATION = "slide_narration"
    RESULT_STATUS = "result_status"
    MODE_SWITCH = "mode_switch"
    COMMAND_INTERACTION = "command_interaction"


class ResultLevel(str, Enum):
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"
    INFO = "info"


class CommandType(str, Enum):
    PROJECT_INTRO = "project_intro"
    REPLAY_INTRO = "replay_intro"
    EXPLAIN_CURRENT_SLIDE = "explain_current_slide"
    SUMMARIZE_CURRENT_SLIDE = "summarize_current_slide"
    BROADCAST_EVENT = "broadcast_event"
    SWITCH_MODE = "switch_mode"
    REPEAT_LAST = "repeat_last"
    PAUSE = "pause"
    RESUME = "resume"
    NEXT_SLIDE = "next_slide"
    PREVIOUS_SLIDE = "previous_slide"
