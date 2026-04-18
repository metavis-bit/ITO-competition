from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import logging
import re
from dataclasses import dataclass
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import urlparse

from avatar_service.core.config import Settings

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class VoiceProfile:
    voice: str
    speed: str | None
    style_prompt: str | None
    avatar_description: str | None
    source: str
    fingerprint: str


@dataclass(slots=True)
class RuntimeVoiceProfileConfig:
    api_base_url: str | None = None
    api_key: str | None = None
    model: str | None = None
    provider_id: str | None = None


class AvatarVoiceProfileService:
    """Resolve a suitable TTS voice from avatar metadata.

    Flow:
    1. If request already specifies voice, trust it.
    2. Else try multimodal image analysis (if configured).
    3. Convert profile text to a deterministic Qwen voice choice.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._cache: dict[str, VoiceProfile] = {}

    async def resolve_voice(
        self,
        session_id: str,
        explicit_voice: str | None,
        metadata: dict[str, str] | None,
        default_voice: str,
        runtime_profile: RuntimeVoiceProfileConfig | None = None,
    ) -> VoiceProfile:
        if explicit_voice and explicit_voice.strip():
            return VoiceProfile(
                voice=explicit_voice.strip(),
                speed=None,
                style_prompt=None,
                avatar_description=None,
                source="explicit",
                fingerprint=self._fingerprint_from_metadata(metadata),
            )

        safe_meta = metadata or {}
        fingerprint = self._fingerprint_from_metadata(safe_meta)
        cached_profile = self._cache.get(session_id)
        runtime_ready = self._has_runtime_profile(runtime_profile)
        if (
            cached_profile
            and cached_profile.fingerprint == fingerprint
            and (cached_profile.source in {"multimodal", "metadata_multimodal"} or not runtime_ready)
        ):
            return cached_profile

        cached_voice = (safe_meta.get("voice_profile_voice") or "").strip()
        if cached_voice:
            cached_source = (safe_meta.get("voice_profile_source") or "metadata_cache").strip()
            profile = VoiceProfile(
                voice=cached_voice,
                speed=(safe_meta.get("voice_profile_speed") or "").strip() or None,
                style_prompt=safe_meta.get("voice_profile_prompt"),
                avatar_description=safe_meta.get("voice_profile_avatar_desc"),
                source=cached_source,
                fingerprint=(safe_meta.get("voice_profile_fingerprint") or "").strip() or fingerprint,
            )
            if profile.fingerprint == fingerprint and (cached_source in {"multimodal", "metadata_multimodal"} or not runtime_ready):
                self._cache[session_id] = profile
                return profile

        avatar_ref = (safe_meta.get("avatar_image_url") or safe_meta.get("avatar_image") or "").strip()
        avatar_source = (safe_meta.get("avatar_source") or "").strip()
        persona_hint = (
            safe_meta.get("avatar_persona_hint")
            or safe_meta.get("avatar_hint")
            or safe_meta.get("avatar_label")
            or ""
        ).strip()

        description, style_prompt, voice_hint, speed_hint = await self._build_profile(
            avatar_ref,
            avatar_source,
            persona_hint,
            runtime_profile=runtime_profile,
        )
        chosen_voice = self._choose_voice(
            default_voice=default_voice,
            style_prompt=style_prompt,
            avatar_description=description,
            avatar_source=avatar_source,
            persona_hint=persona_hint,
            voice_hint=voice_hint,
        )
        chosen_speed = self._choose_speed(
            style_prompt=style_prompt,
            avatar_description=description,
            avatar_source=avatar_source,
            persona_hint=persona_hint,
            speed_hint=speed_hint,
        )
        source = "multimodal" if description else ("heuristic" if style_prompt else "default")
        profile = VoiceProfile(
            voice=chosen_voice,
            speed=chosen_speed,
            style_prompt=style_prompt,
            avatar_description=description,
            source=source,
            fingerprint=fingerprint,
        )
        self._cache[session_id] = profile
        return profile

    def metadata_patch(self, profile: VoiceProfile) -> dict[str, str]:
        patch: dict[str, str] = {
            "voice_profile_voice": profile.voice,
            "voice_profile_source": profile.source,
            "voice_profile_fingerprint": profile.fingerprint,
        }
        if profile.speed:
            patch["voice_profile_speed"] = profile.speed
        if profile.style_prompt:
            patch["voice_profile_prompt"] = profile.style_prompt[:160]
        if profile.avatar_description:
            patch["voice_profile_avatar_desc"] = profile.avatar_description[:240]
        return patch

    async def _build_profile(
        self,
        avatar_ref: str,
        avatar_source: str,
        persona_hint: str,
        runtime_profile: RuntimeVoiceProfileConfig | None = None,
    ) -> tuple[str | None, str | None, str | None, str | None]:
        description, profile_json = await self._describe_avatar_with_vlm(
            avatar_ref=avatar_ref,
            avatar_source=avatar_source,
            persona_hint=persona_hint,
            runtime_profile=runtime_profile,
        )
        if profile_json:
            style_prompt = str(profile_json.get("style_prompt") or "").strip() or self._style_prompt_from_text(
                f"{description or ''} {avatar_source} {persona_hint}".strip()
            )
            voice_hint = self._normalize_voice_hint(str(profile_json.get("voice") or ""))
            speed_hint = self._normalize_speed_hint(profile_json.get("speed_pct"))
            return description, style_prompt, voice_hint, speed_hint

        if description:
            style_prompt = self._style_prompt_from_text(f"{description} {avatar_source} {persona_hint}".strip())
            return description, style_prompt, None, None

        fallback_signals = f"{avatar_source} {persona_hint}".strip()
        if fallback_signals:
            return None, self._style_prompt_from_text(fallback_signals), None, None
        return None, None, None, None

    async def _describe_avatar_with_vlm(
        self,
        avatar_ref: str,
        avatar_source: str,
        persona_hint: str,
        runtime_profile: RuntimeVoiceProfileConfig | None = None,
    ) -> tuple[str | None, dict[str, Any] | None]:
        if not self.settings.voice_profile_enabled:
            return None, None
        if not avatar_ref:
            return None, None
        if avatar_ref.startswith("/") and not avatar_ref.startswith("//"):
            # Relative paths are usually browser assets and cannot be fetched by this service directly.
            return None, None
        if avatar_ref.startswith("data:") and len(avatar_ref) > self.settings.voice_profile_max_image_chars:
            logger.warning("Skip avatar vision profiling: data URL too large (%s chars).", len(avatar_ref))
            return None, None
        if not self._is_supported_multimodal_image_ref(avatar_ref):
            return None, None
        effective_base_url = (
            runtime_profile.api_base_url
            if runtime_profile and runtime_profile.api_base_url
            else self.settings.voice_profile_api_base_url
        )
        effective_api_key = (
            runtime_profile.api_key if runtime_profile and runtime_profile.api_key else self.settings.voice_profile_api_key
        )
        effective_model = (
            runtime_profile.model if runtime_profile and runtime_profile.model else self.settings.voice_profile_model
        )
        candidate_models = self._candidate_vision_models(effective_model, effective_base_url)

        if not effective_base_url or not effective_api_key or not candidate_models:
            return None, None

        system_prompt = (
            "你是语音导演。请根据头像图像提取声音画像，并返回严格 JSON。"
            "字段: gender(male/female/neutral), age_tone, energy(low/medium/high),"
            " warmth(low/medium/high), tone, style_prompt, voice, speed_pct。"
            "voice 只能从 [Cherry,Serena,Ethan,Ryan,Moon,Momo,Vivian,Nofish,Bella,Jennifer,Kai,Chelsie,Aiden,Maia,Katerina] 中选。"
            "speed_pct 取值[-30,30]整数。style_prompt 必须是中文短句，20字以内。"
        )
        user_text = (
            "请分析这个头像并给出匹配声音画像。"
            f"{f' 头像来源: {avatar_source}。' if avatar_source else ''}"
            f"{f' 额外提示: {persona_hint}' if persona_hint else ''}"
        )

        last_model_error: str | None = None
        for model in candidate_models:
            payload = {
                "model": model,
                "temperature": 0.2,
                "max_tokens": 260,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": user_text},
                            {"type": "image_url", "image_url": {"url": avatar_ref}},
                        ],
                    },
                ],
            }

            try:
                resp_payload = await asyncio.to_thread(
                    self._post_chat_completion,
                    payload,
                    effective_base_url,
                    effective_api_key,
                )
                raw_text = self._extract_text_from_chat_completion(resp_payload)
                if not raw_text:
                    continue
                profile_json = self._extract_json(raw_text)
                if not profile_json:
                    return raw_text.strip()[:240], None
                normalized_profile = self._normalize_multimodal_profile(profile_json)
                summary = self._summary_from_profile(normalized_profile)
                return (summary[:240] if summary else raw_text.strip()[:240]), normalized_profile
            except urllib_error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="ignore")
                last_model_error = f"HTTP {exc.code}: {body[:220]}"
                if self._is_model_fallback_error(exc.code, body):
                    logger.info("Avatar profiling fallback to next model after %s failed: %s", model, last_model_error)
                    continue
                logger.warning("Avatar multimodal profiling failed on model %s: %s", model, last_model_error)
                return None, None
            except (urllib_error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                logger.warning("Avatar multimodal profiling network/parse failure on model %s: %s", model, exc)
                return None, None
            except Exception as exc:  # pragma: no cover
                logger.warning("Avatar multimodal profiling unexpected failure on model %s: %s", model, exc)
                return None, None

        if last_model_error:
            logger.warning("Avatar multimodal profiling exhausted all candidate models: %s", last_model_error)
        return None, None

    def _post_chat_completion(self, payload: dict[str, Any], base_url: str, api_key: str) -> dict[str, Any]:
        base_url = base_url.rstrip("/")
        if base_url.lower().endswith("/chat/completions"):
            url = base_url
        else:
            url = f"{base_url}/chat/completions"
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib_request.Request(
            url=url,
            data=data,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
        )
        with urllib_request.urlopen(req, timeout=self.settings.voice_profile_timeout_sec) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _extract_text_from_chat_completion(self, payload: dict[str, Any]) -> str | None:
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            return None
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        if not isinstance(message, dict):
            return None
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str):
                        parts.append(text)
            return "\n".join(parts).strip() if parts else None
        return None

    def _extract_json(self, raw_text: str) -> dict[str, Any] | None:
        text = raw_text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        try:
            payload = json.loads(text)
            if isinstance(payload, dict):
                return payload
        except json.JSONDecodeError:
            pass

        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            return None
        try:
            payload = json.loads(match.group(0))
            if isinstance(payload, dict):
                return payload
        except json.JSONDecodeError:
            return None
        return None

    async def generate_project_intro_script(
        self,
        *,
        title: str,
        summary: str,
        highlights: list[str],
        metadata: dict[str, str] | None,
        runtime_profile: RuntimeVoiceProfileConfig | None = None,
    ) -> dict[str, Any] | None:
        base_url, api_key, model = self._resolve_runtime_llm(runtime_profile)
        if not base_url or not api_key or not model:
            return None

        safe_meta = metadata or {}
        avatar_ref = (safe_meta.get("avatar_image_url") or safe_meta.get("avatar_image") or "").strip()
        persona_hint = (
            safe_meta.get("avatar_persona_hint")
            or safe_meta.get("avatar_hint")
            or safe_meta.get("avatar_label")
            or ""
        ).strip()
        highlights_text = "；".join(item.strip() for item in highlights if item and item.strip()) or "无"

        user_text = (
            "请为数字人课堂生成开场讲解文案，严格返回 JSON。"
            f"\n课堂标题: {title}"
            f"\n已有摘要: {summary}"
            f"\n已有重点: {highlights_text}"
            f"\n角色提示: {persona_hint or '无'}"
            "\n要求：summary 要自然口语、80-160字；highlights 返回 2-4 条中文短句。"
        )

        payload = {
            "model": model,
            "temperature": 0.3,
            "max_tokens": 280,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是课堂开场文案导演。输出 JSON，字段：summary(string)、highlights(array<string>)。"
                        "不要输出 markdown，不要额外解释。"
                    ),
                },
                {
                    "role": "user",
                    "content": self._build_multimodal_user_content(user_text, avatar_ref),
                },
            ],
        }

        try:
            resp_payload = await asyncio.to_thread(
                self._post_chat_completion,
                payload,
                base_url,
                api_key,
            )
            raw_text = self._extract_text_from_chat_completion(resp_payload)
            if not raw_text:
                return None
            intro_json = self._extract_json(raw_text)
            if intro_json:
                next_summary = str(intro_json.get("summary") or "").strip()
                raw_highlights = intro_json.get("highlights")
                next_highlights: list[str] = []
                if isinstance(raw_highlights, list):
                    for item in raw_highlights:
                        if isinstance(item, str):
                            cleaned = item.strip()
                            if cleaned:
                                next_highlights.append(cleaned[:40])
                if not next_summary:
                    return None
                if not next_highlights and highlights:
                    next_highlights = [item.strip()[:40] for item in highlights if item and item.strip()][:3]
                return {
                    "summary": next_summary[:220],
                    "highlights": next_highlights[:4],
                }
            return {
                "summary": raw_text.strip()[:220],
                "highlights": [item.strip()[:40] for item in highlights if item and item.strip()][:3],
            }
        except (urllib_error.HTTPError, urllib_error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            logger.warning("Project intro multimodal generation failed: %s", exc)
            return None
        except Exception as exc:  # pragma: no cover
            logger.warning("Project intro multimodal generation unexpected failure: %s", exc)
            return None

    async def generate_slide_explain_script(
        self,
        *,
        slide_no: int,
        level: str,
        title: str | None,
        bullets: list[str],
        speaker_notes: str | None,
        summary: str | None,
        metadata: dict[str, str] | None,
        runtime_profile: RuntimeVoiceProfileConfig | None = None,
    ) -> dict[str, str] | None:
        base_url, api_key, model = self._resolve_runtime_llm(runtime_profile)
        if not base_url or not api_key or not model:
            return None

        safe_meta = metadata or {}
        avatar_ref = (safe_meta.get("avatar_image_url") or safe_meta.get("avatar_image") or "").strip()
        persona_hint = (
            safe_meta.get("avatar_persona_hint")
            or safe_meta.get("avatar_hint")
            or safe_meta.get("avatar_label")
            or ""
        ).strip()
        bullets_text = "；".join(item.strip() for item in bullets if item and item.strip()) or "无"

        level = (level or "full").strip().lower()
        if level not in {"full", "summary"}:
            level = "full"

        user_text = (
            "请生成数字人课堂讲解文案，严格返回 JSON。"
            f"\nslide_no: {slide_no}"
            f"\nlevel: {level}"
            f"\n标题: {title or '无'}"
            f"\n要点: {bullets_text}"
            f"\n已有讲稿: {(speaker_notes or '').strip() or '无'}"
            f"\n已有摘要: {(summary or '').strip() or '无'}"
            f"\n角色提示: {persona_hint or '无'}"
            "\n要求：内容专业、口语化、适合课堂直接播报。"
        )

        if level == "summary":
            system_prompt = (
                "你是课堂讲解摘要助手。输出 JSON，字段：summary(string)。"
                "summary 控制在 70-140 字。不要输出 markdown。"
            )
            max_tokens = 180
        else:
            system_prompt = (
                "你是课堂讲解脚本助手。输出 JSON，字段：speaker_notes(string)、summary(string)。"
                "speaker_notes 控制在 120-260 字，summary 控制在 60-120 字。不要输出 markdown。"
            )
            max_tokens = 360

        payload = {
            "model": model,
            "temperature": 0.3,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": self._build_multimodal_user_content(user_text, avatar_ref),
                },
            ],
        }

        try:
            resp_payload = await asyncio.to_thread(
                self._post_chat_completion,
                payload,
                base_url,
                api_key,
            )
            raw_text = self._extract_text_from_chat_completion(resp_payload)
            if not raw_text:
                return None

            explain_json = self._extract_json(raw_text)
            if explain_json:
                result: dict[str, str] = {}
                next_summary = str(explain_json.get("summary") or "").strip()
                if next_summary:
                    result["summary"] = next_summary[:220]
                next_notes = str(
                    explain_json.get("speaker_notes")
                    or explain_json.get("notes")
                    or explain_json.get("explain")
                    or ""
                ).strip()
                if next_notes:
                    result["speaker_notes"] = next_notes[:520]
                if result:
                    return result
                return None

            fallback = raw_text.strip()
            if not fallback:
                return None
            if level == "summary":
                return {"summary": fallback[:220]}
            return {"speaker_notes": fallback[:520]}
        except (urllib_error.HTTPError, urllib_error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            logger.warning("Slide multimodal generation failed: %s", exc)
            return None
        except Exception as exc:  # pragma: no cover
            logger.warning("Slide multimodal generation unexpected failure: %s", exc)
            return None

    def _resolve_runtime_llm(
        self,
        runtime_profile: RuntimeVoiceProfileConfig | None,
    ) -> tuple[str | None, str | None, str | None]:
        effective_base_url = (
            runtime_profile.api_base_url
            if runtime_profile and runtime_profile.api_base_url
            else self.settings.voice_profile_api_base_url
        )
        effective_api_key = (
            runtime_profile.api_key if runtime_profile and runtime_profile.api_key else self.settings.voice_profile_api_key
        )
        effective_model = (
            runtime_profile.model if runtime_profile and runtime_profile.model else self.settings.voice_profile_model
        )
        return effective_base_url, effective_api_key, effective_model

    def _build_multimodal_user_content(self, text: str, avatar_ref: str) -> str | list[dict[str, Any]]:
        if not avatar_ref:
            return text
        if avatar_ref.startswith("/") and not avatar_ref.startswith("//"):
            return text
        if avatar_ref.startswith("data:") and len(avatar_ref) > self.settings.voice_profile_max_image_chars:
            return text
        if not self._is_supported_multimodal_image_ref(avatar_ref):
            return text
        return [
            {"type": "text", "text": text},
            {"type": "image_url", "image_url": {"url": avatar_ref}},
        ]

    def _is_supported_multimodal_image_ref(self, avatar_ref: str) -> bool:
        candidate = (avatar_ref or "").strip()
        if not candidate:
            return False
        if candidate.startswith("data:"):
            return True

        parsed = urlparse(candidate)
        if parsed.scheme not in {"http", "https"}:
            return False

        hostname = (parsed.hostname or "").strip()
        if not hostname:
            return False
        lowered = hostname.lower()
        if lowered in {"localhost"} or lowered.endswith(".local"):
            return False

        try:
            address = ipaddress.ip_address(lowered)
        except ValueError:
            return True

        return not (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_reserved
            or address.is_unspecified
        )

    def _fingerprint_from_metadata(self, metadata: dict[str, str] | None) -> str:
        safe_meta = metadata or {}
        avatar_ref = (safe_meta.get("avatar_image_url") or safe_meta.get("avatar_image") or "").strip()
        avatar_source = (safe_meta.get("avatar_source") or "").strip()
        persona_hint = (
            safe_meta.get("avatar_persona_hint")
            or safe_meta.get("avatar_hint")
            or safe_meta.get("avatar_label")
            or ""
        ).strip()
        payload = f"{avatar_ref}\n{avatar_source}\n{persona_hint}".encode("utf-8")
        return hashlib.sha256(payload).hexdigest()[:20]

    def _has_runtime_profile(self, runtime_profile: RuntimeVoiceProfileConfig | None) -> bool:
        if runtime_profile and runtime_profile.api_key and runtime_profile.api_base_url:
            return True
        return bool(self.settings.voice_profile_api_key and self.settings.voice_profile_api_base_url)

    def _candidate_vision_models(self, preferred_model: str | None, base_url: str | None) -> list[str]:
        candidates: list[str] = []

        def add(model: str | None) -> None:
            if not model:
                return
            cleaned = model.strip()
            if cleaned and cleaned not in candidates:
                candidates.append(cleaned)

        add(preferred_model)
        low_base = (base_url or "").lower()

        # DashScope users often configure a text-only model globally; fallback to VL models for avatar parsing.
        if "dashscope.aliyuncs.com" in low_base:
            if not preferred_model or not re.search(r"(vl|vision|omni)", preferred_model, re.IGNORECASE):
                add("qwen-vl-max-latest")
                add("qwen-vl-plus-latest")
                add("qwen-vl-max")
                add("qwen-vl-plus")
                add("qwen2.5-vl-72b-instruct")
                add("qwen2.5-vl-7b-instruct")
        else:
            # Generic OpenAI-compatible fallback.
            if not preferred_model:
                add("gpt-4o-mini")
                add("gpt-4o")

        return candidates

    def _is_model_fallback_error(self, status_code: int, error_body: str) -> bool:
        if status_code not in {400, 404, 422}:
            return False
        body = (error_body or "").lower()
        hints = (
            "model",
            "unsupported",
            "not found",
            "not support",
            "vision",
            "image",
            "multimodal",
        )
        return any(token in body for token in hints)

    def _normalize_multimodal_profile(self, profile: dict[str, Any]) -> dict[str, Any]:
        normalized: dict[str, Any] = {}
        for key in ("gender", "age_tone", "energy", "warmth", "tone", "style_prompt"):
            value = profile.get(key)
            if value is None:
                continue
            if isinstance(value, str):
                cleaned = value.strip()
                if cleaned:
                    normalized[key] = cleaned

        voice_hint = self._normalize_voice_hint(str(profile.get("voice") or ""))
        if voice_hint:
            normalized["voice"] = voice_hint

        speed_hint = self._normalize_speed_hint(profile.get("speed_pct"))
        if speed_hint:
            normalized["speed_pct"] = speed_hint
        return normalized

    def _summary_from_profile(self, profile: dict[str, Any]) -> str:
        parts: list[str] = []
        for key in ("gender", "age_tone", "energy", "warmth", "tone", "style_prompt", "voice"):
            value = profile.get(key)
            if isinstance(value, str) and value.strip():
                parts.append(value.strip())
        speed = profile.get("speed_pct")
        if isinstance(speed, str) and speed:
            parts.append(f"speed{speed}")
        return " ".join(parts)

    def _normalize_voice_hint(self, voice: str) -> str | None:
        v = (voice or "").strip()
        if not v:
            return None
        supported = {
            "Cherry",
            "Serena",
            "Ethan",
            "Ryan",
            "Moon",
            "Momo",
            "Vivian",
            "Nofish",
            "Bella",
            "Jennifer",
            "Kai",
            "Chelsie",
            "Aiden",
            "Maia",
            "Katerina",
        }
        return v if v in supported else None

    def _normalize_speed_hint(self, raw_value: Any) -> str | None:
        if raw_value is None:
            return None
        try:
            numeric = int(float(raw_value))
        except (TypeError, ValueError):
            return None
        bounded = max(-30, min(30, numeric))
        if bounded == 0:
            return "+0%"
        return f"{bounded:+d}%"

    def _style_prompt_from_text(self, text: str) -> str | None:
        if not text:
            return None
        lower = text.lower()

        traits: list[str] = []
        if any(k in lower for k in ["cartoon", "卡通", "q版", "派大星", "patrick", "动漫"]):
            traits.append("语气活泼有角色感")
        if any(k in lower for k in ["professional", "老师", "teacher", "稳重", "严谨"]):
            traits.append("表达清晰稳重")
        if any(k in lower for k in ["warm", "温暖", "友好", "friendly", "亲和"]):
            traits.append("声音温暖自然")
        if any(k in lower for k in ["energetic", "高能", "激情", "excited", "兴奋", "元气"]):
            traits.append("节奏偏快有感染力")
        if any(k in lower for k in ["calm", "冷静", "沉稳", "serious", "严肃"]):
            traits.append("语速平稳不过分夸张")

        if not traits:
            traits = ["语气自然亲和", "发音清晰有讲解感"]
        return "；".join(traits[:3])

    def _choose_voice(
        self,
        default_voice: str,
        style_prompt: str | None,
        avatar_description: str | None,
        avatar_source: str,
        persona_hint: str,
        voice_hint: str | None = None,
    ) -> str:
        if voice_hint:
            return voice_hint

        signals = " ".join(
            part for part in [style_prompt or "", avatar_description or "", avatar_source, persona_hint] if part
        ).lower()

        male_tokens = ("male", "男", "先生", "叔", "硬朗", "低沉", "派大星", "patrick", "starfish")
        female_tokens = ("female", "女", "女士", "温柔", "甜美", "小姐姐", "少女")
        energetic_tokens = ("活泼", "energetic", "高能", "元气", "俏皮", "可爱", "搞怪", "卡通", "动漫")
        calm_tokens = ("calm", "沉稳", "严谨", "稳重", "冷静", "serious", "理性", "专业")

        male_score = sum(1 for token in male_tokens if token in signals)
        female_score = sum(1 for token in female_tokens if token in signals)
        energetic_score = sum(1 for token in energetic_tokens if token in signals)
        calm_score = sum(1 for token in calm_tokens if token in signals)

        if male_score > female_score:
            return "Ryan" if energetic_score >= calm_score else "Ethan"
        if female_score > male_score:
            return "Cherry" if energetic_score >= calm_score else "Serena"
        if energetic_score > calm_score:
            return "Cherry"
        if calm_score > energetic_score:
            return "Serena"
        return default_voice

    def _choose_speed(
        self,
        style_prompt: str | None,
        avatar_description: str | None,
        avatar_source: str,
        persona_hint: str,
        speed_hint: str | None = None,
    ) -> str | None:
        if speed_hint:
            return speed_hint
        signals = " ".join(
            part for part in [style_prompt or "", avatar_description or "", avatar_source, persona_hint] if part
        ).lower()
        fast_tokens = ("活泼", "元气", "energetic", "兴奋", "卡通", "俏皮", "可爱")
        slow_tokens = ("沉稳", "calm", "冷静", "严谨", "serious", "低沉")
        fast_score = sum(1 for token in fast_tokens if token in signals)
        slow_score = sum(1 for token in slow_tokens if token in signals)
        if fast_score > slow_score:
            return "+8%"
        if slow_score > fast_score:
            return "-6%"
        return "+0%"
