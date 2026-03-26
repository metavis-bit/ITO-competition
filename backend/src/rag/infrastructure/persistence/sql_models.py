"""
ORM models — ported from main/tools/SQL.py with field naming aligned to domain models.

Tables:
  - session_history:    chat interaction log
  - session_context:    current teaching task state (live assets)
  - courseware_version:  point-in-time snapshots (time machine)
  - temp_image:         image asset gallery per session
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class SessionHistory(Base):
    """Chat interaction log — records human-agent conversation."""

    __tablename__ = "session_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(50), index=True)
    role = Column(String(20))  # "user" | "assistant"
    content = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow)


class SessionContext(Base):
    """
    Current teaching task state — stores live assets and extracted teaching elements.

    This is the single row per session that holds the latest state.
    """

    __tablename__ = "session_context"

    session_id = Column(
        String(50),
        primary_key=True,
        default=lambda: f"sess_{uuid.uuid4().hex[:12]}",
    )
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Teaching elements (extracted intent as JSON)
    extracted_slots = Column(JSON, nullable=True, default=dict)

    # ── Live assets ──
    outline_str = Column(Text, nullable=True)          # current outline text
    total_pages = Column(Integer, default=0)
    lesson_plan_str = Column(Text, nullable=True)       # current lesson plan text
    lesson_plan_path = Column(Text, nullable=True)      # Word file path
    ppt_path = Column(Text, nullable=True)              # PPT file path
    game_paths = Column(JSON, nullable=True, default=list)  # list of game HTML paths

    # Image placement state
    is_image_placement_deferred = Column(Boolean, default=False)

    # Relationships
    images = relationship(
        "TempImage", back_populates="session", cascade="all, delete-orphan"
    )
    versions = relationship(
        "CoursewareVersion",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="CoursewareVersion.created_at.desc()",
    )


class CoursewareVersion(Base):
    """
    Point-in-time snapshot — enables version rollback.

    Each modification creates a new version with full asset snapshots.
    """

    __tablename__ = "courseware_version"

    version_id = Column(
        String(50),
        primary_key=True,
        default=lambda: f"ver_{uuid.uuid4().hex[:8]}",
    )
    session_id = Column(
        String(50), ForeignKey("session_context.session_id")
    )
    version_note = Column(String(255))

    # ── Asset snapshots ──
    outline_snapshot = Column(Text, nullable=True)
    plan_snapshot = Column(Text, nullable=True)
    lesson_plan_path_snapshot = Column(Text, nullable=True)
    ppt_path_snapshot = Column(Text, nullable=True)
    game_paths_snapshot = Column(JSON, nullable=True, default=list)
    image_layout_snapshot = Column(JSON, nullable=True)

    # Plan JSON snapshot (for re-generation)
    plan_json_snapshot = Column(JSON, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    session = relationship("SessionContext", back_populates="versions")


class TempImage(Base):
    """Image asset gallery — tracks generated/uploaded images per session."""

    __tablename__ = "temp_image"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(
        String(50), ForeignKey("session_context.session_id"), index=True
    )
    image_id = Column(String(50), index=True)
    url = Column(Text)
    image_prompt = Column(Text)
    target = Column(Integer, default=1)  # 1=active, 0=discarded
    target_page = Column(Integer, nullable=True)
    position_code = Column(String(20), nullable=True)  # e.g. "p3_2"
    created_at = Column(DateTime, default=datetime.utcnow)

    session = relationship("SessionContext", back_populates="images")
