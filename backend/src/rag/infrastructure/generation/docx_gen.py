"""
Word/DOCX generator wrapper — implements ArtifactGenerator protocol.

Wraps wym's existing DocxGenerator, adapting CoursewarePlan → outline dict.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Dict

from ...domain.models import ArtifactType, CoursewarePlan, GeneratedArtifact

logger = logging.getLogger("docx_gen")


class DOCXGenerator:
    """
    Wraps existing src/rag/docx_generator.py DocxGenerator.

    Adapts:
      CoursewarePlan fields → outline dict expected by DocxGenerator
    """

    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = config_path
        self._gen = None

    @property
    def gen(self):
        if self._gen is None:
            from ...docx_generator import DocxGenerator
            self._gen = DocxGenerator(self.config_path)
        return self._gen

    def artifact_type(self) -> ArtifactType:
        return ArtifactType.DOCX

    def generate(self, plan: CoursewarePlan, output_dir: str) -> GeneratedArtifact:
        """Generate a DOCX lesson plan from a CoursewarePlan."""
        t0 = time.time()
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        outline = self._plan_to_outline(plan)

        try:
            result = self.gen.generate_from_outline(
                outline=outline,
                output_dir=output_dir,
            )
            docx_path = result.get("docx_path", "")

            return GeneratedArtifact(
                artifact_type=ArtifactType.DOCX,
                file_path=docx_path,
                metadata={
                    "title": plan.intent.topic or plan.intent.chapter,
                },
                generation_time_sec=time.time() - t0,
            )
        except Exception as e:
            logger.error("DOCX generation failed: %s", e, exc_info=True)
            return GeneratedArtifact(
                artifact_type=ArtifactType.DOCX,
                file_path="",
                error=str(e),
                generation_time_sec=time.time() - t0,
            )

    @staticmethod
    def _plan_to_outline(plan: CoursewarePlan) -> Dict[str, Any]:
        """Convert CoursewarePlan → outline dict for DocxGenerator."""
        intent = plan.intent

        # Build teaching process from slides
        teaching_process = []
        for s in plan.slides:
            if s.layout in ("cover", "toc"):
                continue
            teaching_process.append({
                "stage": s.title,
                "duration": "",
                "content": "\n".join(s.bullet_points),
                "activity": s.notes or s.visual_suggestion,
            })

        # Build from lesson_plan_sections if available
        if plan.lesson_plan_sections:
            teaching_process = []
            for sec in plan.lesson_plan_sections:
                teaching_process.append({
                    "stage": sec.get("section", sec.get("stage", "")),
                    "duration": sec.get("duration", ""),
                    "content": sec.get("content", ""),
                    "activity": sec.get("method", sec.get("activity", "")),
                })

        return {
            "title": intent.topic or intent.chapter or "教学设计",
            "subject": intent.subject or "生物",
            "grade": intent.grade_level or intent.target_audience,
            "duration": f"{intent.duration_minutes}分钟",
            "teaching_goal": [intent.teaching_goal] if intent.teaching_goal else intent.key_focus,
            "key_points": intent.key_focus,
            "difficulties": intent.difficulties,
            "teaching_method": intent.suggested_activities or ["讲授法", "讨论法", "探究法"],
            "teaching_process": teaching_process,
            "homework": [],
            "reflection": "",
        }
