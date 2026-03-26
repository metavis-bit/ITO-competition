"""
Application bootstrap 鈥?wires all dependencies.

This is the ONLY file that knows concrete implementations.
Everything else depends on Protocol contracts.

Usage:
    from src.rag.bootstrap import create_pipeline, create_app

    # For direct use:
    pipeline = create_pipeline("config.yaml")
    result = await pipeline.generate(intent, session_id="sess_001")

    # For FastAPI:
    app = create_app("config.yaml")
"""
from __future__ import annotations

import logging
from typing import Optional

from .config import load_config
from .infrastructure.cache import EmbeddingCache
from .infrastructure.generation import AnimationHTMLGenerator, DOCXGenerator, GameHTMLGenerator, PPTXGenerator
from .infrastructure.llm import LLMRouter
from .infrastructure.persistence.database import init_db
from .infrastructure.persistence.version_store import SQLiteArtifactStore
from .infrastructure.retrieval import RetrievalPipeline
from .services.pipeline_orchestrator import PipelineOrchestrator
from .services.schema_normalizer import SchemaNormalizer

logger = logging.getLogger("bootstrap")


def create_pipeline(
    config_path: str = "config.yaml",
    *,
    skip_rag: bool = False,
) -> PipelineOrchestrator:
    """
    Wire all dependencies and return a fully configured PipelineOrchestrator.

    Args:
        config_path: Path to config.yaml.
        skip_rag: If True, skip RAG engine initialization (faster startup for testing).

    Returns:
        Ready-to-use PipelineOrchestrator instance.
    """
    cfg = load_config(config_path)
    logger.info("Bootstrapping pipeline from %s", config_path)

    # 鈹€鈹€ Initialize database 鈹€鈹€
    init_db()

    # 鈹€鈹€ LLM Router 鈹€鈹€
    generator_cfg = cfg.get("generator", {}) or {}
    llm = LLMRouter(generator_cfg)
    logger.info("LLM Router initialized (model: %s)", generator_cfg.get("api_model", "default"))

    # 鈹€鈹€ Embedding Cache 鈹€鈹€
    cache_dir = cfg.get("cache_dir", "./rag_store/cache")
    embedding_cache = EmbeddingCache(cache_dir)
    logger.info("Embedding cache loaded (%d entries)", embedding_cache.size)

    # 鈹€鈹€ RAG Engine + Retrieval Pipeline 鈹€鈹€
    retriever: Optional[RetrievalPipeline] = None
    rag_init_error: Optional[str] = None
    if not skip_rag:
        try:
            from .rag_engine import RAGEngine
            engine = RAGEngine(config_path)
            retriever = RetrievalPipeline(rag_engine=engine)
            logger.info("RAG engine + retrieval pipeline initialized")

            # Auto-bootstrap: ingest knowledge_base/ on first startup
            _auto_ingest_kb(engine)
        except Exception as e:
            rag_init_error = str(e)
            logger.warning("RAG engine init failed (continuing without RAG): %s", e)

    # 鈹€鈹€ Schema Normalizer 鈹€鈹€
    normalizer = SchemaNormalizer()

    # 鈹€鈹€ Generators 鈹€鈹€
    pptx_gen = PPTXGenerator(config_path)
    docx_gen = DOCXGenerator(config_path)
    game_gen = GameHTMLGenerator(config_path)
    animation_gen = AnimationHTMLGenerator(config_path)
    generators = [pptx_gen, docx_gen, game_gen, animation_gen]

    # 鈹€鈹€ Artifact Store 鈹€鈹€
    store_dir = cfg.get("store_dir", "./rag_store")
    store = SQLiteArtifactStore(store_dir=store_dir)

    # 鈹€鈹€ Assemble Pipeline 鈹€鈹€
    pipeline = PipelineOrchestrator(
        llm=llm,
        retriever=retriever,
        normalizer=normalizer,
        generators=generators,
        store=store,
        embedding_cache=embedding_cache,
    )
    # Attach startup diagnostics so API can expose exact RAG init failures.
    pipeline.rag_init_error = rag_init_error

    logger.info("Pipeline bootstrap complete (generators: %s)", [g.artifact_type().value for g in generators])
    return pipeline


def _auto_ingest_kb(engine) -> None:
    """
    Auto-ingest knowledge_base/ directory 鈥?with change detection.

    Computes a fingerprint (file names + sizes + mtimes) of all files in
    knowledge_base/. Compares against the stored fingerprint from the last
    successful ingestion. Re-ingests only when:
      - First run (no marker file)
      - Files added, removed, or modified since last ingestion

    On change: resets the 'kb' index and performs a full re-ingestion to
    ensure the vector store is consistent with the current file set.
    """
    import hashlib
    from pathlib import Path

    kb_dir = Path("knowledge_base")
    marker = Path("rag_store/.kb_fingerprint")

    if not kb_dir.exists() or not any(kb_dir.iterdir()):
        logger.info("No knowledge_base/ directory or empty, skipping auto-ingest")
        return

    # Build fingerprint from current file set
    current_fingerprint = _compute_kb_fingerprint(kb_dir)
    file_count = sum(1 for f in kb_dir.rglob("*") if f.is_file())

    # Compare with stored fingerprint
    if marker.exists():
        stored_fingerprint = marker.read_text(encoding="utf-8").strip()
        if stored_fingerprint == current_fingerprint:
            logger.info(
                "Knowledge base unchanged (%d files, fingerprint match), skipping",
                file_count,
            )
            return
        logger.info(
            "Knowledge base changed (fingerprint mismatch), re-ingesting %d files",
            file_count,
        )
        # Reset the kb index to remove stale entries
        try:
            engine.reset_index("kb")
            logger.info("Reset 'kb' index for clean re-ingestion")
        except Exception as e:
            logger.warning("Failed to reset 'kb' index: %s (proceeding anyway)", e)
    else:
        logger.info("First startup 鈥?ingesting knowledge base: %d files", file_count)

    try:
        result = engine.ingest_knowledge_base(
            str(kb_dir), index="kb", session_id="kb"
        )
        logger.info(
            "Knowledge base ingestion complete: %d items, %d chunks",
            result.get("items", 0),
            result.get("chunks", 0),
        )

        # Write fingerprint marker
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(current_fingerprint, encoding="utf-8")
    except Exception as e:
        logger.error("Knowledge base auto-ingest failed: %s", e)
        # Don't write marker 鈥?will retry on next startup


def _compute_kb_fingerprint(kb_dir) -> str:
    """
    Compute a deterministic fingerprint of all files in a directory.

    Uses sorted (relative_path, file_size, mtime_ns) tuples hashed with SHA-256.
    Any file addition, deletion, rename, or content change will alter the fingerprint.
    """
    import hashlib
    from pathlib import Path

    entries = []
    for f in sorted(kb_dir.rglob("*")):
        if f.is_file():
            stat = f.stat()
            rel = f.relative_to(kb_dir)
            entries.append(f"{rel}|{stat.st_size}|{stat.st_mtime_ns}")

    raw = "\n".join(entries)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def create_app(config_path: str = "config.yaml"):
    """
    Create a fully wired FastAPI application.

    Returns:
        FastAPI app instance with all routes registered.
    """
    from .api.server import create_fastapi_app
    pipeline = create_pipeline(config_path)
    return create_fastapi_app(pipeline, config_path=config_path)


