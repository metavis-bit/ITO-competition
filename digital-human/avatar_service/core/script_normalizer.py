from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class Segment:
    index: int
    text: str
    kind: str = "narration"
    metadata: dict[str, str] = field(default_factory=dict)


class ScriptNormalizer:
    """Normalize structured script fragments into deterministic subtitle text."""

    def build_segments(self, *parts: str) -> list[Segment]:
        segments: list[Segment] = []
        for index, part in enumerate(parts, start=1):
            cleaned = self._clean_text(part)
            if cleaned:
                segments.append(Segment(index=index, text=cleaned))
        return segments

    def build_subtitle(self, segments: list[Segment]) -> str:
        return "".join(segment.text for segment in segments)

    def normalize_sentence(self, text: str) -> str:
        cleaned = self._clean_text(text)
        if not cleaned:
            return ""
        return cleaned if cleaned.endswith("。") else f"{cleaned}。"

    def _clean_text(self, text: str) -> str:
        return " ".join(text.split()).strip()
