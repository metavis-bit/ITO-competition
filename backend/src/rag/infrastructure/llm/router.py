"""
Unified LLM router — single point of control for all model calls.

Replaces scattered QwenGenerator and raw OpenAI calls with:
  - Per-task model selection (intent → qwen-max, outline → qwen-plus, etc.)
  - Retry with exponential backoff on transient failures
  - JSON extraction and schema validation
  - Content-hash based response caching (TTL 300s)
  - Structured error taxonomy
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("llm_router")


class ModelTimeoutError(Exception):
    pass


class SchemaViolationError(Exception):
    pass


class ProviderUnavailableError(Exception):
    pass


class LLMRouter:
    """
    Central LLM gateway. All LLM calls in the system go through here.

    Usage:
        router = LLMRouter(config)
        answer = router.generate(prompt, task="outline", expect_json=True)
    """

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self._cache: Dict[str, tuple] = {}  # hash → (response, timestamp)
        self._cache_ttl = config.get("cache_ttl", 300)
        self._client = None

    @property
    def client(self):
        """Lazy-init OpenAI client (compatible with DashScope / any OpenAI-compatible API)."""
        if self._client is None:
            from openai import OpenAI

            api_key_env = self.config.get("api_key_env", "OPENAI_API_KEY")
            base_url_env = self.config.get("api_base_url_env", "OPENAI_BASE_URL")
            api_key = os.environ.get(api_key_env, "")
            base_url = os.environ.get(base_url_env) or self.config.get("api_base_url")

            self._client = OpenAI(
                api_key=api_key,
                base_url=base_url,
                timeout=float(self.config.get("timeout_sec", 120)),
            )
        return self._client

    def generate(
        self,
        prompt: str,
        *,
        task: str = "default",
        system_prompt: str = "你是严谨的教学助手。",
        messages: Optional[List[Dict[str, str]]] = None,
        max_tokens: int = 512,
        temperature: float = 0.2,
        expect_json: bool = False,
        json_schema: Optional[Dict[str, Any]] = None,
        timeout_sec: Optional[int] = None,
        max_retries: int = 2,
        cache: bool = True,
    ) -> str:
        """
        Central generation method.

        Args:
            prompt: The user prompt (ignored if messages is provided).
            task: Task type for model selection (intent|outline|game|refinement|vlm|default).
            system_prompt: System message.
            messages: Full message list (overrides prompt/system_prompt if provided).
            max_tokens: Max tokens in response.
            temperature: Sampling temperature.
            expect_json: If True, extracts and validates JSON from response.
            json_schema: If provided, validates required keys exist in parsed JSON.
            timeout_sec: Override timeout for this call.
            max_retries: Max retries on transient failures.
            cache: Whether to use response cache.

        Returns:
            Generated text (or extracted JSON string if expect_json=True).

        Raises:
            SchemaViolationError: If JSON validation fails.
            ProviderUnavailableError: If all retries exhausted.
            ModelTimeoutError: If call times out.
        """
        cache_key = hashlib.sha256(
            f"{task}:{prompt}:{max_tokens}:{temperature}".encode()
        ).hexdigest()

        if cache and cache_key in self._cache:
            resp, ts = self._cache[cache_key]
            if time.time() - ts < self._cache_ttl:
                logger.debug("Cache hit for task=%s", task)
                return resp

        model = self._select_model(task)
        actual_timeout = timeout_sec or int(self.config.get("timeout_sec", 120))

        if messages is None:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ]

        for attempt in range(max_retries + 1):
            try:
                raw = self._call_provider(model, messages, max_tokens, temperature, actual_timeout)

                if expect_json:
                    raw = self._extract_json(raw)
                    if json_schema:
                        raw = self._validate_schema(raw, json_schema)

                if cache:
                    self._cache[cache_key] = (raw, time.time())
                return raw

            except SchemaViolationError:
                raise  # don't retry on schema errors
            except (ModelTimeoutError, ProviderUnavailableError) as e:
                if attempt == max_retries:
                    raise
                wait = 2 ** attempt
                logger.warning("Retry %d/%d for task=%s: %s (wait %ds)", attempt + 1, max_retries, task, e, wait)
                time.sleep(wait)

        raise ProviderUnavailableError("Exhausted retries")

    def generate_stream(
        self,
        prompt: str,
        *,
        task: str = "default",
        system_prompt: str = "你是严谨的教学助手。",
        messages: Optional[List[Dict[str, str]]] = None,
        max_tokens: int = 2048,
        temperature: float = 0.2,
    ):
        """
        Streaming generation — yields text chunks.

        Used by SSE outline streaming endpoint.
        """
        model = self._select_model(task)

        if messages is None:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ]

        try:
            stream = self.client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
            )
            for chunk in stream:
                delta = chunk.choices[0].delta
                if delta and delta.content:
                    yield delta.content
        except Exception as e:
            logger.error("Stream generation failed for task=%s: %s", task, e)
            raise ProviderUnavailableError(f"Stream failed: {e}") from e

    def _select_model(self, task: str) -> str:
        """Select model based on task type."""
        models = self.config.get("models", {})
        if isinstance(models, dict) and task in models:
            return models[task]

        # Fallback to single api_model config
        default = self.config.get("api_model", "qwen-plus-latest")
        mapping = {
            "intent": self.config.get("intent_model", default),
            "outline": self.config.get("outline_model", default),
            "game": self.config.get("game_model", default),
            "refinement": self.config.get("refine_model", default),
            "vlm": self.config.get("vlm_model", "qwen2.5-vl-7b-instruct"),
            "default": default,
        }
        return mapping.get(task, default)

    def _call_provider(
        self,
        model: str,
        messages: List[Dict[str, str]],
        max_tokens: int,
        temperature: float,
        timeout_sec: int,
    ) -> str:
        """Make the actual API call."""
        try:
            resp = self.client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            content = resp.choices[0].message.content
            return (content or "").strip()
        except Exception as e:
            err_str = str(e).lower()
            if "timeout" in err_str or "timed out" in err_str:
                raise ModelTimeoutError(f"Model {model} timed out: {e}") from e
            raise ProviderUnavailableError(f"Provider error for {model}: {e}") from e

    @staticmethod
    def _extract_json(raw: str) -> str:
        """Strip markdown fences and extract the first JSON block.

        Handles:
        - ```json ... ``` fences (single or multiple)
        - Truncated JSON (auto-closes open brackets/braces)
        - Trailing commas
        """
        text = raw.strip()

        # Strip all ```json / ``` fences robustly
        text = re.sub(r"```(?:json|JSON)?\s*\n?", "", text)
        text = text.strip()

        # Try parsing as-is first
        try:
            json.loads(text)
            return text
        except json.JSONDecodeError:
            pass

        # Find first { ... } or [ ... ] block
        for pattern in [r"\{[\s\S]*\}", r"\[[\s\S]*\]"]:
            match = re.search(pattern, text)
            if match:
                candidate = match.group(0)
                # Remove trailing commas before } or ]
                candidate = re.sub(r",\s*([}\]])", r"\1", candidate)
                try:
                    json.loads(candidate)
                    return candidate
                except json.JSONDecodeError:
                    # Try to repair truncated JSON by closing open brackets
                    repaired = LLMRouter._repair_truncated_json(candidate)
                    if repaired:
                        return repaired
                    continue

        # Last resort: find the first { or [ and try to repair from there
        for start_char in ["{", "["]:
            idx = text.find(start_char)
            if idx >= 0:
                candidate = text[idx:]
                repaired = LLMRouter._repair_truncated_json(candidate)
                if repaired:
                    return repaired

        raise SchemaViolationError(f"No valid JSON found in LLM output (first 200 chars): {raw[:200]}")

    @staticmethod
    def _repair_truncated_json(text: str) -> Optional[str]:
        """Attempt to repair truncated JSON by closing unclosed brackets/braces.

        Handles cases where LLM output was cut off mid-JSON.
        Returns the repaired JSON string, or None if repair fails.
        """
        # Remove trailing commas and incomplete key-value pairs
        text = re.sub(r",\s*([}\]])", r"\1", text)
        # Remove trailing incomplete string (e.g., `"key": "incom`)
        text = re.sub(r',\s*"[^"]*"?\s*:\s*"[^"]*$', "", text)
        # Remove trailing comma after last complete element
        text = re.sub(r",\s*$", "", text)

        # Count unclosed brackets
        open_braces = text.count("{") - text.count("}")
        open_brackets = text.count("[") - text.count("]")

        if open_braces < 0 or open_brackets < 0:
            return None  # More closes than opens — malformed

        # Close unclosed structures (inner brackets first, then braces)
        closing = "]" * open_brackets + "}" * open_braces

        candidate = text + closing
        # Clean up trailing commas one more time after repair
        candidate = re.sub(r",\s*([}\]])", r"\1", candidate)

        try:
            json.loads(candidate)
            logger.warning("Repaired truncated JSON (closed %d braces, %d brackets)",
                           open_braces, open_brackets)
            return candidate
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _validate_schema(json_str: str, schema: Dict[str, Any]) -> str:
        """Validate that required keys exist in parsed JSON.

        If the LLM returns a bare list and a required key is expected,
        auto-wrap it (e.g. list → {"slides": list}).
        Returns the (possibly rewritten) json_str.
        """
        parsed = json.loads(json_str)
        required = schema.get("required_keys", [])
        if isinstance(parsed, list) and required:
            # Auto-wrap: use the first required key as wrapper
            wrapped = {required[0]: parsed}
            return json.dumps(wrapped, ensure_ascii=False)
        if isinstance(parsed, dict):
            for key in required:
                if key not in parsed:
                    raise SchemaViolationError(f"Missing required key: {key}")
        return json_str

    def clear_cache(self) -> int:
        """Clear expired cache entries. Returns number of entries removed."""
        now = time.time()
        expired = [k for k, (_, ts) in self._cache.items() if now - ts >= self._cache_ttl]
        for k in expired:
            del self._cache[k]
        return len(expired)
