"""
FastAPI backend — the canonical API contract.

All routes delegate to PipelineOrchestrator. This is a thin transport layer.
"""
from __future__ import annotations

import asyncio
import json
import logging
import shutil
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..domain.models import (
    ArtifactType,
    CascadeLevel,
    PipelineResult,
    RefineRequest,
    TeachingIntent,
)
from ..services.pipeline_orchestrator import PipelineOrchestrator
from ..dialogue.dialogue_manager import DialogueManager, DialogueState
from ..dialogue.role_discussion import generate_role_discussion_events
from ..services.video_pipeline import VideoPipeline

logger = logging.getLogger("api")


# ── Request / Response Models ──

class GenerateRequest(BaseModel):
    session_id: Optional[str] = None
    topic: str = ""
    subject: str = ""
    target_audience: str = ""
    teaching_goal: str = ""
    grade_level: str = ""
    page_range: str = "10-15"
    key_focus: List[str] = Field(default_factory=list)
    difficulties: List[str] = Field(default_factory=list)
    game_types: List[str] = Field(default_factory=list)
    special_requirements: str = ""
    indexes: List[str] = Field(default_factory=lambda: ["kb"])
    output_types: List[str] = Field(default_factory=lambda: ["pptx", "docx", "game_html", "animation_html"])


class RefineAPIRequest(BaseModel):
    session_id: str
    feedback: str
    cascade_level: int = 2
    target_types: List[str] = Field(default_factory=lambda: ["pptx", "docx"])


class IngestRequest(BaseModel):
    dir_path: str
    index: str = "kb"
    session_id: str = "kb"


class QueryRequest(BaseModel):
    question: str
    indexes: List[str] = Field(default_factory=lambda: ["kb"])
    top_k: int = 6


class RollbackRequest(BaseModel):
    session_id: str
    version_id: str


class StreamRequest(BaseModel):
    session_id: Optional[str] = None
    topic: str = ""
    subject: str = ""
    target_audience: str = ""
    teaching_goal: str = ""
    grade_level: str = ""
    page_range: str = "10-15"
    key_focus: List[str] = Field(default_factory=list)
    difficulties: List[str] = Field(default_factory=list)
    game_types: List[str] = Field(default_factory=list)
    special_requirements: str = ""
    indexes: List[str] = Field(default_factory=lambda: ["kb"])


class ChatRequest(BaseModel):
    session_id: Optional[str] = None
    message: str = ""
    # requirements | qa | discussion
    session_type: str = "requirements"
    discussion_topic: str = ""
    discussion_prompt: str = ""
    trigger_agent_id: Optional[str] = None
    messages: List[Dict[str, Any]] = Field(default_factory=list)
    agent_ids: List[str] = Field(default_factory=list)
    agent_configs: List[Dict[str, Any]] = Field(default_factory=list)
    user_profile: Dict[str, Any] = Field(default_factory=dict)


# ── App Factory ──

