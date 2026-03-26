from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class TraceEvent:
    step: str
    message: str
    data: Dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=lambda: time.time())


class TraceLog:
    """A tiny structured trace collector.

    We keep it JSON-serializable so frontends can stream or render it.
    """

    def __init__(self):
        self._events: List[TraceEvent] = []

    def add(self, step: str, message: str, **data: Any) -> None:
        self._events.append(TraceEvent(step=step, message=message, data=data))

    def extend(self, events: List[Dict[str, Any]]) -> None:
        for e in events:
            self.add(e.get("step", "unknown"), e.get("message", ""), **(e.get("data", {}) or {}))

    def as_dicts(self) -> List[Dict[str, Any]]:
        return [
            {
                "ts": e.ts,
                "step": e.step,
                "message": e.message,
                "data": e.data,
            }
            for e in self._events
        ]


    @property
    def steps(self) -> List[Dict[str, Any]]:
        """Backward-compatible alias for older call sites."""
        return self.as_dicts()
    def last(self) -> Optional[Dict[str, Any]]:
        if not self._events:
            return None
        e = self._events[-1]
        return {"ts": e.ts, "step": e.step, "message": e.message, "data": e.data}
