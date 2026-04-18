from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass
class VLMResult:
    """Vision-Language Model (VLM) result.

    We keep it intentionally small and serialization-friendly.
    """

    text: str
    engine: str
    prompt: str


def _img_to_data_url(image_path: str) -> str:
    p = Path(image_path)
    suffix = p.suffix.lower().lstrip(".")
    mime = "image/png" if suffix in ["png"] else "image/jpeg" if suffix in ["jpg", "jpeg"] else "image/webp" if suffix in ["webp"] else "image/png"
    b64 = base64.b64encode(p.read_bytes()).decode("utf-8")
    return f"data:{mime};base64,{b64}"


def describe_image(image_path: str, prompt: str, vlm_cfg: Dict[str, Any]) -> Optional[VLMResult]:
    """Describe an image using a VLM.

    This function is **optional** and must be fail-soft: if the environment
    has no VLM backend configured, it returns None instead of crashing.

    Supported backends:
      - OpenAI-compatible API (recommended for most teams): mode=api
      - local transformers backend: mode=local (best-effort)

    NOTE: We keep local backend minimal to avoid pinning to a single VLM.
    In practice, many teams deploy Qwen-VL/Qwen2-VL via vLLM and use mode=api.
    """

    enabled = bool(vlm_cfg.get("enabled", False))
    if not enabled:
        return None

    mode = str(vlm_cfg.get("mode", "api")).lower()
    if mode in ["off", "disabled", "none"]:
        return None

    # ---------------- API backend (OpenAI-compatible) ----------------
    if mode in ["api", "auto"]:
        try:
            from openai import OpenAI  # type: ignore
        except Exception:
            if mode == "api":
                return None
        else:
            api_model = str(vlm_cfg.get("api_model", "gpt-4o-mini"))
            base_env = str(vlm_cfg.get("api_base_url_env", "OPENAI_BASE_URL"))
            key_env = str(vlm_cfg.get("api_key_env", "OPENAI_API_KEY"))
            timeout_sec = float(vlm_cfg.get("timeout_sec", 120))
            max_new_tokens = int(vlm_cfg.get("max_new_tokens", 256))
            temperature = float(vlm_cfg.get("temperature", 0.2))

            base_url = os.getenv(base_env) or None
            api_key = os.getenv(key_env) or ""
            if not api_key and mode != "auto":
                # explicitly API but no key
                return None

            client = OpenAI(base_url=base_url, api_key=api_key, timeout=timeout_sec)
            img_url = _img_to_data_url(image_path)
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": img_url}},
                    ],
                }
            ]
            try:
                resp = client.chat.completions.create(
                    model=api_model,
                    messages=messages,
                    max_tokens=max_new_tokens,
                    temperature=temperature,
                )
                text = (resp.choices[0].message.content or "").strip()
                if not text:
                    return None
                return VLMResult(text=text, engine=f"api:{api_model}", prompt=prompt)
            except Exception:
                if mode == "api":
                    return None

    # ---------------- local backend (best-effort) ----------------
    if mode in ["local", "auto"]:
        # We keep this minimal and best-effort because different VLMs
        # may require different processors / model classes.
        # Recommended: deploy your VLM with an OpenAI-compatible server and use mode=api.
        try:
            from transformers import AutoProcessor, AutoModelForVision2Seq  # type: ignore
            import torch  # type: ignore
        except Exception:
            return None

        model_path = str(vlm_cfg.get("local_model_path", ""))
        if not model_path:
            return None
        device = str(vlm_cfg.get("device", "cpu"))

        try:
            processor = AutoProcessor.from_pretrained(model_path, trust_remote_code=True)
            model = AutoModelForVision2Seq.from_pretrained(model_path, trust_remote_code=True)
            if device != "cpu":
                model = model.to(device)
            model.eval()

            # NOTE: model-specific; may not work for all VLMs.
            inputs = processor(text=prompt, images=Path(image_path).read_bytes(), return_tensors="pt")
            if device != "cpu":
                inputs = {k: v.to(device) for k, v in inputs.items()}
            out_ids = model.generate(**inputs, max_new_tokens=int(vlm_cfg.get("max_new_tokens", 256)))
            text = processor.batch_decode(out_ids, skip_special_tokens=True)[0].strip()
            if not text:
                return None
            return VLMResult(text=text, engine=f"local:{Path(model_path).name}", prompt=prompt)
        except Exception:
            return None

    return None


def save_vlm_result(result: VLMResult, out_path: str) -> None:
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "engine": result.engine,
        "prompt": result.prompt,
        "text": result.text,
    }
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
