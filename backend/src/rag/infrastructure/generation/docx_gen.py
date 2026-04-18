"""
Word/DOCX generator wrapper — implements ArtifactGenerator protocol.

Wraps wym's existing DocxGenerator, adapting CoursewarePlan → outline dict.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Dict, List

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
        slide_lookup = {s.title: s for s in plan.slides}

        # Build teaching process from slides
        teaching_process = []
        for s in plan.slides:
            if s.layout in ("cover", "toc"):
                continue
            teaching_process.append({
                "stage": s.title,
                "duration": "",
                "content": DOCXGenerator._expand_stage_content(
                    stage=s.title,
                    bullet_points=s.bullet_points,
                    notes=s.notes,
                ),
                "activity": DOCXGenerator._expand_stage_activity(
                    stage=s.title,
                    notes=s.notes,
                    visual_suggestion=s.visual_suggestion,
                ),
            })

        # Build from lesson_plan_sections if available
        if plan.lesson_plan_sections:
            teaching_process = []
            for sec in plan.lesson_plan_sections:
                stage = sec.get("section", sec.get("stage", ""))
                ref_slide = slide_lookup.get(stage)
                teaching_process.append({
                    "stage": stage,
                    "duration": sec.get("duration", ""),
                    "content": DOCXGenerator._merge_section_text(
                        primary=sec.get("content", ""),
                        fallback=DOCXGenerator._expand_stage_content(
                            stage=stage,
                            bullet_points=list(getattr(ref_slide, "bullet_points", []) or []),
                            notes=getattr(ref_slide, "notes", ""),
                        ),
                        minimum_len=70,
                    ),
                    "activity": DOCXGenerator._merge_section_text(
                        primary=sec.get("method", sec.get("activity", "")),
                        fallback=DOCXGenerator._expand_stage_activity(
                            stage=stage,
                            notes=getattr(ref_slide, "notes", ""),
                            visual_suggestion=getattr(ref_slide, "visual_suggestion", ""),
                        ),
                        minimum_len=45,
                    ),
                })

        return {
            "title": intent.topic or intent.chapter or "教学设计",
            "subject": intent.subject or "生物",
            "grade": intent.grade_level or intent.target_audience,
            "duration": f"{intent.duration_minutes}分钟",
            "teaching_goal": [intent.teaching_goal] if intent.teaching_goal else intent.key_focus,
            "key_points": intent.key_focus,
            "difficulties": intent.difficulties,
            "teaching_method": intent.suggested_activities or [
                "讲授与启发结合，突出概念理解与过程分析",
                "问题驱动与课堂讨论结合，引导学生主动表达",
                "借助图片、结构示意与过程动画开展探究学习",
            ],
            "teaching_process": teaching_process,
            "homework": DOCXGenerator._build_homework(plan),
            "reflection": DOCXGenerator._build_reflection(plan),
        }

    @staticmethod
    def _normalize_sentence(text: str) -> str:
        value = " ".join((text or "").replace("\n", " ").split()).strip("；;，,。 ")
        if not value:
            return ""
        if value[-1] not in "。！？":
            value += "。"
        return value

    @staticmethod
    def _merge_section_text(primary: str, fallback: str, *, minimum_len: int) -> str:
        primary_text = DOCXGenerator._normalize_sentence(primary)
        if len(primary_text) >= minimum_len:
            return primary_text
        fallback_text = DOCXGenerator._normalize_sentence(fallback)
        if not primary_text:
            return fallback_text
        if not fallback_text or fallback_text == primary_text:
            return primary_text
        return DOCXGenerator._normalize_sentence(f"{primary_text} {fallback_text}")

    @staticmethod
    def _expand_stage_content(*, stage: str, bullet_points: List[str], notes: str) -> str:
        clean_points = [p.strip("；;。 ").strip() for p in bullet_points if p and p.strip()]
        point_text = "；".join(clean_points)
        if point_text:
            point_text = f"本环节围绕“{stage}”展开，重点包括{point_text}。"
        note_text = DOCXGenerator._normalize_sentence(notes)
        if point_text and note_text:
            return DOCXGenerator._normalize_sentence(f"{point_text} 教师讲解时可进一步强调：{note_text}")
        if point_text:
            return point_text
        if note_text:
            return DOCXGenerator._normalize_sentence(f"本环节围绕“{stage}”展开，教师可结合课堂讲解进一步说明：{note_text}")
        return DOCXGenerator._normalize_sentence(f"本环节围绕“{stage}”展开，引导学生从概念理解、过程分析和应用迁移三个层面完成学习。")

    @staticmethod
    def _expand_stage_activity(*, stage: str, notes: str, visual_suggestion: str) -> str:
        parts: List[str] = [
            f"教师围绕“{stage}”设置问题链，引导学生先观察现象、再归纳规律。"
        ]
        note_text = DOCXGenerator._normalize_sentence(notes)
        visual_text = DOCXGenerator._normalize_sentence(visual_suggestion)
        if note_text:
            parts.append(f"讲解时重点关注：{note_text}")
        if visual_text:
            parts.append(f"可结合{visual_text}组织学生进行表达、比较或推理。")
        else:
            parts.append("可结合示意图、流程图或关键术语板书组织学生进行同伴讨论与即时反馈。")
        return DOCXGenerator._normalize_sentence(" ".join(parts))

    @staticmethod
    def _build_homework(plan: CoursewarePlan) -> List[str]:
        topic = plan.intent.topic or plan.intent.chapter or "本节课"
        focuses = [item for item in plan.intent.key_focus if item]
        focus_text = "、".join(focuses[:3]) or topic
        difficulties = "、".join(plan.intent.difficulties[:2]) or "关键概念辨析"
        return [
            f"整理{topic}的知识结构图，围绕{focus_text}写出不少于150字的知识梳理，突出概念之间的联系。",
            f"完成1道与{topic}相关的综合应用题，结合课堂所学说明解题思路，并特别注意{difficulties}。",
        ]

    @staticmethod
    def _build_reflection(plan: CoursewarePlan) -> str:
        topic = plan.intent.topic or plan.intent.chapter or "本节课"
        focus_text = "、".join(plan.intent.key_focus[:3]) or "核心概念建构"
        difficulty_text = "、".join(plan.intent.difficulties[:2]) or "重点难点突破"
        return DOCXGenerator._normalize_sentence(
            f"本课以{topic}为主线，课堂设计需要持续关注学生对{focus_text}的理解深度。"
            f"实施过程中应重点观察学生在{difficulty_text}方面的掌握情况，"
            "根据学生回答与互动表现及时调整提问层次、示意图展示方式和知识迁移练习，"
            "确保学生不仅能够复述概念，还能够解释过程、辨析易错点并完成实际应用。"
        )
