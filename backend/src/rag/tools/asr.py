from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class ASRSegment:
    start: float
    end: float
    text: str


@dataclass
class ASRResult:
    text: str
    segments: List[ASRSegment]
    engine: str


def _try_faster_whisper(audio_path: str, model_size: str = "medium",
                        device: str = "cuda", compute_type: str = "float16") -> Optional[ASRResult]:
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except Exception:
        return None

    # cache
    key = f"_model_{model_size}_{device}"
    if not hasattr(_try_faster_whisper, key):
        try:
            setattr(_try_faster_whisper, key, WhisperModel(model_size, device=device, compute_type=compute_type))
        except Exception:
            # GPU不可用时退化到CPU
            setattr(_try_faster_whisper, key, WhisperModel(model_size, device="cpu", compute_type="int8"))

    model: WhisperModel = getattr(_try_faster_whisper, key)
    segments_iter, _info = model.transcribe(audio_path)

    segs: List[ASRSegment] = []
    texts: List[str] = []
    for s in segments_iter:
        segs.append(ASRSegment(start=float(s.start), end=float(s.end), text=str(s.text).strip()))
        if s.text:
            texts.append(str(s.text).strip())

    return ASRResult(text=" ".join(texts).strip(), segments=segs, engine=f"faster-whisper:{model_size}")


def _try_openai_whisper(audio_path: str, model_size: str = "small") -> Optional[ASRResult]:
    try:
        import whisper  # type: ignore
    except Exception:
        return None

    key = f"_whisper_{model_size}"
    if not hasattr(_try_openai_whisper, key):
        setattr(_try_openai_whisper, key, whisper.load_model(model_size))

    model = getattr(_try_openai_whisper, key)
    res = model.transcribe(audio_path)

    segs: List[ASRSegment] = []
    for s in res.get("segments", []) or []:
        segs.append(ASRSegment(start=float(s.get("start", 0.0)), end=float(s.get("end", 0.0)), text=str(s.get("text", "")).strip()))

    text = str(res.get("text", "")).strip()
    return ASRResult(text=text, segments=segs, engine=f"openai-whisper:{model_size}")


def transcribe_audio(audio_path: str, prefer: str = "faster-whisper", model_size: str = "medium",
                     device: str = "cuda", compute_type: str = "float16") -> ASRResult:
    """Transcribe audio using Faster-Whisper or OpenAI Whisper.

    prefer:
      - "faster-whisper" (default)
      - "openai-whisper"

    Raises RuntimeError if no backend is available.
    """

    if prefer == "faster-whisper":
        r = _try_faster_whisper(audio_path, model_size=model_size, device=device, compute_type=compute_type)
        if r is not None:
            return r
        r = _try_openai_whisper(audio_path, model_size=model_size)
        if r is not None:
            return r
    else:
        r = _try_openai_whisper(audio_path, model_size=model_size)
        if r is not None:
            return r
        r = _try_faster_whisper(audio_path, model_size=model_size, device=device, compute_type=compute_type)
        if r is not None:
            return r

    raise RuntimeError(
        "No ASR backend available. Install one of: faster-whisper, or openai-whisper. Also ensure ffmpeg is installed for video/audio." 
    )


def save_asr_result(result: ASRResult, out_path: str) -> None:
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "engine": result.engine,
        "text": result.text,
        "segments": [
            {"start": s.start, "end": s.end, "text": s.text}
            for s in result.segments
        ],
    }
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def extract_audio_with_ffmpeg(video_path: str, out_wav_path: str) -> None:
    """Extract audio track to wav using ffmpeg."""
    p = Path(out_wav_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ar",
        "16000",
        "-ac",
        "1",
        str(out_wav_path),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
