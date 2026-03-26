"""
Artifact version store — implements ArtifactStore protocol using SQLite + filesystem.

Artifacts saved to: outputs/{session_id}/{version_id}/{artifact_type}.ext
Metadata tracked in CoursewareVersion table.
"""
from __future__ import annotations

import json
import logging
import shutil
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from ...domain.models import (
    ArtifactType,
    CoursewarePlan,
    GeneratedArtifact,
    PipelineResult,
)
from .database import get_db
from .sql_models import CoursewareVersion, SessionContext

logger = logging.getLogger("version_store")

# File extension mapping
_EXT_MAP = {
    ArtifactType.PPTX: ".pptx",
    ArtifactType.DOCX: ".docx",
    ArtifactType.GAME_HTML: ".html",
    ArtifactType.ANIMATION_HTML: ".html",
}


class SQLiteArtifactStore:
    """
    Implements ArtifactStore protocol.

    - save(): copies artifact file to versioned directory, records snapshot in DB
    - load(): retrieves artifact metadata from DB
    - list_versions(): returns version history for a session
    - rollback(): restores session to a previous version
    - create_snapshot(): creates a full version snapshot from current state
    """

    def __init__(self, store_dir: str = "./rag_store", output_dir: str = "./outputs"):
        self.store_dir = Path(store_dir)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def save(self, session_id: str, artifact: GeneratedArtifact) -> str:
        """
        Save an artifact to the versioned file structure.

        Returns:
            The path where the artifact was saved.
        """
        session_dir = self.output_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)

        src = Path(artifact.file_path)
        if not src.exists():
            logger.warning("Artifact file not found: %s", src)
            return artifact.file_path

        # Copy to session output directory
        dst = session_dir / src.name
        if src != dst:
            shutil.copy2(src, dst)

        artifact.file_path = str(dst)
        return str(dst)

    def load(
        self,
        session_id: str,
        artifact_type: ArtifactType,
        version: Optional[int] = None,
    ) -> Optional[GeneratedArtifact]:
        """Load artifact metadata from DB. If version=None, returns latest."""
        with get_db() as db:
            query = (
                db.query(CoursewareVersion)
                .filter_by(session_id=session_id)
                .order_by(CoursewareVersion.created_at.desc())
            )
            if version is not None:
                versions = query.all()
                if version >= len(versions):
                    return None
                ver = versions[version]
            else:
                ver = query.first()

            if ver is None:
                return None

            # Map artifact type to stored path
            path = None
            if artifact_type == ArtifactType.PPTX:
                path = ver.ppt_path_snapshot
            elif artifact_type == ArtifactType.DOCX:
                path = ver.lesson_plan_path_snapshot
            elif artifact_type == ArtifactType.GAME_HTML:
                paths = ver.game_paths_snapshot or []
                path = paths[0] if paths else None

            if path is None:
                return None

            return GeneratedArtifact(
                artifact_type=artifact_type,
                file_path=path,
                metadata={"version_id": ver.version_id, "version_note": ver.version_note},
            )

    def list_versions(self, session_id: str) -> List[Dict[str, Any]]:
        """List all versions for a session, newest first."""
        with get_db() as db:
            versions = (
                db.query(CoursewareVersion)
                .filter_by(session_id=session_id)
                .order_by(CoursewareVersion.created_at.desc())
                .all()
            )
            return [
                {
                    "version_id": v.version_id,
                    "version_note": v.version_note,
                    "created_at": v.created_at.isoformat() if v.created_at else None,
                    "has_ppt": bool(v.ppt_path_snapshot),
                    "has_docx": bool(v.lesson_plan_path_snapshot),
                    "has_games": bool(v.game_paths_snapshot),
                }
                for v in versions
            ]

    def create_snapshot(
        self,
        session_id: str,
        version_note: str,
        plan: Optional[CoursewarePlan] = None,
        artifacts: Optional[List[GeneratedArtifact]] = None,
    ) -> str:
        """
        Create a full version snapshot from current state.

        Returns:
            version_id of the new snapshot.
        """
        version_id = f"ver_{uuid.uuid4().hex[:8]}"
        artifacts = artifacts or []

        ppt_path = None
        docx_path = None
        game_paths = []

        for a in artifacts:
            if a.artifact_type == ArtifactType.PPTX:
                ppt_path = a.file_path
            elif a.artifact_type == ArtifactType.DOCX:
                docx_path = a.file_path
            elif a.artifact_type == ArtifactType.GAME_HTML:
                game_paths.append(a.file_path)

        with get_db() as db:
            # Ensure session exists
            ctx = db.query(SessionContext).filter_by(session_id=session_id).first()
            if ctx is None:
                ctx = SessionContext(session_id=session_id)
                db.add(ctx)
                db.flush()

            # Update live assets on session context
            if ppt_path:
                ctx.ppt_path = ppt_path
            if docx_path:
                ctx.lesson_plan_path = docx_path
            if game_paths:
                ctx.game_paths = game_paths
            if plan:
                ctx.outline_str = plan.raw_llm_output or json.dumps(
                    [s.model_dump() for s in plan.slides], ensure_ascii=False
                )
                ctx.total_pages = len(plan.slides)
                ctx.extracted_slots = plan.intent.to_extracted_slots()

            # Create version snapshot
            ver = CoursewareVersion(
                version_id=version_id,
                session_id=session_id,
                version_note=version_note,
                outline_snapshot=ctx.outline_str,
                plan_snapshot=ctx.lesson_plan_str,
                lesson_plan_path_snapshot=ctx.lesson_plan_path,
                ppt_path_snapshot=ctx.ppt_path,
                game_paths_snapshot=ctx.game_paths,
                plan_json_snapshot=plan.model_dump() if plan else None,
            )
            db.add(ver)

        logger.info("Created snapshot %s for session %s: %s", version_id, session_id, version_note)
        return version_id

    def rollback(self, session_id: str, target_version_id: str) -> Optional[PipelineResult]:
        """
        Rollback session to a specific version.

        Restores all live assets on SessionContext from the target version snapshot.
        Returns PipelineResult with the restored artifacts.
        """
        with get_db() as db:
            ver = (
                db.query(CoursewareVersion)
                .filter_by(version_id=target_version_id, session_id=session_id)
                .first()
            )
            if ver is None:
                logger.warning("Version %s not found for session %s", target_version_id, session_id)
                return None

            ctx = db.query(SessionContext).filter_by(session_id=session_id).first()
            if ctx is None:
                return None

            # Restore live assets from snapshot
            ctx.outline_str = ver.outline_snapshot
            ctx.lesson_plan_str = ver.plan_snapshot
            ctx.lesson_plan_path = ver.lesson_plan_path_snapshot
            ctx.ppt_path = ver.ppt_path_snapshot
            ctx.game_paths = ver.game_paths_snapshot or []

        # Build result
        artifacts = []
        if ver.ppt_path_snapshot:
            artifacts.append(GeneratedArtifact(
                artifact_type=ArtifactType.PPTX,
                file_path=ver.ppt_path_snapshot,
            ))
        if ver.lesson_plan_path_snapshot:
            artifacts.append(GeneratedArtifact(
                artifact_type=ArtifactType.DOCX,
                file_path=ver.lesson_plan_path_snapshot,
            ))
        for gp in (ver.game_paths_snapshot or []):
            artifacts.append(GeneratedArtifact(
                artifact_type=ArtifactType.GAME_HTML,
                file_path=gp,
            ))

        # Restore plan if available
        plan = None
        if ver.plan_json_snapshot:
            try:
                plan = CoursewarePlan.model_validate(ver.plan_json_snapshot)
            except Exception:
                logger.warning("Failed to restore plan from snapshot")

        return PipelineResult(
            session_id=session_id,
            plan=plan,
            artifacts=artifacts,
            version_id=target_version_id,
        )
