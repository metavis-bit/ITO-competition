"""
Video Analysis Pipeline — competition core differentiator.

Closed loop: video → keyframes + ASR → RAG ingest → courseware references frames.

Uses wym's existing parsers (FFmpeg + Whisper + VLM) and RAGEngine ingestion.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("video_pipeline")


class VideoPipeline:
    """
    Processes teaching videos through the full analysis loop:

    1. FFmpeg extracts audio → faster-whisper ASR transcription
    2. FFmpeg extracts keyframes at configurable intervals
    3. VLM describes each keyframe (optional, falls back to OCR)
    4. All evidence (ASR segments + frame descriptions) ingested into Milvus
       under a session-scoped index ``ref:{session_id}``
    5. Subsequent courseware generation retrieves video evidence via RAG

    Usage::

        vp = VideoPipeline(rag_engine)
        result = vp.process("Central_Dogma.mp4", session_id="demo_001")
        # result.frames, result.transcript_chunks, etc.
    """

    def __init__(
        self,
        rag_engine,           # RAGEngine instance (from bootstrap)
        config_path: str = "config.yaml",
        output_base: str = "./outputs",
    ):
        self.engine = rag_engine
        self.config_path = config_path
        self.output_base = output_base

        # Lazy-load config
        self._cfg: Optional[Dict[str, Any]] = None

    @property
    def cfg(self) -> Dict[str, Any]:
        if self._cfg is None:
            from ..config import load_config
            self._cfg = load_config(self.config_path)
        return self._cfg

    # ── Public API ──

    def process(
        self,
        video_path: str,
        session_id: str,
        *,
        index: Optional[str] = None,
        frame_interval_sec: float = 5.0,
        max_frames: int = 20,
        vlm_max_frames: int = 8,
    ) -> VideoProcessResult:
        """
        Full video analysis pipeline.

        Args:
            video_path: Path to video file (.mp4, .mov, .mkv, etc.)
            session_id: Session ID for RAG index isolation.
            index: Milvus index name. Defaults to ``ref:{session_id}``.
            frame_interval_sec: Seconds between keyframe samples.
            max_frames: Maximum number of frames to extract.
            vlm_max_frames: Max frames to describe with VLM.

        Returns:
            VideoProcessResult with frame paths, transcript info, timing.
        """
        t0 = time.time()
        vpath = Path(video_path)

        if not vpath.exists():
            raise FileNotFoundError(f"Video not found: {video_path}")

        target_index = index or f"ref:{session_id}"
        assets_dir = str(Path(self.output_base) / session_id / "assets")
        Path(assets_dir).mkdir(parents=True, exist_ok=True)

        logger.info(
            "Processing video: %s (session=%s, index=%s)",
            vpath.name, session_id, target_index,
        )

        # ── Step 1-4: Parse video using wym's unified parser ──
        parse_cfg = dict(self.cfg.get("parsing", {}))

        # Override video-specific settings
        video_cfg = dict(parse_cfg.get("video", {}))
        video_cfg["extract_frames"] = True
        video_cfg["frame_interval_sec"] = frame_interval_sec
        video_cfg["max_frames"] = max_frames
        video_cfg["describe_frames_with_vlm"] = True
        video_cfg["vlm_max_frames"] = vlm_max_frames
        video_cfg["segment_level"] = True
        video_cfg["combine_asr_and_frames"] = True
        parse_cfg["video"] = video_cfg

        from ..parsers import parse_file

        parsed_docs = parse_file(
            str(vpath),
            root_dir=str(vpath.parent),
            source_type="video_lecture",
            session_id=session_id,
            assets_dir=assets_dir,
            parse_cfg=parse_cfg,
        )

        if not parsed_docs:
            logger.warning("No documents parsed from video: %s", vpath.name)
            return VideoProcessResult(
                session_id=session_id,
                video_path=str(vpath),
                index=target_index,
                frames=[],
                transcript_chunks=0,
                vlm_descriptions=0,
                total_docs=0,
                processing_time_sec=time.time() - t0,
            )

        # ── Step 5: Ingest all parsed evidence into Milvus ──
        items = [{"text": doc.text, "meta": doc.meta} for doc in parsed_docs]

        ingest_result = self.engine.ingest_items(
            items,
            index=target_index,
            source_type="video_lecture",
            session_id=session_id,
        )

        logger.info(
            "Ingested %d docs → index=%s (%d chunks)",
            len(items), target_index,
            ingest_result.get("chunks", 0),
        )

        # ── Collect frame paths from parsed metadata ──
        frames: List[FrameInfo] = []
        vlm_count = 0

        for doc in parsed_docs:
            meta = doc.meta
            frame_path = meta.get("frame_path")
            if frame_path and Path(frame_path).exists():
                fi = FrameInfo(
                    path=frame_path,
                    timestamp_sec=meta.get("frame_ts"),
                    vlm_description=doc.text if meta.get("vlm_used") else None,
                    ocr_text=doc.text if "ocr" in meta.get("part", "") else None,
                )
                frames.append(fi)
                if meta.get("vlm_used"):
                    vlm_count += 1

        # Deduplicate frames by path
        seen_paths = set()
        unique_frames = []
        for f in frames:
            if f.path not in seen_paths:
                seen_paths.add(f.path)
                unique_frames.append(f)

        # Count ASR segments
        asr_chunks = sum(
            1 for doc in parsed_docs
            if "asr" in doc.meta.get("part", "") and "combined" not in doc.meta.get("part", "")
        )

        result = VideoProcessResult(
            session_id=session_id,
            video_path=str(vpath),
            index=target_index,
            frames=unique_frames,
            transcript_chunks=asr_chunks,
            vlm_descriptions=vlm_count,
            total_docs=len(parsed_docs),
            processing_time_sec=time.time() - t0,
        )

        logger.info(
            "Video processing complete: %d frames, %d ASR segments, %d VLM descriptions (%.1fs)",
            len(unique_frames), asr_chunks, vlm_count, result.processing_time_sec,
        )

        return result

    def process_cached(
        self,
        video_path: str,
        session_id: str,
        cache_dir: str = "./rag_store/video_cache",
        **kwargs,
    ) -> VideoProcessResult:
        """
        Process with disk cache — for competition demo.

        If a cached result exists for this video+session, load it directly
        instead of re-processing. Saves time during live demo.
        """
        import json

        cache_path = Path(cache_dir) / f"{session_id}_{Path(video_path).stem}.json"

        if cache_path.exists():
            logger.info("Loading cached video result: %s", cache_path)
            data = json.loads(cache_path.read_text(encoding="utf-8"))
            return VideoProcessResult.from_dict(data)

        # Process and cache
        result = self.process(video_path, session_id, **kwargs)

        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("Cached video result: %s", cache_path)

        return result


# ── Result Types ──

class FrameInfo:
    """Info about a single extracted keyframe."""

    __slots__ = ("path", "timestamp_sec", "vlm_description", "ocr_text")

    def __init__(
        self,
        path: str,
        timestamp_sec: Optional[float] = None,
        vlm_description: Optional[str] = None,
        ocr_text: Optional[str] = None,
    ):
        self.path = path
        self.timestamp_sec = timestamp_sec
        self.vlm_description = vlm_description
        self.ocr_text = ocr_text

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "timestamp_sec": self.timestamp_sec,
            "vlm_description": self.vlm_description,
            "ocr_text": self.ocr_text,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "FrameInfo":
        return cls(
            path=d["path"],
            timestamp_sec=d.get("timestamp_sec"),
            vlm_description=d.get("vlm_description"),
            ocr_text=d.get("ocr_text"),
        )


class VideoProcessResult:
    """Result of processing a single video."""

    __slots__ = (
        "session_id", "video_path", "index", "frames",
        "transcript_chunks", "vlm_descriptions", "total_docs",
        "processing_time_sec",
    )

    def __init__(
        self,
        session_id: str,
        video_path: str,
        index: str,
        frames: List[FrameInfo],
        transcript_chunks: int,
        vlm_descriptions: int,
        total_docs: int,
        processing_time_sec: float,
    ):
        self.session_id = session_id
        self.video_path = video_path
        self.index = index
        self.frames = frames
        self.transcript_chunks = transcript_chunks
        self.vlm_descriptions = vlm_descriptions
        self.total_docs = total_docs
        self.processing_time_sec = processing_time_sec

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "video_path": self.video_path,
            "index": self.index,
            "frames": [f.to_dict() for f in self.frames],
            "transcript_chunks": self.transcript_chunks,
            "vlm_descriptions": self.vlm_descriptions,
            "total_docs": self.total_docs,
            "processing_time_sec": self.processing_time_sec,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "VideoProcessResult":
        return cls(
            session_id=d["session_id"],
            video_path=d["video_path"],
            index=d["index"],
            frames=[FrameInfo.from_dict(f) for f in d.get("frames", [])],
            transcript_chunks=d["transcript_chunks"],
            vlm_descriptions=d["vlm_descriptions"],
            total_docs=d["total_docs"],
            processing_time_sec=d["processing_time_sec"],
        )
