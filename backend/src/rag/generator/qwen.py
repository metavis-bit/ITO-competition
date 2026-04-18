from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class GeneratorConfig:
    mode: str = "local"  # local | api

    # OpenAI-compatible API
    api_model: str = "gpt-4o-mini"
    api_base_url_env: str = "OPENAI_BASE_URL"
    api_key_env: str = "OPENAI_API_KEY"
    timeout_sec: float = 120.0

    # Local transformers model (e.g., Qwen2.5-1.5B-Instruct)
    local_model_path: str = "./models/Qwen2.5-1.5B-Instruct"
    device: str = "cpu"  # cpu | cuda
    max_new_tokens: int = 512
    temperature: float = 0.2


class QwenGenerator:
    """LLM generator wrapper.

    Supports:
    - local transformers generation (default, offline)
    - OpenAI-compatible API (optional)
    """

    def __init__(self, cfg: GeneratorConfig):
        self.cfg = cfg
        self._tok = None
        self._model = None

    def _ensure_local(self):
        if self._tok is not None and self._model is not None:
            return

        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        dtype = torch.float16 if self.cfg.device == "cuda" else torch.float32
        tok = AutoTokenizer.from_pretrained(self.cfg.local_model_path, trust_remote_code=True)

        if self.cfg.device == "cuda":
            model = AutoModelForCausalLM.from_pretrained(
                self.cfg.local_model_path,
                torch_dtype=dtype,
                device_map="auto",
                trust_remote_code=True,
            )
        else:
            model = AutoModelForCausalLM.from_pretrained(
                self.cfg.local_model_path,
                torch_dtype=dtype,
                trust_remote_code=True,
            )
            model.to("cpu")

        self._tok = tok
        self._model = model

    def _call_api(self, prompt: str) -> str:
        from openai import OpenAI

        base_url = os.environ.get(self.cfg.api_base_url_env) or None
        api_key = os.environ.get(self.cfg.api_key_env) or ""

        if not api_key.strip():
            return "(LLM disabled: missing env " + self.cfg.api_key_env + ")"

        client = OpenAI(api_key=api_key, base_url=base_url, timeout=float(self.cfg.timeout_sec))
        resp = client.chat.completions.create(
            model=self.cfg.api_model,
            messages=[
                {"role": "system", "content": "你是严谨的教学助手。"},
                {"role": "user", "content": prompt},
            ],
            temperature=float(self.cfg.temperature),
        )
        return resp.choices[0].message.content.strip()

    def _call_local(self, prompt: str) -> str:
        import torch

        self._ensure_local()
        assert self._tok is not None and self._model is not None

        tok = self._tok
        model = self._model

        inputs = tok(prompt, return_tensors="pt")
        if self.cfg.device == "cuda":
            inputs = {k: v.to("cuda") for k, v in inputs.items()}
        else:
            inputs = {k: v.to("cpu") for k, v in inputs.items()}

        do_sample = float(self.cfg.temperature) > 0
        with torch.no_grad():
            out = model.generate(
                **inputs,
                max_new_tokens=int(self.cfg.max_new_tokens),
                do_sample=do_sample,
                temperature=float(self.cfg.temperature) if do_sample else None,
            )

        gen = out[0][inputs["input_ids"].shape[1] :]
        return tok.decode(gen, skip_special_tokens=True).strip()

    def generate(self, prompt: str) -> str:
        mode = (self.cfg.mode or "local").lower()
        if mode == "api":
            return self._call_api(prompt)
        return self._call_local(prompt)
