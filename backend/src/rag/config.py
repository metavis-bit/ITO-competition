from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

import yaml


_DEVICE_SECTIONS = (
    ("embedding_model",),
    ("reranker",),
    ("generator",),
    ("vlm",),
    ("parsing", "audio"),
    ("parsing", "video"),
)


def _resolve_device(value: str) -> str:
    """Resolve `device: auto` to cuda/cpu based on runtime availability."""
    if not isinstance(value, str) or value.strip().lower() != "auto":
        return value
    try:
        import torch  # type: ignore

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def _resolve_compute_type(value: str, device: str) -> str:
    """Resolve `compute_type: auto` for faster-whisper based on resolved device."""
    if not isinstance(value, str) or value.strip().lower() != "auto":
        return value
    return "float16" if device == "cuda" else "int8"


def _apply_device_auto(cfg: Dict[str, Any]) -> None:
    """Walk known device sections and replace `auto` with a concrete device."""
    for path in _DEVICE_SECTIONS:
        node: Any = cfg
        for key in path:
            if not isinstance(node, dict) or key not in node:
                node = None
                break
            node = node[key]
        if not isinstance(node, dict):
            continue
        if "device" in node:
            resolved = _resolve_device(node["device"])
            node["device"] = resolved
            if "compute_type" in node:
                node["compute_type"] = _resolve_compute_type(node["compute_type"], resolved)
            # use_fp16 is only safe on CUDA; force False on CPU to avoid crashes.
            if resolved != "cuda" and node.get("use_fp16") is True:
                node["use_fp16"] = False


def load_config(path: str) -> Dict[str, Any]:
    """Load YAML config.

    - Resolves relative paths relative to the config file directory.
    - Expands environment variables in strings like ${VAR}.
    - Resolves `device: auto` to cuda or cpu based on torch availability.
    """
    cfg_path = Path(path).expanduser().resolve()
    base_dir = cfg_path.parent

    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}

    def _expand(v):
        if isinstance(v, str):
            v = os.path.expandvars(v)
            if not os.path.isabs(v) and ("/" in v or v.startswith(".")):
                # treat as relative path
                return str((base_dir / v).resolve())
            return v
        if isinstance(v, dict):
            return {k: _expand(val) for k, val in v.items()}
        if isinstance(v, list):
            return [_expand(x) for x in v]
        return v

    cfg = _expand(cfg)
    _apply_device_auto(cfg)
    return cfg


def ensure_dirs(cfg: Dict[str, Any]) -> None:
    """Create required directories."""
    store_dir = Path(cfg.get("store_dir", "./rag_store")).expanduser()
    (store_dir / "assets").mkdir(parents=True, exist_ok=True)
    (store_dir / "indexes").mkdir(parents=True, exist_ok=True)
