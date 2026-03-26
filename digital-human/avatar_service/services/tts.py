from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from avatar_service.models.enums import DurationSource

logger = logging.getLogger(__name__)


class TTSError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def estimate_duration_seconds(text: str) -> float:
    stripped = re.sub(r"\s+", "", text)
    if not stripped:
        return 0.0
    return round(max(1.0, len(stripped) / 4.5), 1)


def normalize_speed(speed: str | float | int | None, default_speed: str = "+0%") -> str:
    if speed is None or speed == "":
        return default_speed

    if isinstance(speed, (int, float)):
        numeric = float(speed)
        if -100.0 <= numeric <= 100.0 and numeric.is_integer():
            return f"{numeric:+.0f}%"
        percentage = round((numeric - 1.0) * 100.0)
        return f"{percentage:+d}%"

    value = str(speed).strip()
    if re.fullmatch(r"[+-]?\d+%", value):
        if value.startswith(("+", "-")):
            return value
        return f"+{value}"
    if re.fullmatch(r"[+-]?\d+(\.\d+)?", value):
        numeric = float(value)
        if -100.0 <= numeric <= 100.0 and numeric.is_integer():
            return f"{numeric:+.0f}%"
        percentage = round((numeric - 1.0) * 100.0)
        return f"{percentage:+d}%"
    raise TTSError("TTS_INVALID_SPEED", f"Unsupported speed value: {speed}")


@dataclass(slots=True)
class ProviderSynthesisResult:
    duration_sec: float
    duration_source: DurationSource = DurationSource.ESTIMATED


@dataclass(slots=True)
class SynthesizedAudio:
    audio_path: Path
    audio_url: str
    duration_sec: float
    duration_source: DurationSource
    cache_hit: bool
    voice: str
    speed: str


class TTSProvider(Protocol):
    async def synthesize(
        self,
        text: str,
        output_path: Path,
        voice: str,
        speed: str,
    ) -> ProviderSynthesisResult:
        """Generate audio file for the supplied text."""


class CachedTTSService:
    def __init__(self, provider: TTSProvider, audio_root: Path, default_speed: str) -> None:
        self.provider = provider
        self.audio_root = audio_root
        self.default_speed = default_speed
        self.cache_root = self.audio_root / "cache"
        self.cache_root.mkdir(parents=True, exist_ok=True)

    async def synthesize(self, text: str, voice: str, speed: str | float | int | None) -> SynthesizedAudio:
        if not text or not text.strip():
            raise TTSError("TTS_EMPTY_TEXT", "Text for speech synthesis must not be empty.")

        normalized_speed = normalize_speed(speed, self.default_speed)
        cache_key = self._build_cache_key(text=text, voice=voice, speed=normalized_speed)
        audio_path = self.cache_root / f"{cache_key}.mp3"
        meta_path = self.cache_root / f"{cache_key}.json"
        audio_url = f"/media/cache/{cache_key}.mp3"

        if audio_path.exists():
            metadata = self._load_or_build_metadata(meta_path=meta_path, text=text)
            return SynthesizedAudio(
                audio_path=audio_path,
                audio_url=audio_url,
                duration_sec=metadata["duration_sec"],
                duration_source=DurationSource(metadata["duration_source"]),
                cache_hit=True,
                voice=voice,
                speed=normalized_speed,
            )

        try:
            audio_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise TTSError("TTS_OUTPUT_WRITE_ERROR", f"Audio cache path is not writable: {exc}") from exc

        provider_result = await self.provider.synthesize(
            text=text,
            output_path=audio_path,
            voice=voice,
            speed=normalized_speed,
        )
        self._write_metadata(
            meta_path=meta_path,
            duration_sec=provider_result.duration_sec,
            duration_source=provider_result.duration_source,
        )
        return SynthesizedAudio(
            audio_path=audio_path,
            audio_url=audio_url,
            duration_sec=provider_result.duration_sec,
            duration_source=provider_result.duration_source,
            cache_hit=False,
            voice=voice,
            speed=normalized_speed,
        )

    def _build_cache_key(self, text: str, voice: str, speed: str) -> str:
        payload = f"{voice}\n{speed}\n{text}".encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def _load_or_build_metadata(self, meta_path: Path, text: str) -> dict[str, str | float]:
        if meta_path.exists():
            try:
                return json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise TTSError("TTS_CACHE_METADATA_ERROR", f"Failed to read cache metadata: {exc}") from exc
        duration_sec = estimate_duration_seconds(text)
        metadata = {
            "duration_sec": duration_sec,
            "duration_source": DurationSource.ESTIMATED.value,
        }
        self._write_metadata(meta_path, duration_sec, DurationSource.ESTIMATED)
        return metadata

    def _write_metadata(self, meta_path: Path, duration_sec: float, duration_source: DurationSource) -> None:
        payload = {
            "duration_sec": duration_sec,
            "duration_source": duration_source.value,
        }
        try:
            meta_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            raise TTSError("TTS_CACHE_METADATA_ERROR", f"Failed to write cache metadata: {exc}") from exc


class EdgeTTSProvider:
    async def synthesize(
        self,
        text: str,
        output_path: Path,
        voice: str,
        speed: str,
    ) -> ProviderSynthesisResult:
        try:
            import edge_tts
        except ModuleNotFoundError as exc:
            raise TTSError("TTS_NOT_INSTALLED", "edge-tts is not installed.") from exc

        if not text or not text.strip():
            raise TTSError("TTS_EMPTY_TEXT", "Text for speech synthesis must not be empty.")

        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            logger.info("Synthesizing audio with edge-tts: voice=%s speed=%s path=%s", voice, speed, output_path)
            communicate = edge_tts.Communicate(text=text, voice=voice, rate=speed)
            await communicate.save(str(output_path))
            return ProviderSynthesisResult(
                duration_sec=estimate_duration_seconds(text),
                duration_source=DurationSource.ESTIMATED,
            )
        except PermissionError as exc:
            raise TTSError("TTS_OUTPUT_WRITE_ERROR", f"Output path is not writable: {exc}") from exc
        except OSError as exc:
            raise TTSError("TTS_OUTPUT_WRITE_ERROR", f"Failed to write audio output: {exc}") from exc
        except Exception as exc:
            error_name = exc.__class__.__name__.lower()
            if "timeout" in error_name or "client" in error_name or "connect" in str(exc).lower():
                raise TTSError("TTS_NETWORK_ERROR", f"edge-tts network failure: {exc}") from exc
            raise TTSError("TTS_SYNTHESIS_ERROR", f"edge-tts synthesis failed: {exc}") from exc
