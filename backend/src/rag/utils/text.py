from __future__ import annotations

import hashlib
import re
from typing import List, Optional


def chunk_text(
    text: str,
    max_chars: Optional[int] = None,
    overlap: int = 60,
    chunk_size: Optional[int] = None,
) -> List[str]:
    """Backward-compatible chunker.

    Historical code may call:
      - chunk_text(text, max_chars=..., overlap=...)
      - chunk_text(text, chunk_size=..., overlap=...)

    This function keeps that behavior.

    NOTE: For better semantic chunks, prefer :func:`chunk_text_recursive`.
    """

    text = (text or "").strip()
    if not text:
        return []

    size = max_chars if max_chars is not None else chunk_size
    if size is None or int(size) <= 0:
        return [text]

    size = int(size)
    overlap = max(0, min(int(overlap), size - 1))

    chunks: List[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(n, start + size)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end == n:
            break
        start = end - overlap
    return chunks


def _split_keep_sep(text: str, sep: str) -> List[str]:
    """Split by sep but keep sep attached to the left part (like LangChain)."""
    if sep == "":
        return list(text)
    parts = text.split(sep)
    out: List[str] = []
    for i, p in enumerate(parts):
        if i == len(parts) - 1:
            if p:
                out.append(p)
        else:
            out.append(p + sep)
    return [x for x in out if x]


def _recursive_split(text: str, separators: List[str], chunk_size: int) -> List[str]:
    """Recursive splitting (roughly similar to RecursiveCharacterTextSplitter)."""
    text = text.strip()
    if len(text) <= chunk_size or not separators:
        return [text] if text else []

    sep = separators[0]
    splits = _split_keep_sep(text, sep)

    # If the first separator doesn't actually split, fall back to next.
    if len(splits) <= 1:
        return _recursive_split(text, separators[1:], chunk_size)

    # Merge splits to satisfy chunk_size.
    merged: List[str] = []
    buf: List[str] = []
    buf_len = 0
    for s in splits:
        if buf_len + len(s) <= chunk_size or not buf:
            buf.append(s)
            buf_len += len(s)
        else:
            merged.append("".join(buf).strip())
            buf = [s]
            buf_len = len(s)
    if buf:
        merged.append("".join(buf).strip())

    # Any merged chunk still too long: recurse with next separators.
    out: List[str] = []
    for m in merged:
        if len(m) <= chunk_size:
            if m:
                out.append(m)
        else:
            out.extend(_recursive_split(m, separators[1:], chunk_size))
    return [x for x in out if x]


def chunk_text_recursive(
    text: str,
    chunk_size: int = 500,
    overlap: int = 50,
    separators: Optional[List[str]] = None,
) -> List[str]:
    """Semantic-friendlier chunking.

    - First split by paragraphs / newlines
    - Then by Chinese / English sentence punctuation
    - Then by smaller separators

    Finally apply overlap (character-based) across chunks.
    """

    text = (text or "").strip()
    if not text:
        return []

    chunk_size = int(chunk_size)
    if chunk_size <= 0:
        return [text]

    overlap = max(0, min(int(overlap), chunk_size - 1))

    if separators is None:
        # Larger -> smaller
        separators = [
            "\n\n",
            "\n",
            "。",
            "！",
            "？",
            ". ",
            "! ",
            "? ",
            ";",
            "；",
            ",",
            "，",
            " ",
            "",
        ]

    raw_chunks = _recursive_split(text, separators, chunk_size)
    raw_chunks = [c.strip() for c in raw_chunks if c and c.strip()]

    if not raw_chunks:
        return []

    # Apply overlap
    if overlap <= 0:
        return raw_chunks

    out: List[str] = []
    for c in raw_chunks:
        if not out:
            out.append(c)
            continue
        prev = out[-1]
        # take overlap tail from prev
        tail = prev[-overlap:]
        out.append((tail + c).strip())
    return out


def sanitize_collection_name(name: str, max_len: int = 63) -> str:
    """Make collection names safe for vector DBs (Milvus/Chroma/etc.)."""

    raw = (name or "").strip()
    safe = re.sub(r"[^0-9a-zA-Z_-]+", "_", raw).strip("_-")
    if len(safe) < 3:
        safe = (safe + "_col")[:max_len]
    if len(safe) > max_len:
        h = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]
        safe = safe[: max_len - 9] + "_" + h
    return safe
