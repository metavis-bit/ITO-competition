from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

import yaml


def load_config(path: str) -> Dict[str, Any]:
    """Load YAML config.

    - Resolves relative paths relative to the config file directory.
    - Expands environment variables in strings like ${VAR}.
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

    return _expand(cfg)


def ensure_dirs(cfg: Dict[str, Any]) -> None:
    """Create required directories."""
    store_dir = Path(cfg.get("store_dir", "./rag_store")).expanduser()
    (store_dir / "assets").mkdir(parents=True, exist_ok=True)
    (store_dir / "indexes").mkdir(parents=True, exist_ok=True)
