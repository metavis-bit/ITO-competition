"""
Animation HTML generator wrapper — implements ArtifactGenerator protocol.

Generates knowledge-point process animations from CoursewarePlan.animation_steps.
If no steps are provided, uses LLM to auto-generate animation steps from the topic.

对应 A04 要求:
  - 4c) 创意知识点动画
  - 5c) 动画可以以 HTML5 网页导出
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from ...domain.models import ArtifactType, CoursewarePlan, GeneratedArtifact

logger = logging.getLogger("animation_gen")

# LLM prompt for auto-generating animation steps
_ANIMATION_PROMPT = """你是一位教学动画设计专家。请将以下知识点拆解为一个可视化动画的步骤序列。

【知识点】{topic}
【参考内容】
{context}

请严格按以下 JSON 格式输出，不要输出多余文字：
{{
    "title": "动画标题（简洁有力）",
    "steps": [
        {{"icon": "🔬", "title": "步骤标题", "description": "该步骤的详细说明（1-2句话）"}},
        {{"icon": "🧬", "title": "步骤标题", "description": "说明"}},
        {{"icon": "⚡", "title": "步骤标题", "description": "说明"}}
    ]
}}

要求:
- 步骤数量 4-8 步，符合该知识点的逻辑顺序
- 每步使用一个与内容相关的 emoji 作为 icon
- 标题简洁（4-8字），描述清楚该步骤的核心内容
- 适合高中生理解的表述方式
"""


class AnimationHTMLGenerator:
    """
    Generates knowledge-point GSAP animations from CoursewarePlan.

    Uses animation_renderer.render_process_animation() for HTML rendering.
    Falls back to LLM-generated steps if plan.animation_steps is empty.
    """

    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = config_path
        self._generator = None

    @property
    def llm(self):
        if self._generator is None:
            from ...config import load_config
            from ...generator import GeneratorConfig, QwenGenerator
            cfg = load_config(self.config_path)
            g_cfg = cfg.get("generator", {}) or {}
            self._generator = QwenGenerator(GeneratorConfig(
                mode=str(g_cfg.get("mode", "api")),
                api_model=str(g_cfg.get("api_model", "qwen-plus-latest")),
                api_base_url_env=str(g_cfg.get("api_base_url_env", "OPENAI_BASE_URL")),
                api_key_env=str(g_cfg.get("api_key_env", "OPENAI_API_KEY")),
                timeout_sec=float(g_cfg.get("timeout_sec", 120.0)),
                local_model_path=str(g_cfg.get("local_model_path", "")),
                device=str(g_cfg.get("device", "cpu")),
                max_new_tokens=int(g_cfg.get("max_new_tokens", 2048)),
                temperature=float(g_cfg.get("temperature", 0.4)),
            ))
        return self._generator

    def artifact_type(self) -> ArtifactType:
        return ArtifactType.ANIMATION_HTML

    def generate(self, plan: CoursewarePlan, output_dir: str) -> GeneratedArtifact:
        """
        Generate a knowledge-point animation HTML file.

        Uses plan.animation_steps if available; otherwise calls LLM to generate steps.
        """
        t0 = time.time()
        anim_dir = Path(output_dir) / "animations"
        anim_dir.mkdir(parents=True, exist_ok=True)

        topic = plan.intent.topic or plan.intent.chapter or "教学内容"
        context = plan.rag_context or ""

        # Get or generate animation data
        animation_data = self._get_animation_data(plan, topic, context)

        # Render HTML
        from ...game.animation_renderer import render_process_animation
        html_content = render_process_animation(animation_data)

        # Save file
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_topic = re.sub(r'[^\w\u4e00-\u9fff]', '_', topic)[:30]
        filename = f"animation_{safe_topic}_{ts}.html"
        filepath = anim_dir / filename
        filepath.write_text(html_content, encoding="utf-8")

        logger.info("Animation generated: %s (%d steps)", filepath, len(animation_data.get("steps", [])))

        return GeneratedArtifact(
            artifact_type=ArtifactType.ANIMATION_HTML,
            file_path=str(filepath),
            metadata={
                "title": animation_data.get("title", topic),
                "step_count": len(animation_data.get("steps", [])),
            },
            generation_time_sec=time.time() - t0,
        )

    def _get_animation_data(
        self, plan: CoursewarePlan, topic: str, context: str
    ) -> Dict[str, Any]:
        """Get animation data from plan or generate via LLM."""
        # Use existing animation_steps if available
        if plan.animation_steps:
            steps = plan.animation_steps
            # Normalize: could be list of dicts or a single dict with "steps"
            if isinstance(steps, list) and len(steps) > 0:
                if isinstance(steps[0], dict) and "icon" in steps[0]:
                    return {"title": f"{topic} — 知识动画", "steps": steps}
                # Maybe it's a wrapper with title + steps
                if isinstance(steps[0], dict) and "steps" in steps[0]:
                    return steps[0]

        # Auto-generate via LLM
        prompt = _ANIMATION_PROMPT.format(
            topic=topic,
            context=context[:2000] if context else "无参考资料",
        )

        try:
            raw = self.llm.generate(prompt)
            data = self._parse_json(raw)
            if data.get("steps"):
                return data
        except Exception as e:
            logger.warning("LLM animation generation failed: %s", e)

        # Fallback: extract key points from slides as animation steps
        return self._fallback_from_slides(plan, topic)

    def _fallback_from_slides(
        self, plan: CoursewarePlan, topic: str
    ) -> Dict[str, Any]:
        """Build animation steps from slide content as fallback."""
        icons = ["📖", "🔬", "🧬", "⚡", "🔄", "✅", "💡", "🎯"]
        steps = []
        for i, slide in enumerate(plan.slides):
            if slide.slide_type in ("cover", "toc", "thanks"):
                continue
            steps.append({
                "icon": icons[i % len(icons)],
                "title": slide.title[:20] if slide.title else f"步骤 {len(steps) + 1}",
                "description": (
                    slide.bullet_points[0][:80] if slide.bullet_points
                    else slide.notes[:80] if slide.notes else "知识要点"
                ),
            })
            if len(steps) >= 8:
                break

        if not steps:
            steps = [
                {"icon": "📖", "title": "知识引入", "description": f"了解{topic}的基本概念"},
                {"icon": "🔬", "title": "核心内容", "description": f"深入学习{topic}的关键知识"},
                {"icon": "✅", "title": "总结归纳", "description": f"回顾{topic}的核心要点"},
            ]

        return {"title": f"{topic} — 知识动画", "steps": steps}

    @staticmethod
    def _parse_json(raw: str) -> Dict[str, Any]:
        text = raw.strip()
        text = re.sub(r'^```(?:json)?\s*', '', text, flags=re.MULTILINE)
        text = re.sub(r'```\s*$', '', text, flags=re.MULTILINE)
        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        match = re.search(r'\{[\s\S]*\}', text)
        if match:
            candidate = re.sub(r',\s*([}\]])', r'\1', match.group(0))
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass
        return {}
