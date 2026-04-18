
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont  # type: ignore
import difflib


def _safe_mkdir(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p


def _load_json(p: Path) -> Dict[str, Any]:
    return json.loads(p.read_text(encoding="utf-8"))


def _try_load_font(size: int = 18) -> ImageFont.ImageFont:
    # Try common monospace fonts; fallback to default
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for c in candidates:
        try:
            if Path(c).exists():
                return ImageFont.truetype(c, size=size)
        except Exception:
            pass
    return ImageFont.load_default()


def _bbox_from_quad(quad: List[List[float]]) -> Tuple[float, float, float, float]:
    xs = [p[0] for p in quad]
    ys = [p[1] for p in quad]
    return (min(xs), min(ys), max(xs), max(ys))


def _union_bbox(a: Tuple[float, float, float, float], b: Tuple[float, float, float, float]) -> Tuple[float, float, float, float]:
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def _crop_with_margin(img: Image.Image, bbox: Tuple[float, float, float, float], margin: int = 24) -> Image.Image:
    w, h = img.size
    x0, y0, x1, y1 = bbox
    x0 = max(0, int(math.floor(x0)) - margin)
    y0 = max(0, int(math.floor(y0)) - margin)
    x1 = min(w, int(math.ceil(x1)) + margin)
    y1 = min(h, int(math.ceil(y1)) + margin)
    return img.crop((x0, y0, x1, y1))


def _draw_ocr_boxes(img: Image.Image, blocks: List[Dict[str, Any]], highlight_bbox: Optional[Tuple[float, float, float, float]] = None) -> Image.Image:
    out = img.copy()
    draw = ImageDraw.Draw(out)

    # draw all boxes
    for b in blocks:
        quad = b.get("bbox")
        if not quad:
            continue
        try:
            pts = [(float(x), float(y)) for x, y in quad]
        except Exception:
            continue
        draw.polygon(pts, outline=(0, 255, 0), width=2)

    if highlight_bbox:
        x0, y0, x1, y1 = highlight_bbox
        draw.rectangle([x0, y0, x1, y1], outline=(255, 0, 0), width=4)

    return out


def _best_match_bbox(snippet: str, blocks: List[Dict[str, Any]]) -> Optional[Tuple[float, float, float, float]]:
    """
    Heuristic: match citation snippet to OCR blocks, return union bbox of the best match.
    """
    s = (snippet or "").strip().replace("\n", " ")
    if not s or not blocks:
        return None
    s = s[:120]  # keep short

    best = None
    best_score = 0.0

    for b in blocks:
        t = (b.get("text") or "").strip().replace("\n", " ")
        if not t:
            continue
        # quick filter
        if len(t) < 2:
            continue
        score = difflib.SequenceMatcher(None, s, t[:120]).ratio()
        if score > best_score:
            quad = b.get("bbox")
            if quad:
                best_score = score
                best = _bbox_from_quad(quad)

    if best and best_score >= 0.45:
        return best
    return None


def _render_text_card(text: str, title: str, out_path: Path, width: int = 1200) -> None:
    text = (text or "").strip()
    font = _try_load_font(20)
    title_font = _try_load_font(26)

    # wrap lines
    max_chars = 90
    lines = []
    for raw in (text.splitlines() if text else [""]):
        r = raw.rstrip()
        if not r:
            lines.append("")
            continue
        while len(r) > max_chars:
            lines.append(r[:max_chars])
            r = r[max_chars:]
        lines.append(r)

    title_h = 50
    line_h = 26
    pad = 30
    h = title_h + pad + max(10, len(lines)) * line_h + pad
    img = Image.new("RGB", (width, h), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)

    draw.text((pad, pad), title, fill=(0, 0, 0), font=title_font)
    y = pad + title_h
    for ln in lines[:300]:
        draw.text((pad, y), ln, fill=(10, 10, 10), font=font)
        y += line_h

    img.save(out_path)


def _ensure_pdf_page_image(pdf_path: Path, page: int, out_path: Path) -> bool:
    """
    Render a PDF page to an image using PyMuPDF if available.
    """
    try:
        import fitz  # PyMuPDF
    except Exception:
        return False

    try:
        doc = fitz.open(str(pdf_path))
        p = doc.load_page(max(0, page - 1))
        pix = p.get_pixmap(dpi=180, alpha=False)
        _safe_mkdir(out_path.parent)
        pix.save(str(out_path))
        doc.close()
        return True
    except Exception:
        return False


@dataclass
class RenderItem:
    citation_n: int
    kind: str
    title: str
    image_path: Optional[str] = None
    extra: Optional[Dict[str, Any]] = None


def render_evidence(evidence_json_path: str, store_dir: str = "rag_store") -> Dict[str, Any]:
    """
    Given rag_store/debug/evidence_*.json, create visual assets under rag_store/assets/rendered/<evidence_tag>/.
    Returns a manifest dict.
    """
    ev_path = Path(evidence_json_path)
    if not ev_path.exists():
        raise FileNotFoundError(str(ev_path))

    ev = _load_json(ev_path)
    tag = ev.get("evidence_tag") or ev_path.stem.replace("evidence_", "")
    citations: List[Dict[str, Any]] = ev.get("citations") or []
    ctx = ev.get("retrieved_context") or []
    # map n -> context text if available
    ctx_map = {int(x.get("n")): (x.get("text") or "") for x in ctx if x.get("n") is not None}

    out_dir = Path(store_dir) / "assets" / "rendered" / str(tag)
    _safe_mkdir(out_dir)

    rendered: List[RenderItem] = []

    for c in citations:
        n = int(c.get("n", 0))
        loc = c.get("loc") or ""
        src = c.get("source_type") or ""
        page = c.get("page")
        frame_ts = c.get("frame_ts")
        sheet = c.get("sheet")
        slide = c.get("slide")
        image_path = c.get("image_path")
        frame_path = c.get("frame_path")
        page_image_path = c.get("page_image_path")
        ocr_path = c.get("ocr_path")
        abs_path = c.get("abs_path")  # may be None
        snippet = c.get("text") or ctx_map.get(n, "")

        title_parts = [f"[{n}] {loc}"]
        if page:
            title_parts.append(f"p{page}")
        if frame_ts is not None:
            title_parts.append(f"t{frame_ts:.1f}s" if isinstance(frame_ts, (int, float)) else f"t{frame_ts}")
        if sheet:
            title_parts.append(f"sheet:{sheet}")
        if slide is not None:
            title_parts.append(f"slide:{slide}")
        title = " | ".join(title_parts)

        # decide base image
        base_img_path: Optional[Path] = None
        kind = "text"
        if page_image_path:
            base_img_path = Path(page_image_path)
            kind = "pdf_page"
        elif frame_path:
            base_img_path = Path(frame_path)
            kind = "video_frame"
        elif image_path:
            base_img_path = Path(image_path)
            kind = "image"
        else:
            # can we render pdf page from abs_path?
            if abs_path and str(abs_path).lower().endswith(".pdf") and page:
                cache_img = Path(store_dir) / "assets" / "pdf_pages_render" / (c.get("doc_id","doc")) / f"page_{int(page):04d}.png"
                ok = _ensure_pdf_page_image(Path(abs_path), int(page), cache_img)
                if ok:
                    base_img_path = cache_img
                    kind = "pdf_page"
            # else stay as text

        # load OCR
        blocks: List[Dict[str, Any]] = []
        if ocr_path:
            p = Path(ocr_path)
            if p.exists():
                try:
                    o = _load_json(p)
                    blocks = o.get("blocks") or []
                except Exception:
                    blocks = []

        if base_img_path and base_img_path.exists():
            img = Image.open(str(base_img_path)).convert("RGB")
            hi = _best_match_bbox(snippet, blocks) if blocks else None
            annotated = _draw_ocr_boxes(img, blocks, hi) if blocks else img

            full_path = out_dir / f"c{n:02d}_{kind}_full.png"
            annotated.save(full_path)

            rendered.append(RenderItem(citation_n=n, kind=f"{kind}_full", title=title, image_path=str(full_path)))

            if hi:
                crop = _crop_with_margin(annotated, hi, margin=40)
                crop_path = out_dir / f"c{n:02d}_{kind}_crop.png"
                crop.save(crop_path)
                rendered.append(RenderItem(citation_n=n, kind=f"{kind}_crop", title=title + " (crop)", image_path=str(crop_path)))
        else:
            # text card (for docx/ppt/xlsx/html/audio)
            card_path = out_dir / f"c{n:02d}_text.png"
            preview = snippet.strip()
            if not preview:
                preview = ev.get("retrieved_context", "")
                if isinstance(preview, list) and preview:
                    preview = preview[0].get("text","")
            if len(preview) > 1800:
                preview = preview[:1800] + " ..."
            _render_text_card(preview, title=title, out_path=card_path)
            rendered.append(RenderItem(citation_n=n, kind="text_card", title=title, image_path=str(card_path), extra={"source_type": src}))

    manifest = {
        "evidence_tag": tag,
        "evidence_json": str(ev_path),
        "out_dir": str(out_dir),
        "items": [ri.__dict__ for ri in rendered],
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def render_evidence_gallery(evidence: List[Dict[str, Any]], store_dir: str = "rag_store", tag: str = "ui") -> Dict[str, Any]:
    """Render evidence gallery from an in-memory evidence list.

    This is a convenience wrapper for Gradio UI / other modules.
    It writes a temporary evidence json into rag_store/debug and then calls render_evidence().
    """
    from pathlib import Path
    import json
    debug_dir = Path(store_dir) / "debug"
    debug_dir.mkdir(parents=True, exist_ok=True)
    ev_path = debug_dir / f"evidence_{tag}.json"
    ev_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    return render_evidence(str(ev_path), store_dir=store_dir)
