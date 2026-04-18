from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib import error as urllib_error
from urllib import request as urllib_request

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
    audio_format: str = "mp3"


@dataclass(slots=True)
class RuntimeTTSConfig:
    api_base_url: str | None = None
    api_key: str | None = None
    model: str | None = None
    provider_id: str | None = None


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
        runtime_config: RuntimeTTSConfig | None = None,
    ) -> ProviderSynthesisResult:
        """Generate audio file for the supplied text."""


class CachedTTSService:
    def __init__(self, provider: TTSProvider, audio_root: Path, default_speed: str) -> None:
        self.provider = provider
        self.audio_root = audio_root
        self.default_speed = default_speed
        self.cache_root = self.audio_root / "cache"
        self.cache_root.mkdir(parents=True, exist_ok=True)

    async def synthesize(
        self,
        text: str,
        voice: str,
        speed: str | float | int | None,
        runtime_config: RuntimeTTSConfig | None = None,
    ) -> SynthesizedAudio:
        if not text or not text.strip():
            raise TTSError("TTS_EMPTY_TEXT", "Text for speech synthesis must not be empty.")

        normalized_speed = normalize_speed(speed, self.default_speed)
        cache_key = self._build_cache_key(
            text=text,
            voice=voice,
            speed=normalized_speed,
            runtime_config=runtime_config,
        )
        format_ext = self._provider_output_format()
        audio_path = self.cache_root / f"{cache_key}.{format_ext}"
        meta_path = self.cache_root / f"{cache_key}.json"
        audio_url = f"/media/cache/{cache_key}.{format_ext}"

        if audio_path.exists():
            metadata = self._load_or_build_metadata(meta_path=meta_path, text=text, audio_format=format_ext)
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
            runtime_config=runtime_config,
        )
        actual_format = self._normalize_audio_format(provider_result.audio_format)
        if actual_format != format_ext:
            target_path = self.cache_root / f"{cache_key}.{actual_format}"
            if audio_path.exists():
                audio_path.replace(target_path)
            audio_path = target_path
            audio_url = f"/media/cache/{cache_key}.{actual_format}"
        self._write_metadata(
            meta_path=meta_path,
            duration_sec=provider_result.duration_sec,
            duration_source=provider_result.duration_source,
            audio_format=actual_format,
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

    def _build_cache_key(
        self,
        text: str,
        voice: str,
        speed: str,
        runtime_config: RuntimeTTSConfig | None = None,
    ) -> str:
        runtime_part = ""
        if runtime_config:
            runtime_part = (
                f"{runtime_config.provider_id or ''}\n"
                f"{runtime_config.model or ''}\n"
                f"{runtime_config.api_base_url or ''}\n"
            )
        payload = f"{voice}\n{speed}\n{runtime_part}{text}".encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def _load_or_build_metadata(
        self,
        meta_path: Path,
        text: str,
        audio_format: str,
    ) -> dict[str, str | float]:
        if meta_path.exists():
            try:
                return json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise TTSError("TTS_CACHE_METADATA_ERROR", f"Failed to read cache metadata: {exc}") from exc
        duration_sec = estimate_duration_seconds(text)
        metadata = {
            "duration_sec": duration_sec,
            "duration_source": DurationSource.ESTIMATED.value,
            "audio_format": audio_format,
        }
        self._write_metadata(meta_path, duration_sec, DurationSource.ESTIMATED, audio_format)
        return metadata

    def _write_metadata(
        self,
        meta_path: Path,
        duration_sec: float,
        duration_source: DurationSource,
        audio_format: str,
    ) -> None:
        payload = {
            "duration_sec": duration_sec,
            "duration_source": duration_source.value,
            "audio_format": audio_format,
        }
        try:
            meta_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            raise TTSError("TTS_CACHE_METADATA_ERROR", f"Failed to write cache metadata: {exc}") from exc

    def _provider_output_format(self) -> str:
        output_format = "mp3"
        provider_output = getattr(self.provider, "output_format", None)
        if callable(provider_output):
            try:
                output_format = str(provider_output()).strip() or "mp3"
            except Exception:
                output_format = "mp3"
        return self._normalize_audio_format(output_format)

    @staticmethod
    def _normalize_audio_format(audio_format: str) -> str:
        fmt = (audio_format or "").strip().lower()
        if fmt in {"wav", "wave"}:
            return "wav"
        return "mp3"


class EdgeTTSProvider:
    def output_format(self) -> str:
        return "mp3"

    async def synthesize(
        self,
        text: str,
        output_path: Path,
        voice: str,
        speed: str,
        runtime_config: RuntimeTTSConfig | None = None,
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
                audio_format="mp3",
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


class QwenTTSProvider:
    """Qwen TTS provider based on DashScope multimodal generation API."""

    def __init__(self, default_model: str | None = None) -> None:
        self.default_model = (default_model or os.getenv("AVATAR_TTS_MODEL") or "qwen3-tts-flash").strip()

    def output_format(self) -> str:
        return "wav"

    async def synthesize(
        self,
        text: str,
        output_path: Path,
        voice: str,
        speed: str,
        runtime_config: RuntimeTTSConfig | None = None,
    ) -> ProviderSynthesisResult:
        if not text or not text.strip():
            raise TTSError("TTS_EMPTY_TEXT", "Text for speech synthesis must not be empty.")

        base_url = self._resolve_base_url(runtime_config)
        api_key = self._resolve_api_key(runtime_config)
        model = self._resolve_model(runtime_config)
        qwen_voice = self._resolve_voice(voice)
        rate = self._speed_to_rate(speed)

        if not base_url:
            raise TTSError("TTS_MISSING_CONFIG", "Qwen TTS base URL is not configured.")
        if not api_key:
            raise TTSError("TTS_MISSING_CONFIG", "Qwen TTS API key is not configured.")

        endpoint = self._build_generation_endpoint(base_url)
        payload = {
            "model": model,
            "input": {
                "text": text,
                "voice": qwen_voice,
                "language_type": "Chinese",
            },
            "parameters": {
                "rate": rate,
            },
        }

        try:
            response_payload = await asyncio.to_thread(
                self._post_json,
                endpoint,
                payload,
                api_key,
            )
            audio_url = str(response_payload.get("output", {}).get("audio", {}).get("url", "")).strip()
            if not audio_url:
                raise TTSError(
                    "TTS_SYNTHESIS_ERROR",
                    f"Qwen TTS returned no audio URL: {json.dumps(response_payload, ensure_ascii=False)[:300]}",
                )

            audio_bytes = await asyncio.to_thread(self._download_binary, audio_url)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(audio_bytes)
            return ProviderSynthesisResult(
                duration_sec=estimate_duration_seconds(text),
                duration_source=DurationSource.ESTIMATED,
                audio_format="wav",
            )
        except TTSError:
            raise
        except urllib_error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="ignore")
            raise TTSError("TTS_NETWORK_ERROR", f"Qwen TTS HTTP {exc.code}: {error_body[:300]}") from exc
        except urllib_error.URLError as exc:
            raise TTSError("TTS_NETWORK_ERROR", f"Qwen TTS network failure: {exc}") from exc
        except OSError as exc:
            raise TTSError("TTS_OUTPUT_WRITE_ERROR", f"Failed to write TTS audio: {exc}") from exc
        except Exception as exc:  # pragma: no cover
            raise TTSError("TTS_SYNTHESIS_ERROR", f"Qwen TTS synthesis failed: {exc}") from exc

    def _resolve_base_url(self, runtime_config: RuntimeTTSConfig | None) -> str:
        runtime_base = (runtime_config.api_base_url or "").strip() if runtime_config else ""
        base = runtime_base or os.getenv("AVATAR_TTS_BASE_URL", "").strip() or os.getenv("OPENAI_BASE_URL", "").strip()
        if not base:
            return "https://dashscope.aliyuncs.com/api/v1"

        normalized = base.rstrip("/")
        lower = normalized.lower()
        if lower.endswith("/chat/completions"):
            normalized = normalized[: -len("/chat/completions")]
            lower = normalized.lower()
        if "dashscope.aliyuncs.com" in lower and "/compatible-mode/v1" in lower:
            normalized = re.sub(r"/compatible-mode/v1/?$", "/api/v1", normalized, flags=re.IGNORECASE)
        return normalized

    def _resolve_api_key(self, runtime_config: RuntimeTTSConfig | None) -> str:
        runtime_key = (runtime_config.api_key or "").strip() if runtime_config else ""
        return runtime_key or os.getenv("AVATAR_TTS_API_KEY", "").strip() or os.getenv("OPENAI_API_KEY", "").strip()

    def _resolve_model(self, runtime_config: RuntimeTTSConfig | None) -> str:
        if runtime_config and runtime_config.model:
            m = runtime_config.model.strip()
            if "tts" in m.lower():
                return m
        return self.default_model

    def _resolve_voice(self, voice: str) -> str:
        v = (voice or "").strip()
        if not v:
            return "Cherry"

        supported = {
            "Cherry",
            "Serena",
            "Ethan",
            "Chelsie",
            "Momo",
            "Vivian",
            "Moon",
            "Maia",
            "Kai",
            "Nofish",
            "Bella",
            "Jennifer",
            "Ryan",
            "Katerina",
            "Aiden",
        }
        if v in supported:
            return v

        lower = v.lower()
        if "yunxi" in lower or "yunjian" in lower or "male" in lower:
            return "Ethan"
        if "xiaoyi" in lower:
            return "Serena"
        if "xiaoxiao" in lower or "female" in lower:
            return "Cherry"
        return "Cherry"

    def _speed_to_rate(self, speed: str) -> int:
        m = re.fullmatch(r"([+-]?)(\d+)%", speed.strip())
        if not m:
            return 0
        sign = -1 if m.group(1) == "-" else 1
        pct = int(m.group(2)) * sign
        pct = max(-100, min(100, pct))
        # Qwen rate range: [-500, 500]
        return int(pct * 5)

    def _build_generation_endpoint(self, base_url: str) -> str:
        lower = base_url.lower()
        suffix = "/services/aigc/multimodal-generation/generation"
        if lower.endswith(suffix):
            return base_url
        return f"{base_url.rstrip('/')}{suffix}"

    def _post_json(self, url: str, payload: dict, api_key: str) -> dict:
        req = urllib_request.Request(
            url=url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Authorization": f"Bearer {api_key}",
            },
        )
        with urllib_request.urlopen(req, timeout=25) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _download_binary(self, url: str) -> bytes:
        req = urllib_request.Request(url=url, method="GET")
        with urllib_request.urlopen(req, timeout=25) as resp:
            return resp.read()
