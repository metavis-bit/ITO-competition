"""
Artifact version store - implements ArtifactStore protocol using SQLite + filesystem.

Runtime generators may emit files under outputs/{session_id}. This store creates
version-scoped snapshots under outputs/{session_id}/versions/{version_id}/... and
all preview/download/export operations should read from those snapshots.
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

_VERSION_SUBDIRS = {
    ArtifactType.PPTX: "ppt",
    ArtifactType.DOCX: "docx",
    ArtifactType.GAME_HTML: "games",
    ArtifactType.ANIMATION_HTML: "animations",
}


class SQLiteArtifactStore:
    """
    Implements ArtifactStore protocol.

    - save(): validates artifact output and leaves placement to snapshotting
    - load(): retrieves artifact metadata from DB
    - list_versions(): returns version history for a session
    - rollback(): restores session to a previous version
    - create_snapshot(): copies current run artifacts into a version-scoped directory
    """

    def __init__(self, store_dir: str = "./rag_store", output_dir: str = "./outputs"):
        self.store_dir = Path(store_dir)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def save(self, session_id: str, artifact: GeneratedArtifact) -> str:
        """
        Validate artifact output.

        The authoritative persisted location is created in create_snapshot(), where a
        concrete version_id is available.
        """
        src = Path(artifact.file_path)
        if not src.exists():
            logger.warning("Artifact file not found: %s", src)
            return artifact.file_path
        return artifact.file_path

    def load(
        self,
        session_id: str,
        artifact_type: ArtifactType,
        version: Optional[int] = None,
        version_id: Optional[str] = None,
    ) -> Optional[GeneratedArtifact]:
        """Load artifact metadata from DB. If version_id/version=None, returns latest."""
        ver = self._resolve_version(session_id, version=version, version_id=version_id)
        if ver is None:
            return None

        artifact = self._artifact_from_version(ver, artifact_type)
        if artifact is None:
            return None
        return artifact

    def load_snapshot(
        self,
        session_id: str,
        *,
        version: Optional[int] = None,
        version_id: Optional[str] = None,
    ) -> Optional[PipelineResult]:
        """Load a version snapshot without mutating live session state."""
        ver = self._resolve_version(session_id, version=version, version_id=version_id)
        if ver is None:
            return None

        plan = None
        if ver.plan_json_snapshot:
            try:
                plan = CoursewarePlan.model_validate(ver.plan_json_snapshot)
            except Exception:
                logger.warning("Failed to restore plan from snapshot %s", ver.version_id, exc_info=True)

        artifacts: List[GeneratedArtifact] = []
        for atype in ArtifactType:
            artifact = self._artifact_from_version(ver, atype)
            if artifact is not None:
                artifacts.append(artifact)

        return PipelineResult(
            session_id=session_id,
            plan=plan,
            artifacts=artifacts,
            version_id=ver.version_id,
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
                    "description": v.version_note,
                    "created_at": v.created_at.isoformat() if v.created_at else None,
                    "has_ppt": bool(v.ppt_path_snapshot),
                    "has_docx": bool(v.lesson_plan_path_snapshot),
                    "has_games": bool(v.game_paths_snapshot),
                    "has_animation": bool(v.animation_path_snapshot),
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
        version_dir = self._version_dir(session_id, version_id)

        snapshot_paths = {
            ArtifactType.PPTX: None,
            ArtifactType.DOCX: None,
            ArtifactType.GAME_HTML: [],
            ArtifactType.ANIMATION_HTML: None,
        }

        for artifact in artifacts:
            copied = self._copy_artifact_into_version(session_id, version_id, artifact)
            artifact.metadata["version_id"] = version_id

            if artifact.artifact_type == ArtifactType.PPTX:
                snapshot_paths[ArtifactType.PPTX] = copied[0] if copied else None
                if copied:
                    artifact.file_path = copied[0]
            elif artifact.artifact_type == ArtifactType.DOCX:
                snapshot_paths[ArtifactType.DOCX] = copied[0] if copied else None
                if copied:
                    artifact.file_path = copied[0]
            elif artifact.artifact_type == ArtifactType.GAME_HTML:
                snapshot_paths[ArtifactType.GAME_HTML] = copied
                if copied:
                    artifact.file_path = copied[0]
                    artifact.metadata["all_paths"] = copied
            elif artifact.artifact_type == ArtifactType.ANIMATION_HTML:
                snapshot_paths[ArtifactType.ANIMATION_HTML] = copied[0] if copied else None
                if copied:
                    artifact.file_path = copied[0]

        with get_db() as db:
            ctx = db.query(SessionContext).filter_by(session_id=session_id).first()
            if ctx is None:
                ctx = SessionContext(session_id=session_id)
                db.add(ctx)
                db.flush()

            if plan:
                ctx.outline_str = plan.raw_llm_output or json.dumps(
                    [s.model_dump() for s in plan.slides], ensure_ascii=False
                )
                ctx.total_pages = len(plan.slides)
                ctx.extracted_slots = plan.intent.to_extracted_slots()

            ctx.ppt_path = (
                str(snapshot_paths[ArtifactType.PPTX])
                if snapshot_paths[ArtifactType.PPTX]
                else None
            )
            ctx.lesson_plan_path = (
                str(snapshot_paths[ArtifactType.DOCX])
                if snapshot_paths[ArtifactType.DOCX]
                else None
            )
            ctx.game_paths = [str(path) for path in snapshot_paths[ArtifactType.GAME_HTML]]
            ctx.animation_path = (
                str(snapshot_paths[ArtifactType.ANIMATION_HTML])
                if snapshot_paths[ArtifactType.ANIMATION_HTML]
                else None
            )

            ver = CoursewareVersion(
                version_id=version_id,
                session_id=session_id,
                version_note=version_note,
                outline_snapshot=ctx.outline_str,
                plan_snapshot=ctx.lesson_plan_str,
                lesson_plan_path_snapshot=ctx.lesson_plan_path,
                ppt_path_snapshot=ctx.ppt_path,
                game_paths_snapshot=ctx.game_paths,
                animation_path_snapshot=ctx.animation_path,
                plan_json_snapshot=plan.model_dump() if plan else None,
            )
            db.add(ver)

        logger.info(
            "Created snapshot %s for session %s in %s",
            version_id,
            session_id,
            version_dir,
        )
        return version_id

    def rollback(self, session_id: str, target_version_id: str) -> Optional[PipelineResult]:
        """
        Roll back session to a specific version.

        Restores all live assets on SessionContext from the target version snapshot.
        Returns PipelineResult with the restored artifacts.
        """
        snapshot = self.load_snapshot(session_id, version_id=target_version_id)
        if snapshot is None:
            logger.warning("Version %s not found for session %s", target_version_id, session_id)
            return None

        with get_db() as db:
            ver = (
                db.query(CoursewareVersion)
                .filter_by(version_id=target_version_id, session_id=session_id)
                .first()
            )
            ctx = db.query(SessionContext).filter_by(session_id=session_id).first()
            if ver is None or ctx is None:
                return None

            ctx.outline_str = ver.outline_snapshot
            ctx.lesson_plan_str = ver.plan_snapshot
            ctx.lesson_plan_path = ver.lesson_plan_path_snapshot
            ctx.ppt_path = ver.ppt_path_snapshot
            ctx.game_paths = ver.game_paths_snapshot or []
            ctx.animation_path = ver.animation_path_snapshot

        return snapshot

    def _resolve_version(
        self,
        session_id: str,
        *,
        version: Optional[int] = None,
        version_id: Optional[str] = None,
    ) -> Optional[CoursewareVersion]:
        with get_db() as db:
            query = (
                db.query(CoursewareVersion)
                .filter_by(session_id=session_id)
                .order_by(CoursewareVersion.created_at.desc())
            )
            if version_id:
                return query.filter_by(version_id=version_id).first()
            if version is not None:
                versions = query.all()
                if version >= len(versions):
                    return None
                return versions[version]
            return query.first()

    def _artifact_from_version(
        self,
        ver: CoursewareVersion,
        artifact_type: ArtifactType,
    ) -> Optional[GeneratedArtifact]:
        path: Optional[str] = None
        metadata: Dict[str, Any] = {
            "version_id": ver.version_id,
            "version_note": ver.version_note,
        }

        if artifact_type == ArtifactType.PPTX:
            path = ver.ppt_path_snapshot
        elif artifact_type == ArtifactType.DOCX:
            path = ver.lesson_plan_path_snapshot
        elif artifact_type == ArtifactType.GAME_HTML:
            paths = ver.game_paths_snapshot or []
            path = paths[0] if paths else None
            metadata["all_paths"] = paths
        elif artifact_type == ArtifactType.ANIMATION_HTML:
            path = ver.animation_path_snapshot

        if path is None:
            return None

        fpath = Path(path)
        if artifact_type == ArtifactType.ANIMATION_HTML:
            metadata.update(self._read_animation_metadata(fpath))

        return GeneratedArtifact(
            artifact_type=artifact_type,
            file_path=path,
            metadata=metadata,
        )

    def _copy_artifact_into_version(
        self,
        session_id: str,
        version_id: str,
        artifact: GeneratedArtifact,
    ) -> List[str]:
        source_paths = self._source_paths_for_artifact(artifact)
        if not source_paths:
            return []

        target_dir = self._version_dir(session_id, version_id) / _VERSION_SUBDIRS[artifact.artifact_type]
        target_dir.mkdir(parents=True, exist_ok=True)

        copied_paths: List[str] = []
        for src in source_paths:
            src_path = Path(src)
            if not src_path.exists():
                logger.warning("Skipping missing artifact source for snapshot: %s", src_path)
                continue
            dst_path = target_dir / src_path.name
            if src_path.resolve() != dst_path.resolve():
                shutil.copy2(src_path, dst_path)
            copied_paths.append(str(dst_path))
        return copied_paths

    def _source_paths_for_artifact(self, artifact: GeneratedArtifact) -> List[str]:
        if artifact.artifact_type == ArtifactType.GAME_HTML:
            raw_paths = artifact.metadata.get("all_paths")
            if isinstance(raw_paths, list):
                unique = []
                seen = set()
                for item in raw_paths:
                    value = str(item or "").strip()
                    if not value or value in seen:
                        continue
                    seen.add(value)
                    unique.append(value)
                if unique:
                    return unique
        return [artifact.file_path] if artifact.file_path else []

    def _version_dir(self, session_id: str, version_id: str) -> Path:
        return self.output_dir / session_id / "versions" / version_id

    @staticmethod
    def _read_animation_metadata(path: Path) -> Dict[str, Any]:
        metadata: Dict[str, Any] = {}
        if not path.exists():
            return metadata
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return metadata

        title_marker = "const animationTitle = "
        steps_marker = "const animationSteps = "

        title_index = text.find(title_marker)
        if title_index >= 0:
            start = title_index + len(title_marker)
            end = text.find(";", start)
            if end > start:
                try:
                    metadata["title"] = json.loads(text[start:end].strip())
                except Exception:
                    pass

        steps_index = text.find(steps_marker)
        if steps_index >= 0:
            start = steps_index + len(steps_marker)
            end = text.find(";", start)
            if end > start:
                try:
                    steps = json.loads(text[start:end].strip())
                    if isinstance(steps, list):
                        metadata["step_count"] = len(steps)
                except Exception:
                    pass

        return metadata
