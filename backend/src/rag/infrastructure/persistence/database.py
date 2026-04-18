"""
SQLAlchemy session management — ported and cleaned from main/tools/database.py.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from .sql_models import Base

_DB_DIR = Path("./rag_store")
_DB_DIR.mkdir(parents=True, exist_ok=True)
SQLALCHEMY_DATABASE_URL = f"sqlite:///{_DB_DIR / 'courseware_agent.db'}"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    expire_on_commit=False,
)


def init_db() -> None:
    """Create all tables if they don't exist."""
    Base.metadata.create_all(bind=engine)
    _migrate_sqlite_schema()


@contextmanager
def get_db() -> Generator[Session, None, None]:
    """
    Context manager for database sessions.

    Usage:
        with get_db() as db:
            db.query(SessionContext).filter_by(session_id=sid).first()
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _migrate_sqlite_schema() -> None:
    """Apply lightweight additive migrations for existing SQLite databases."""
    required_columns = {
        "session_context": {
            "animation_path": "TEXT",
        },
        "courseware_version": {
            "animation_path_snapshot": "TEXT",
        },
    }

    with engine.begin() as conn:
        for table_name, columns in required_columns.items():
            existing = {
                row[1]
                for row in conn.exec_driver_sql(f"PRAGMA table_info({table_name})").fetchall()
            }
            for column_name, column_type in columns.items():
                if column_name in existing:
                    continue
                conn.exec_driver_sql(
                    f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"
                )
