"""
PPT generator wrapper — implements ArtifactGenerator protocol.

Wraps wym's existing PPTGenerator, adapting CoursewarePlan → outline dict.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Dict

from ...domain.models import ArtifactType, CoursewarePlan, GeneratedArtifact

logger = logging.getLogger("pptx_gen")


class PPTXGenerator:
    """
    Wraps existing src/rag/ppt_generator.py PPTGenerator.

    Adapts:
      CoursewarePlan.slides (List[SlideSpec]) → outline dict expected by PPTGenerator
    """

    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = config_path
        self._gen = None

    @property
    def gen(self):
        if self._gen is None:
            from ...ppt_generator import PPTGenerator
            self._gen = PPTGenerator(self.config_path)
        return self._gen

    def artifact_type(self) -> ArtifactType:
        return ArtifactType.PPTX

    def generate(self, plan: CoursewarePlan, output_dir: str) -> GeneratedArtifact:
        """
        Generate a PPTX file from a CoursewarePlan.

        Converts SlideSpec list → outline dict → PPTGenerator.generate_from_outline()
        """
        t0 = time.time()
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        outline = self._plan_to_outline(plan)

        try:
            result = self.gen.generate_from_outline(
                outline=outline,
                output_dir=output_dir,
                author="ITO Teaching Agent",
            )
            pptx_path = result.get("pptx_path", "")
            slide_count = result.get("slide_count", len(plan.slides))

            return GeneratedArtifact(
                artifact_type=ArtifactType.PPTX,
                file_path=pptx_path,
                metadata={
                    "slide_count": slide_count,
                    "title": plan.intent.topic or plan.intent.chapter,
                },
                generation_time_sec=time.time() - t0,
            )
        except Exception as e:
            logger.error("PPT generation failed: %s", e, exc_info=True)
            return GeneratedArtifact(
                artifact_type=ArtifactType.PPTX,
                file_path="",
                error=str(e),
                generation_time_sec=time.time() - t0,
            )

    @staticmethod
    def _plan_to_outline(plan: CoursewarePlan) -> Dict[str, Any]:
        """Convert CoursewarePlan → outline dict for PPTGenerator."""
        slides = []
        for s in plan.slides:
            slide_dict: Dict[str, Any] = {
                "title": s.title,
                "content_points": s.bullet_points,
                "speaker_notes": s.notes,
                "visual_suggestion": s.visual_suggestion,
            }
            # Map layout to PPTGenerator slide types
            layout_map = {
                "cover": "cover",
                "toc": "toc",
                "summary": "summary",
                "interactive": "content",
                "content": "content",
            }
            slide_dict["type"] = layout_map.get(s.layout, "content")

            if s.image_path:
                slide_dict["image_path"] = s.image_path

            slides.append(slide_dict)

        return {
            "title": plan.intent.topic or plan.intent.chapter or "教学课件",
            "subtitle": plan.intent.teaching_goal or plan.intent.subject,
            "slides": slides,
        }
