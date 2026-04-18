"""Download required HuggingFace models on first startup.

Desktop distributions ship without bundled model weights to keep the installer
small. When the backend boots we check that the paths referenced by `config.yaml`
exist, and download them from a HuggingFace mirror if they are missing.

Progress is written as JSON lines to `rag_store/model_download.status` so the
Electron shell can render a progress bar before the user sees the UI.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Dict, Iterable, Optional

logger = logging.getLogger(__name__)


DEFAULT_REPO_MAP: Dict[str, str] = {
    "bge-m3": "BAAI/bge-m3",
    "bge-reranker-large": "BAAI/bge-reranker-large",
}


def _status_path() -> Path:
    return Path("rag_store") / "model_download.status"


def _write_status(stage: str, **extra) -> None:
    path = _status_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"stage": stage, "ts": time.time(), **extra}
    try:
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except Exception:  # pragma: no cover - status is best-effort
        pass


def _is_model_complete(local_dir: Path) -> bool:
    """A BGE model dir is considered complete when it has the core config + weights."""
    if not local_dir.exists():
        return False
    required = ["config.json"]
    weight_candidates = [
        "pytorch_model.bin",
        "model.safetensors",
        "model.onnx",
    ]
    if not any((local_dir / name).exists() for name in required):
        return False
    if not any((local_dir / name).exists() for name in weight_candidates):
        return False
    return True


def ensure_models(cfg: Dict, *, repo_map: Optional[Dict[str, str]] = None) -> None:
    """Ensure required embedding/reranker model directories exist on disk.

    Called from bootstrap before any model load. Blocks until downloads finish
    so that downstream initialization sees the files in place. On error the
    exception is re-raised — the Electron shell will display it to the user.
    """
    repo_map = repo_map or DEFAULT_REPO_MAP

    targets = []
    embedding_cfg = cfg.get("embedding_model", {}) or {}
    embedding_path = embedding_cfg.get("name_or_path")
    if embedding_path:
        targets.append((Path(embedding_path), "bge-m3"))

    reranker_cfg = cfg.get("reranker", {}) or {}
    reranker_path = reranker_cfg.get("name_or_path")
    if reranker_path:
        targets.append((Path(reranker_path), "bge-reranker-large"))

    for local_dir, key in targets:
        if _is_model_complete(local_dir):
            logger.info("Model already present: %s", local_dir)
            continue
        repo_id = repo_map.get(key)
        if not repo_id:
            logger.warning("No repo mapping for model key %s (dir=%s), skipping", key, local_dir)
            continue
        _download_snapshot(repo_id, local_dir)

    _write_status("ready")


def _download_snapshot(repo_id: str, local_dir: Path) -> None:
    """Download one HF repo into `local_dir` via huggingface_hub snapshot API."""
    try:
        from huggingface_hub import snapshot_download  # type: ignore
    except Exception as exc:
        raise RuntimeError(
            "huggingface_hub is required to auto-download models. "
            "Please ensure it is installed in the Python runtime."
        ) from exc

    # Respect user-provided HF_ENDPOINT (e.g. https://hf-mirror.com) for CN access.
    endpoint = os.environ.get("HF_ENDPOINT") or "https://hf-mirror.com"
    os.environ.setdefault("HF_ENDPOINT", endpoint)

    local_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Downloading %s -> %s (endpoint=%s)", repo_id, local_dir, endpoint)
    _write_status("downloading", repo_id=repo_id, target=str(local_dir), endpoint=endpoint)

    snapshot_download(
        repo_id=repo_id,
        local_dir=str(local_dir),
        local_dir_use_symlinks=False,
        allow_patterns=list(_allow_patterns(repo_id)),
    )
    _write_status("downloaded", repo_id=repo_id, target=str(local_dir))
    logger.info("Finished downloading %s", repo_id)


def _allow_patterns(repo_id: str) -> Iterable[str]:
    """Pull just the files we actually need — skip tokenizer variants / flax / tf."""
    base = [
        "config.json",
        "tokenizer.json",
        "tokenizer_config.json",
        "special_tokens_map.json",
        "sentence_bert_config.json",
        "sentencepiece.bpe.model",
        "spiece.model",
        "vocab.txt",
        "modules.json",
        "1_Pooling/*",
        "2_Dense/*",
        "colbert_linear.pt",
        "sparse_linear.pt",
    ]
    # Prefer safetensors if available; fall back to pytorch bin.
    weights = ["model.safetensors", "pytorch_model.bin"]
    return base + weights