def create_fastapi_app(pipeline: PipelineOrchestrator, config_path: str = "config.yaml") -> FastAPI:
    """Create FastAPI app with all routes wired to the pipeline."""

    app = FastAPI(
        title="ITO Teaching Agent API",
        description="AI-powered multi-modal interactive teaching system",
        version="3.0.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Store pipeline in app state
    app.state.pipeline = pipeline

    # ── Serve biology assets (images) as static files ──
    _assets_images_dir = Path(__file__).resolve().parent.parent.parent.parent / "assets" / "images"
    if _assets_images_dir.is_dir():
        app.mount("/v1/assets/images", StaticFiles(directory=str(_assets_images_dir)), name="assets-images")

    def _rag_unavailable_detail() -> str:
        reason = getattr(pipeline, "rag_init_error", None)
        if reason:
            return f"RAG engine not initialized: {reason}"
        return "RAG engine not initialized"

    # ── Health ──

    @app.get("/v1/health")
    async def health():
        return {
            "status": "ok",
            "version": "3.0.0",
            "rag": {
                "initialized": pipeline.retriever is not None,
                "error": getattr(pipeline, "rag_init_error", None),
            },
        }

    # ── Image Matching ──

    @app.post("/v1/images/match")
    async def match_image(req: dict):
        """Find the best matching biology image for a slide title/content."""
        from ..image_matcher import find_best_image, IMAGE_KEYWORD_MAP

        title = req.get("title", "")
        content_points = req.get("content_points", [])
        used = set(req.get("used_images", []))
        assets_dir = str(_assets_images_dir) if _assets_images_dir.is_dir() else "assets/images"

        path = find_best_image(title, content_points, assets_dir, used)
        if path:
            filename = Path(path).name
            return {"matched": True, "filename": filename, "url": f"/v1/assets/images/{filename}"}
        return {"matched": False, "filename": None, "url": None}

    @app.get("/v1/images/list")
    async def list_images():
        """List all available biology images (built-in + user-uploaded)."""
        from ..image_matcher import IMAGE_KEYWORD_MAP

        results = []
        assets_dir = _assets_images_dir if _assets_images_dir.is_dir() else Path("assets/images")

        # Built-in images with keywords
        for filename, keywords in IMAGE_KEYWORD_MAP.items():
            img_path = assets_dir / filename
            if img_path.exists():
                results.append({"filename": filename, "keywords": keywords[:5], "url": f"/v1/assets/images/{filename}", "builtin": True})

        # User-uploaded images (any file in the dir not in keyword map)
        if assets_dir.is_dir():
            for f in assets_dir.iterdir():
                if f.suffix.lower() in ('.jpg', '.jpeg', '.png', '.webp', '.gif') and f.name not in IMAGE_KEYWORD_MAP:
                    results.append({"filename": f.name, "keywords": [], "url": f"/v1/assets/images/{f.name}", "builtin": False})

        return {"images": results}

    @app.post("/v1/images/upload")
    async def upload_image(
        file: UploadFile = File(...),
        keywords: str = Form(""),
    ):
        """Upload a biology image to the assets library."""
        if not file.filename:
            raise HTTPException(400, "No filename provided")

        # Validate file type
        ext = Path(file.filename).suffix.lower()
        if ext not in ('.jpg', '.jpeg', '.png', '.webp', '.gif'):
            raise HTTPException(400, f"Unsupported image format: {ext}")

        assets_dir = _assets_images_dir if _assets_images_dir.is_dir() else Path("assets/images")
        assets_dir.mkdir(parents=True, exist_ok=True)

        # Save file
        dest = assets_dir / file.filename
        content = await file.read()
        dest.write_bytes(content)

        # Optionally add keywords to the matcher
        if keywords.strip():
            from ..image_matcher import IMAGE_KEYWORD_MAP
            kw_list = [k.strip() for k in keywords.split(",") if k.strip()]
            if kw_list:
                IMAGE_KEYWORD_MAP[file.filename] = kw_list

        return {
            "filename": file.filename,
            "url": f"/v1/assets/images/{file.filename}",
            "size": len(content),
        }

    @app.delete("/v1/images/{filename}")
    async def delete_image(filename: str):
        """Delete a user-uploaded image."""
        from ..image_matcher import IMAGE_KEYWORD_MAP

        assets_dir = _assets_images_dir if _assets_images_dir.is_dir() else Path("assets/images")
        img_path = assets_dir / filename

        if not img_path.exists():
            raise HTTPException(404, "Image not found")

        img_path.unlink()
        IMAGE_KEYWORD_MAP.pop(filename, None)
        return {"deleted": filename}

    # ── Knowledge Ingestion ──

    @app.post("/v1/knowledge/ingest")
    async def ingest_knowledge(req: IngestRequest):
        """Ingest documents into RAG knowledge base."""
        if pipeline.retriever is None or not hasattr(pipeline.retriever, "engine"):
            raise HTTPException(400, _rag_unavailable_detail())

        try:
            result = await asyncio.to_thread(
                pipeline.retriever.engine.ingest_dir,
                req.dir_path,
                index=req.index,
                source_type="knowledge_base",
                session_id=req.session_id,
            )
            return {"status": "ok", "result": result}
        except Exception as e:
            raise HTTPException(500, f"Ingestion failed: {e}")

    # ── Knowledge Query ──

    @app.post("/v1/knowledge/query")
    async def query_knowledge(req: QueryRequest):
        """Query the RAG knowledge base."""
        if pipeline.retriever is None:
            raise HTTPException(400, _rag_unavailable_detail())

        try:
            result = await asyncio.to_thread(
                pipeline.retriever.retrieve_text,
                req.question,
                indexes=req.indexes,
                top_k=req.top_k,
            )
            return {"status": "ok", "context": result}
        except Exception as e:
            raise HTTPException(500, f"Query failed: {e}")

    # ── Reference Upload (multi-format) ──

    @app.post("/v1/knowledge/upload")
    async def upload_reference_file(
        file: UploadFile = File(...),
        session_id: Optional[str] = Form(None),
        index: Optional[str] = Form(None),
        teacher_note: str = Form(""),
        purpose: str = Form("reference_upload"),
    ):
        """
        Upload one reference file (PDF/Word/PPT/Image/Video/Audio/Text),
        parse it, and ingest parsed chunks into RAG.

        This endpoint closes the gap where frontend could upload files but
        backend ingestion only supported local filesystem paths.
        """
        if pipeline.retriever is None or not hasattr(pipeline.retriever, "engine"):
            raise HTTPException(400, _rag_unavailable_detail())

        raw_session_id = (session_id or "").strip() or f"sess_{uuid.uuid4().hex[:12]}"
        target_index = (index or "").strip() or f"ref:{raw_session_id}"
        safe_session_id = _safe_path_component(raw_session_id)

        upload_root = Path("rag_store") / "uploads" / safe_session_id
        upload_root.mkdir(parents=True, exist_ok=True)

        original_name = Path(file.filename or f"upload_{uuid.uuid4().hex[:8]}").name
        saved_name = f"{uuid.uuid4().hex[:8]}_{original_name}"
        saved_path = upload_root / saved_name

        with open(saved_path, "wb") as out:
            shutil.copyfileobj(file.file, out)

        try:
            from ..config import load_config
            from ..parsers import parse_file

            cfg = load_config(config_path)
            parse_cfg = cfg.get("parsing", {}) or {}
            parsed_docs = await asyncio.to_thread(
                parse_file,
                str(saved_path),
                root_dir=str(upload_root),
                source_type=purpose or "reference_upload",
                session_id=raw_session_id,
                assets_dir=str(Path("rag_store") / "assets" / safe_session_id),
                parse_cfg=parse_cfg,
            )

            items = []
            preview_parts: List[str] = []
            for doc in parsed_docs:
                text = (doc.text or "").strip()
                if not text:
                    continue
                meta = dict(doc.meta or {})
                if teacher_note:
                    meta["teacher_note"] = teacher_note
                meta["uploaded_file_name"] = original_name
                items.append({"text": text, "meta": meta})
                if len(preview_parts) < 3:
                    preview_parts.append(text[:600])

            if not items:
                raise HTTPException(400, "No parsable text extracted from uploaded file")

            ingest_result = await asyncio.to_thread(
                pipeline.retriever.engine.ingest_items,
                items,
                index=target_index,
                source_type=purpose or "reference_upload",
                session_id=raw_session_id,
            )

            return {
                "status": "ok",
                "session_id": raw_session_id,
                "index": target_index,
                "file_name": original_name,
                "file_path": str(saved_path),
                "mime_type": file.content_type or "",
                "teacher_note": teacher_note,
                "parsed_docs": len(items),
                "preview_text": "\n\n".join(preview_parts)[:2400],
                "ingest": ingest_result,
            }
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(500, f"Reference upload failed: {e}")
        finally:
            file.file.close()

    # ── Courseware Generation ──

    @app.post("/v1/courseware/generate")
    async def generate_courseware(req: GenerateRequest):
        """Full pipeline: intent → plan → artifacts."""
        session_id = req.session_id or f"sess_{uuid.uuid4().hex[:12]}"

        intent = _build_intent(req)
        try:
            output_types = _parse_artifact_types(req.output_types, field_name="output_types")
        except ValueError as e:
            raise HTTPException(400, str(e))

        result = await pipeline.generate(
            intent,
            session_id=session_id,
            indexes=req.indexes,
            output_types=output_types,
        )

        return _serialize_result(result)

    # ── Streaming Outline Generation ──

    @app.post("/v1/outline/stream")
    async def stream_outline(req: StreamRequest):
        """SSE streaming outline generation."""
        session_id = req.session_id or f"sess_{uuid.uuid4().hex[:12]}"

        intent = _build_intent(req)

        async def event_stream():
            async for event in pipeline.generate_stream(
                intent, session_id=session_id, indexes=req.indexes
            ):
                data = json.dumps(event, ensure_ascii=False)
                yield f"data: {data}\n\n"

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # ── Refinement ──

    @app.post("/v1/courseware/refine")
    async def refine_courseware(req: RefineAPIRequest):
        """
        Cascade-aware refinement with natural language edit understanding.

        Automatically detects edit intent from feedback text and selects the
        optimal cascade level if the client sends the default level (2).
        """
        # Load previous result from version store
        versions = pipeline.store.list_versions(req.session_id)
        if not versions:
            raise HTTPException(404, f"No versions found for session {req.session_id}")

        latest = versions[0]
        previous_plan = None
        previous_artifacts = []

        rollback_result = pipeline.store.rollback(req.session_id, latest["version_id"])
        if rollback_result:
            previous_plan = rollback_result.plan
            previous_artifacts = rollback_result.artifacts

        if previous_plan is None:
            raise HTTPException(400, "Cannot refine: no previous plan found")

        previous = PipelineResult(
            session_id=req.session_id,
            plan=previous_plan,
            artifacts=previous_artifacts,
        )

        # Smart NL edit detection — auto-select cascade level + target types
        try:
            normalized_targets = _parse_artifact_types(req.target_types, field_name="target_types")
            cascade_level, target_types, enhanced_feedback = _parse_edit_command(
                req.feedback,
                req.cascade_level,
                [t.value for t in normalized_targets],
            )
        except ValueError as e:
            raise HTTPException(400, str(e))

        refine_req = RefineRequest(
            session_id=req.session_id,
            feedback=enhanced_feedback,
            cascade_level=cascade_level,
            target_types=target_types,
        )

        result = await pipeline.refine(refine_req, previous)
        return _serialize_result(result)

    # ── Version Management ──

    @app.get("/v1/courseware/versions/{session_id}")
    async def list_versions(session_id: str):
        """List version history for a session."""
        versions = pipeline.store.list_versions(session_id)
        return {"session_id": session_id, "versions": versions}

    @app.post("/v1/courseware/rollback")
    async def rollback_version(req: RollbackRequest):
        """Rollback to a specific version."""
        result = pipeline.store.rollback(req.session_id, req.version_id)
        if result is None:
            raise HTTPException(404, f"Version {req.version_id} not found")
        return _serialize_result(result)

    # ── Artifact Preview ──

    @app.get("/v1/artifacts/preview")
    async def preview_artifact(session_id: str, artifact_type: str):
        """Preview a generated artifact as HTML (supports pptx and docx)."""
        from fastapi.responses import HTMLResponse

        atype = ArtifactType(artifact_type)
        artifact = pipeline.store.load(session_id, atype)
        if artifact is None or not artifact.file_path:
            raise HTTPException(404, "Artifact not found")

        fpath = Path(artifact.file_path)
        if not fpath.exists():
            raise HTTPException(404, f"File not found: {artifact.file_path}")

        try:
            if atype == ArtifactType.PPTX:
                from ..ppt_preview import pptx_preview_html
                html = await asyncio.to_thread(pptx_preview_html, str(fpath))
            elif atype == ArtifactType.DOCX:
                from ..docx_preview import docx_preview_html
                html = await asyncio.to_thread(docx_preview_html, str(fpath))
            elif atype == ArtifactType.GAME_HTML:
                html = fpath.read_text(encoding="utf-8")
            else:
                raise HTTPException(400, f"Preview not supported for {artifact_type}")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(500, f"Preview generation failed: {e}")

        return HTMLResponse(content=html)

    # ── File Download ──

    @app.get("/v1/artifacts/download")
    async def download_artifact(session_id: str, artifact_type: str):
        """Download a generated artifact file."""
        atype = ArtifactType(artifact_type)
        artifact = pipeline.store.load(session_id, atype)
        if artifact is None or not artifact.file_path:
            raise HTTPException(404, "Artifact not found")

        from pathlib import Path
        path = Path(artifact.file_path)
        if not path.exists():
            raise HTTPException(404, f"File not found: {artifact.file_path}")

        return FileResponse(
            path=str(path),
            filename=path.name,
            media_type="application/octet-stream",
        )

    # ── Animation GIF Export ──

    @app.get("/v1/artifacts/export-gif")
    async def export_animation_gif(session_id: str):
        """Export the animation artifact as an animated GIF."""
        artifact = pipeline.store.load(session_id, ArtifactType.ANIMATION_HTML)
        if artifact is None or not artifact.file_path:
            raise HTTPException(404, "Animation artifact not found")

        # We need the animation data (steps) — read from metadata or re-parse
        anim_title = artifact.metadata.get("title", "知识动画")
        step_count = artifact.metadata.get("step_count", 0)

        # Reconstruct animation data from the HTML file or use fallback
        gif_path = str(Path(artifact.file_path).with_suffix(".gif"))
        try:
            from ..game.export_utils import animation_steps_to_gif

            # Try to load plan and extract animation_steps
            versions = pipeline.store.list_versions(session_id)
            anim_data = {"title": anim_title, "steps": []}
            if versions:
                rb = pipeline.store.rollback(session_id, versions[0]["version_id"])
                if rb and rb.plan and rb.plan.animation_steps:
                    anim_data = {"title": anim_title, "steps": rb.plan.animation_steps}

            if not anim_data["steps"]:
                raise HTTPException(400, "No animation steps data available for GIF export")

            await asyncio.to_thread(animation_steps_to_gif, anim_data, gif_path)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(500, f"GIF export failed: {e}")

        return FileResponse(path=gif_path, filename=Path(gif_path).name, media_type="image/gif")

    # ── Animation MP4 Export ──

    @app.get("/v1/artifacts/export-mp4")
    async def export_animation_mp4(session_id: str):
        """Export the animation artifact as an MP4 video (H.264 via FFmpeg)."""
        artifact = pipeline.store.load(session_id, ArtifactType.ANIMATION_HTML)
        if artifact is None or not artifact.file_path:
            raise HTTPException(404, "Animation artifact not found")

        anim_title = artifact.metadata.get("title", "知识动画")

        mp4_path = str(Path(artifact.file_path).with_suffix(".mp4"))
        try:
            from ..game.export_utils import animation_steps_to_mp4

            versions = pipeline.store.list_versions(session_id)
            anim_data = {"title": anim_title, "steps": []}
            if versions:
                rb = pipeline.store.rollback(session_id, versions[0]["version_id"])
                if rb and rb.plan and rb.plan.animation_steps:
                    anim_data = {"title": anim_title, "steps": rb.plan.animation_steps}

            if not anim_data["steps"]:
                raise HTTPException(400, "No animation steps data available for MP4 export")

            await asyncio.to_thread(animation_steps_to_mp4, anim_data, mp4_path)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(500, f"MP4 export failed: {e}")

        return FileResponse(path=mp4_path, filename=Path(mp4_path).name, media_type="video/mp4")

    # ── Bundle Export (ZIP) ──

    @app.get("/v1/artifacts/bundle")
    async def export_bundle(session_id: str):
        """Download all artifacts for a session as a single ZIP file."""
        artifacts_dir = Path(f"outputs/{session_id}")
        if not artifacts_dir.exists():
            raise HTTPException(404, f"No artifacts found for session {session_id}")

        try:
            from ..game.export_utils import create_export_bundle
            zip_path = await asyncio.to_thread(
                create_export_bundle, session_id, str(artifacts_dir)
            )
        except Exception as e:
            raise HTTPException(500, f"Bundle export failed: {e}")

        return FileResponse(
            path=zip_path,
            filename=Path(zip_path).name,
            media_type="application/zip",
        )

    # ── In-memory dialogue sessions ──

    _dialogue_sessions: Dict[str, DialogueManager] = {}

    # ── Chat (Multi-turn Dialogue) ──

    @app.post("/v1/chat")
    async def chat_endpoint(req: ChatRequest):
        """SSE streaming chat — multi-turn dialogue for teaching requirement collection."""
        session_id = req.session_id or f"sess_{uuid.uuid4().hex[:12]}"

        session_type = (req.session_type or "requirements").strip().lower()

        # ── Classroom multi-role QA / discussion mode ──
        if session_type in ("qa", "discussion"):
            events = await asyncio.to_thread(
                generate_role_discussion_events,
                session_id=session_id,
                message=req.message,
                messages=req.messages,
                agent_ids=req.agent_ids,
                agent_configs=req.agent_configs,
                session_type=session_type,
                discussion_topic=req.discussion_topic,
                discussion_prompt=req.discussion_prompt,
                trigger_agent_id=req.trigger_agent_id,
                user_profile=req.user_profile or {},
            )

            async def event_stream():
                for event in events:
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

            return StreamingResponse(
                event_stream(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )

        # Get or create dialogue manager for this session
        if session_id not in _dialogue_sessions:
            _dialogue_sessions[session_id] = DialogueManager(config_path=config_path)
        dm = _dialogue_sessions[session_id]

        # Process message (synchronous LLM call → run in thread)
        reply, state = await asyncio.to_thread(dm.chat, req.message)

        async def event_stream():
            # Emit the chat reply
            event_data = {
                "event": "CHAT_REPLY",
                "data": {
                    "session_id": session_id,
                    "message": reply,
                    "state": state.value,
                    "collected_info": dm.collected.to_text(),
                    "is_complete": dm.collected.is_complete(),
                    "missing_fields": dm.collected.missing_fields(),
                },
            }
            yield f"data: {json.dumps(event_data, ensure_ascii=False)}\n\n"

            # If requirements are complete, also emit collected intent
            if state in (DialogueState.READY, DialogueState.CONFIRMING):
                intent_event = {
                    "event": "INTENT_COLLECTED",
                    "data": {
                        "session_id": session_id,
                        "intent": {
                            "topic": dm.collected.topic,
                            "subject": dm.collected.subject,
                            "target_audience": dm.collected.target_audience,
                            "teaching_goal": dm.collected.teaching_goal,
                            "output_types": dm.collected.output_types,
                            "key_points": dm.collected.key_points,
                            "difficulties": dm.collected.difficulties,
                        },
                    },
                }
                yield f"data: {json.dumps(intent_event, ensure_ascii=False)}\n\n"

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.post("/v1/chat/reset")
    async def reset_chat(session_id: str):
        """Reset a chat session."""
        if session_id in _dialogue_sessions:
            _dialogue_sessions[session_id].reset()
            del _dialogue_sessions[session_id]
        return {"status": "ok", "session_id": session_id}

    # ── Video Processing (Stage D) ──

    @app.post("/v1/video/process")
    async def process_video(
        file: UploadFile = File(...),
        session_id: Optional[str] = Form(None),
    ):
        """Upload a teaching video → ASR + keyframes + VLM → RAG ingest."""
        if pipeline.retriever is None or not hasattr(pipeline.retriever, "engine"):
            raise HTTPException(400, f"{_rag_unavailable_detail()} — video processing requires RAG")

        session_id = session_id or f"vid_{uuid.uuid4().hex[:8]}"

        import tempfile
        import shutil
        from pathlib import Path as PLPath

        temp_dir = PLPath(tempfile.mkdtemp(prefix="ito_video_"))
        temp_path = temp_dir / (file.filename or "upload.mp4")

        try:
            with open(temp_path, "wb") as f:
                shutil.copyfileobj(file.file, f)

            vp = VideoPipeline(
                rag_engine=pipeline.retriever.engine,
                config_path=config_path,
            )

            result = await asyncio.to_thread(
                vp.process_cached,
                str(temp_path),
                session_id,
            )

            return {
                "status": "ok",
                "session_id": result.session_id,
                "index": result.index,
                "frames": [f.to_dict() for f in result.frames],
                "transcript_chunks": result.transcript_chunks,
                "vlm_descriptions": result.vlm_descriptions,
                "total_docs": result.total_docs,
                "processing_time_sec": round(result.processing_time_sec, 2),
            }
        except Exception as e:
            logger.error("Video processing failed: %s", e)
            raise HTTPException(500, f"Video processing failed: {e}")
        finally:
            if temp_path.exists():
                temp_path.unlink(missing_ok=True)
            if temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)

    return app


# ── Helpers ──

def _build_intent(req: GenerateRequest | StreamRequest) -> TeachingIntent:
    """Convert API request to TeachingIntent."""
    from ..domain.models import GameTypeEnum

    game_types = []
    for g in req.game_types:
        try:
            game_types.append(GameTypeEnum(g))
        except ValueError:
            pass

    # Project constraint: current knowledge base is biology-only.
    topic = (req.topic or "").strip() or "智绘生物"

    return TeachingIntent(
        topic=topic,
        subject="生物",
        target_audience=req.target_audience,
        teaching_goal=req.teaching_goal,
        grade_level=req.grade_level,
        page_range=req.page_range,
        key_focus=req.key_focus,
        difficulties=req.difficulties,
        game_types=game_types,
        special_requirements=req.special_requirements,
    )


def _serialize_result(result: PipelineResult) -> Dict[str, Any]:
    """Serialize PipelineResult for API response."""
    artifacts = []
    for a in result.artifacts:
        artifacts.append({
            "artifact_id": a.artifact_id,
            "type": a.artifact_type.value,
            "file_path": a.file_path,
            "metadata": a.metadata,
            "generation_time_sec": a.generation_time_sec,
            "error": a.error,
        })

    response: Dict[str, Any] = {
        "session_id": result.session_id,
        "version_id": result.version_id,
        "artifacts": artifacts,
        "errors": result.errors,
        "total_time_sec": result.total_time_sec,
    }

    if result.plan:
        response["plan"] = {
            "slide_count": len(result.plan.slides),
            "game_count": len(result.plan.game_specs),
            "intent": result.plan.intent.summary_text(),
        }

    return response




def _parse_artifact_types(values: Optional[List[str]], *, field_name: str) -> List[ArtifactType]:
    """Parse and validate artifact type strings with clear error messages."""
    defaults = [
        ArtifactType.PPTX,
        ArtifactType.DOCX,
        ArtifactType.GAME_HTML,
        ArtifactType.ANIMATION_HTML,
    ]
    if not values:
        return defaults

    parsed: List[ArtifactType] = []
    invalid: List[str] = []
    seen = set()
    for raw in values:
        value = str(raw or "").strip()
        if not value:
            continue
        try:
            atype = ArtifactType(value)
        except ValueError:
            invalid.append(value)
            continue
        if atype not in seen:
            seen.add(atype)
            parsed.append(atype)

    if invalid:
        allowed = ", ".join(t.value for t in defaults)
        bad = ", ".join(sorted(set(invalid)))
        raise ValueError(f"Invalid {field_name}: {bad}. Allowed values: {allowed}")

    return parsed or defaults

def _parse_edit_command(
    feedback: str,
    default_cascade: int,
    default_targets: List[str],
) -> tuple:
    """
    Parse natural language edit commands to determine optimal cascade level and targets.

    Recognizes patterns like:
    - "调换/重排第X页和第Y页" → OUTLINE_CHANGE, reorder slides
    - "简化这一页/第X页" → OUTLINE_CHANGE, simplify specific slide
    - "添加一个案例/例子" → OUTLINE_CHANGE, add case study
    - "只改教案/Word" → LOCAL_EDIT, target docx only
    - "只改PPT" → LOCAL_EDIT, target pptx only
    - "换个模板/风格" → TEMPLATE_SWAP
    - "重新生成游戏/小游戏" → LOCAL_EDIT, target game_html only

    Returns:
        (cascade_level, target_types, enhanced_feedback)
    """
    import re

    text = feedback.strip()
    cascade = CascadeLevel(default_cascade)
    targets = [ArtifactType(t) for t in default_targets]
    enhanced = feedback

    # ── Pattern: reorder / swap pages ──
    reorder_patterns = [
        r'(?:调换|交换|对调|互换|重排|调整顺序).*?第?\s*(\d+).*?第?\s*(\d+)',
        r'(?:把|将).*?第?\s*(\d+).*?(?:移到|放到|换到).*?第?\s*(\d+)',
    ]
    for pat in reorder_patterns:
        m = re.search(pat, text)
        if m:
            cascade = CascadeLevel.OUTLINE_CHANGE
            enhanced = f"请将第{m.group(1)}页和第{m.group(2)}页的顺序对调。{feedback}"
            break

    # ── Pattern: simplify specific page ──
    simplify_match = re.search(r'(?:简化|精简|缩减|删减).*?第?\s*(\d+)\s*页', text)
    if simplify_match:
        cascade = CascadeLevel.OUTLINE_CHANGE
        enhanced = f"请简化第{simplify_match.group(1)}页的内容，减少文字量使其更精炼。{feedback}"

    # ── Pattern: add case / example ──
    if re.search(r'(?:添加|加入|增加|补充).*?(?:案例|例子|实例|情境|场景)', text):
        cascade = CascadeLevel.OUTLINE_CHANGE

    # ── Pattern: target-specific edits ──
    if re.search(r'(?:只|仅|单独).*?(?:改|修改|更新|重新生成).*?(?:教案|Word|word|docx)', text):
        cascade = CascadeLevel.LOCAL_EDIT
        targets = [ArtifactType.DOCX]
    elif re.search(r'(?:只|仅|单独).*?(?:改|修改|更新|重新生成).*?(?:PPT|ppt|课件|幻灯片)', text):
        cascade = CascadeLevel.LOCAL_EDIT
        targets = [ArtifactType.PPTX]
    elif re.search(r'(?:只|仅|单独|重新).*?(?:生成|改|修改).*?(?:游戏|小游戏|互动)', text):
        cascade = CascadeLevel.LOCAL_EDIT
        targets = [ArtifactType.GAME_HTML]
    elif re.search(r'(?:只|仅|单独|重新).*?(?:生成|改|修改).*?(?:动画)', text):
        cascade = CascadeLevel.LOCAL_EDIT
        targets = [ArtifactType.ANIMATION_HTML]

    # ── Pattern: template / style swap ──
    if re.search(r'(?:换|更换|替换).*?(?:模板|风格|样式|主题)', text):
        cascade = CascadeLevel.TEMPLATE_SWAP

    return cascade, targets, enhanced


def _safe_path_component(raw: str) -> str:
    """Sanitize user-provided path components for local filesystem use."""
    cleaned = "".join(ch for ch in raw if ch.isalnum() or ch in ("-", "_"))
    return cleaned or "session"


