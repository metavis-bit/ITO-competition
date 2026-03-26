from __future__ import annotations

import subprocess
from pathlib import Path
from typing import List, Optional


def has_ffmpeg() -> bool:
    try:
        subprocess.run(["ffmpeg", "-version"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


def extract_frames_with_ffmpeg(
    video_path: str,
    out_dir: str,
    interval_sec: float = 5.0,
    max_frames: int = 20,
    image_format: str = "jpg",
) -> List[str]:
    """Extract keyframes / frames every N seconds using ffmpeg.

    Returns a list of extracted frame file paths.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    interval_sec = float(interval_sec)
    if interval_sec <= 0:
        interval_sec = 5.0

    # fps = 1 / interval_sec
    fps_expr = f"1/{interval_sec}"
    pattern = str(out / f"frame_%05d.{image_format}")

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-vf",
        f"fps={fps_expr}",
        "-frames:v",
        str(int(max_frames)),
        pattern,
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    return [str(p) for p in sorted(out.glob(f"frame_*.{image_format}"))]


def convert_audio_to_wav(
    audio_path: str,
    out_wav_path: str,
    sample_rate: int = 16000,
) -> None:
    """Convert audio to mono wav via ffmpeg."""
    p = Path(out_wav_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(audio_path),
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ar",
        str(int(sample_rate)),
        "-ac",
        "1",
        str(out_wav_path),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
