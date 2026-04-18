from __future__ import annotations

"""Small IO helpers.

NOTE: The main ingestion pipeline uses `rag.parsers.parse_file`.
This module exists mostly for backwards compatibility / small utilities.
"""

from pathlib import Path
from typing import Iterable, List, Optional, Sequence


def iter_files(input_dir: str, exts: Optional[Sequence[str]] = None) -> List[Path]:
    root = Path(input_dir)
    if not root.exists():
        return []
    exts_set = {e.lower() for e in exts} if exts else None

    files: List[Path] = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if exts_set is not None and p.suffix.lower() not in exts_set:
            continue
        files.append(p)
    return files


def load_any(path: str) -> str:
    """Best-effort load a file into text.

    For multi-part formats (PDF/PPTX/XLSX/video...), it will join parts with blank lines.
    """

    from ..parsers import parse_file

    p = Path(path)
    if not p.exists() or not p.is_file():
        return ""

    docs = parse_file(
        str(p),
        root_dir=str(p.parent),
        source_type="unknown",
        session_id="",
        assets_dir=None,
        parse_cfg={},
    )
    texts = [d.text for d in docs if d.text and d.text.strip()]
    return "\n\n".join(texts).strip()
