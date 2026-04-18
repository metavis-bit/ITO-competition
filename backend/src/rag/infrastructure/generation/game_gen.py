"""
Game HTML generator wrapper — implements ArtifactGenerator protocol.

Wraps wym's existing GameEngine, adapting CoursewarePlan.game_specs → game generation.
"""
from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional

from ...domain.models import ArtifactType, CoursewarePlan, GeneratedArtifact
from ..llm import LLMRouter

logger = logging.getLogger("game_gen")

# Shared thread pool for parallel game LLM calls
_game_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="game-gen")


class GameHTMLGenerator:
    """
    Wraps existing src/rag/game/game_engine.py GameEngine.

    Generates one HTML file per game spec in CoursewarePlan.game_specs.
    Returns the first game as the primary artifact; additional games
    are listed in metadata.

    Multiple game specs are generated **in parallel** via a thread pool
    to avoid sequential LLM call latency.
    """

    def __init__(self, config_path: str = "config.yaml", llm: Optional[LLMRouter] = None):
        self.config_path = config_path
        self._engine = None
        self._llm = llm

    @property
    def engine(self):
        if self._engine is None:
            from ...game.game_engine import GameEngine
            self._engine = GameEngine(self.config_path, llm_router=self._llm)
        return self._engine

    def artifact_type(self) -> ArtifactType:
        return ArtifactType.GAME_HTML

    def _generate_single(self, spec: Dict[str, Any], topic: str, context: str, game_dir: str) -> Dict[str, Any]:
        """Generate a single game from spec (runs in thread pool)."""
        game_type = spec.get("type", "quiz")
        game_topic = spec.get("topic", topic)
        teacher_req = spec.get("teacher_requirement", "")
        count = spec.get("count", 5)

        try:
            result = self.engine.generate(
                knowledge_topic=game_topic,
                game_type=game_type,
                teacher_requirement=teacher_req,
                count=count,
                context=context,
                output_dir=game_dir,
            )
            if result.get("html_path"):
                logger.info("Game generated: %s → %s", game_type, result["html_path"])
            return result
        except Exception as e:
            logger.error("Game generation failed for type=%s: %s", game_type, e)
            return {"error": str(e), "game_type": game_type}

    def generate(self, plan: CoursewarePlan, output_dir: str) -> GeneratedArtifact:
        """
        Generate interactive game HTML files from CoursewarePlan.game_specs.

        If no game_specs exist, generates a default quiz based on the topic.
        Multiple specs are generated in parallel for faster completion.
        """
        t0 = time.time()
        game_dir = str(Path(output_dir) / "games")
        Path(game_dir).mkdir(parents=True, exist_ok=True)

        topic = plan.intent.topic or plan.intent.chapter or "教学内容"
        context = plan.rag_context or ""

        game_specs = plan.game_specs
        if not game_specs:
            game_specs = [{"type": "quiz", "topic": topic, "questions": []}]

        # Parallel generation: submit all specs to thread pool
        if len(game_specs) == 1:
            all_results = [self._generate_single(game_specs[0], topic, context, game_dir)]
        else:
            futures = [
                _game_pool.submit(self._generate_single, spec, topic, context, game_dir)
                for spec in game_specs
            ]
            all_results = [f.result() for f in futures]

        all_paths: List[str] = [
            r["html_path"] for r in all_results if r.get("html_path")
        ]

        primary_path = all_paths[0] if all_paths else ""

        return GeneratedArtifact(
            artifact_type=ArtifactType.GAME_HTML,
            file_path=primary_path,
            metadata={
                "game_count": len(all_paths),
                "all_paths": all_paths,
                "game_types": [s.get("type", "quiz") for s in game_specs],
            },
            generation_time_sec=time.time() - t0,
            error=None if all_paths else "No games generated successfully",
        )
