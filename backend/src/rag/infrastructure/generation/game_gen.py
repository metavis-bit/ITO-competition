"""
Game HTML generator wrapper — implements ArtifactGenerator protocol.

Wraps wym's existing GameEngine, adapting CoursewarePlan.game_specs → game generation.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Dict, List

from ...domain.models import ArtifactType, CoursewarePlan, GeneratedArtifact

logger = logging.getLogger("game_gen")


class GameHTMLGenerator:
    """
    Wraps existing src/rag/game/game_engine.py GameEngine.

    Generates one HTML file per game spec in CoursewarePlan.game_specs.
    Returns the first game as the primary artifact; additional games
    are listed in metadata.
    """

    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = config_path
        self._engine = None

    @property
    def engine(self):
        if self._engine is None:
            from ...game.game_engine import GameEngine
            self._engine = GameEngine(self.config_path)
        return self._engine

    def artifact_type(self) -> ArtifactType:
        return ArtifactType.GAME_HTML

    def generate(self, plan: CoursewarePlan, output_dir: str) -> GeneratedArtifact:
        """
        Generate interactive game HTML files from CoursewarePlan.game_specs.

        If no game_specs exist, generates a default quiz based on the topic.
        """
        t0 = time.time()
        game_dir = str(Path(output_dir) / "games")
        Path(game_dir).mkdir(parents=True, exist_ok=True)

        topic = plan.intent.topic or plan.intent.chapter or "教学内容"
        context = plan.rag_context or ""

        game_specs = plan.game_specs
        if not game_specs:
            # Auto-generate a default quiz
            game_specs = [{"type": "quiz", "topic": topic, "questions": []}]

        all_results: List[Dict[str, Any]] = []
        all_paths: List[str] = []

        for spec in game_specs:
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
                all_results.append(result)
                if result.get("html_path"):
                    all_paths.append(result["html_path"])
                    logger.info("Game generated: %s → %s", game_type, result["html_path"])
            except Exception as e:
                logger.error("Game generation failed for type=%s: %s", game_type, e)
                all_results.append({"error": str(e), "game_type": game_type})

        # Primary artifact is the first successful game
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
