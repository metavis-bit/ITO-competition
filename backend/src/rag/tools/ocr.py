from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class OCRBlock:
    bbox: List[List[int]]  # [[x,y], ...]
    text: str
    conf: float


@dataclass
class OCRResult:
    text: str
    mean_conf: Optional[float]
    blocks: List[OCRBlock]
    engine: str


def _try_paddleocr(image_path: str) -> Optional[OCRResult]:
    try:
        from paddleocr import PaddleOCR  # type: ignore
    except Exception:
        return None

    # NOTE: keep init lazy & cached per-process
    if not hasattr(_try_paddleocr, "_ocr"):
        # lang='ch' works for CN; you can change in config if needed.
        _try_paddleocr._ocr = PaddleOCR(use_angle_cls=True, lang="ch")  # type: ignore[attr-defined]

    ocr = _try_paddleocr._ocr  # type: ignore[attr-defined]
    res = ocr.ocr(image_path, cls=True)

    blocks: List[OCRBlock] = []
    texts: List[str] = []
    confs: List[float] = []

    # paddleocr returns: [[ [bbox], (text, conf) ], ...]
    for line in (res[0] if res else []):
        try:
            bbox, (txt, conf) = line
            bbox_int = [[int(p[0]), int(p[1])] for p in bbox]
            blocks.append(OCRBlock(bbox=bbox_int, text=str(txt), conf=float(conf)))
            if txt:
                texts.append(str(txt))
                confs.append(float(conf))
        except Exception:
            continue

    mean_conf = sum(confs) / len(confs) if confs else None
    text = "\n".join(texts).strip()
    return OCRResult(text=text, mean_conf=mean_conf, blocks=blocks, engine="paddleocr")


def _try_tesseract(image_path: str) -> Optional[OCRResult]:
    try:
        import pytesseract  # type: ignore
        from PIL import Image
    except Exception:
        return None

    try:
        img = Image.open(image_path)
        txt = pytesseract.image_to_string(img, lang="chi_sim+eng")
    except Exception:
        # fallback without specifying language
        try:
            img = Image.open(image_path)
            txt = pytesseract.image_to_string(img)
        except Exception:
            return None

    text = (txt or "").strip()
    return OCRResult(text=text, mean_conf=None, blocks=[], engine="tesseract")


def ocr_image(image_path: str) -> OCRResult:
    """OCR an image using PaddleOCR if available, else fall back to Tesseract.

    Raises RuntimeError if no OCR backend is available.
    """

    out = _try_paddleocr(image_path)
    if out is not None:
        return out

    out = _try_tesseract(image_path)
    if out is not None:
        return out

    raise RuntimeError(
        "No OCR backend available. Install one of: paddleocr + paddlepaddle, or pytesseract + tesseract-ocr."
    )


def save_ocr_result(result: OCRResult, out_path: str) -> None:
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "engine": result.engine,
        "text": result.text,
        "mean_conf": result.mean_conf,
        "blocks": [
            {"bbox": b.bbox, "text": b.text, "conf": b.conf}
            for b in result.blocks
        ],
    }
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
