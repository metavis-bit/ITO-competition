"""
课件生成流水线 — 串联 A04 全部环节

闭环流程:
  教师对话 → 意图提取 → RAG检索 → 生成指令集 → PPT + Word + 游戏
           ↑                                                    ↓
           ←──────────── 教师修改意见 ←──── 预览 ←──────────────↙

对应 A04:
  3c) 将教师意图与参考资料、知识库融合，形成课件生成指令集
  4)   根据指令集生成 PPT / Word / 游戏
  5)   预览 → 修改 → 再生成的闭环
"""

from __future__ import annotations

import json
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class CoursewareResult:
    """一次课件生成的完整结果"""
    intent_json: Dict[str, Any] = field(default_factory=dict)
    instructions_json: Dict[str, Any] = field(default_factory=dict)
    rag_context: str = ""

    pptx_path: Optional[str] = None
    pptx_status: str = ""
    pptx_slide_count: int = 0

    docx_path: Optional[str] = None
    docx_status: str = ""

    game_html: str = ""
    game_path: Optional[str] = None
    game_status: str = ""

    animation_html: str = ""
    animation_path: Optional[str] = None
    animation_status: str = ""

    errors: List[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = []
        if self.pptx_path:
            lines.append(f"✅ PPT: {self.pptx_slide_count}页 → {self.pptx_path}")
        elif self.pptx_status:
            lines.append(f"❌ PPT: {self.pptx_status}")
        if self.docx_path:
            lines.append(f"✅ Word教案 → {self.docx_path}")
        elif self.docx_status:
            lines.append(f"❌ Word: {self.docx_status}")
        if self.game_path:
            lines.append(f"✅ 互动游戏 → {self.game_path}")
        if self.animation_path:
            lines.append(f"✅ 知识动画 → {self.animation_path}")
        elif self.game_status:
            lines.append(f"❌ 游戏: {self.game_status}")
        if self.errors:
            lines.append(f"\n⚠️ 错误: {'; '.join(self.errors)}")
        return "\n".join(lines) if lines else "未生成任何课件"


class CoursewarePipeline:
    """
    课件生成流水线。

    核心方法:
      1. generate_all() — 从对话管理器一键生成全部课件
      2. regenerate_with_feedback() — 根据修改意见迭代再生成

    Example:
        pipeline = CoursewarePipeline(config_path="config.yaml")

        # 首次生成
        result = pipeline.generate_all(
            dialogue_mgr=dm,       # 已完成对话的 DialogueManager
            rag_service=svc,       # RAGService
            output_types=["ppt", "docx", "game"],
        )

        # 迭代修改
        result2 = pipeline.regenerate_with_feedback(
            feedback="把第3页的内容简化，增加一个案例",
            previous_result=result,
        )
    """

    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = config_path
        self._intent_extractor = None
        self._ppt_gen = None
        self._docx_gen = None
        self._game_engine = None

    @property
    def intent_extractor(self):
        if self._intent_extractor is None:
            from .dialogue.intent_extractor import IntentExtractor
            self._intent_extractor = IntentExtractor(self.config_path)
        return self._intent_extractor

    @property
    def ppt_gen(self):
        if self._ppt_gen is None:
            from .ppt_generator import PPTGenerator
            self._ppt_gen = PPTGenerator(self.config_path)
        return self._ppt_gen

    @property
    def docx_gen(self):
        if self._docx_gen is None:
            from .docx_generator import DocxGenerator
            self._docx_gen = DocxGenerator(self.config_path)
        return self._docx_gen

    @property
    def game_engine(self):
        if self._game_engine is None:
            from .game.game_engine import GameEngine
            self._game_engine = GameEngine(self.config_path)
        return self._game_engine

    # ─────────────────────────────────────────
    # 1. 一键生成全部课件
    # ─────────────────────────────────────────

    def generate_all(
        self,
        dialogue_mgr=None,
        rag_service=None,
        output_types: Optional[List[str]] = None,
        # 直接传参模式（不经对话）
        topic: str = "",
        teaching_goal: str = "",
        key_points: str = "",
        target_audience: str = "",
        duration: str = "45分钟",
        style: str = "清晰简洁",
        context: str = "",
        game_type: str = "quiz",
        game_count: int = 5,
    ) -> CoursewareResult:
        """
        一键生成全部课件。

        可以两种方式驱动:
        1. 传入 dialogue_mgr（已完成对话） → 自动提取意图、检索RAG、生成指令
        2. 直接传入参数（topic/goal等） → 跳过对话，直接生成
        """
        result = CoursewareResult()
        if output_types is None:
            output_types = ["ppt", "docx", "game"]

        # --- Step 1: 获取教学意图 ---
        if dialogue_mgr is not None:
            try:
                # 从对话历史提取
                history_text = dialogue_mgr._format_history()
                ref_text = dialogue_mgr._format_references()

                intent = self.intent_extractor.extract_intent(
                    dialogue_text=history_text,
                    reference_content=ref_text,
                )
                result.intent_json = intent.raw_json

                # 用对话中收集的信息补全
                c = dialogue_mgr.collected
                topic = topic or c.topic or intent.chapter or ""
                teaching_goal = teaching_goal or c.teaching_goal or ""
                key_points = key_points or ", ".join(c.key_points) or ", ".join(intent.key_focus) or ""
                target_audience = target_audience or c.target_audience or intent.grade_level or ""
                duration = c.duration_minutes and f"{c.duration_minutes}分钟" or duration
                style = c.style or style
            except Exception as e:
                result.errors.append(f"意图提取失败: {e}")

        if not topic:
            result.errors.append("缺少课题信息")
            return result

        # --- Step 2: RAG 检索知识库 ---
        rag_context = context
        if rag_service:
            try:
                rag_res = rag_service.query(question=topic, indexes=["kb"], top_k=5)
                evidence = rag_res.get("evidence", [])
                rag_texts = [ev.get("text", "") for ev in evidence if isinstance(ev, dict) and ev.get("text")]
                if rag_texts:
                    rag_context = "\n\n".join(rag_texts) + "\n\n" + (context or "")
            except Exception as e:
                result.errors.append(f"RAG检索失败(不影响生成): {e}")
        result.rag_context = rag_context

        # --- Step 3: 生成指令集 ---
        if result.intent_json:
            try:
                from .dialogue.intent_extractor import TeachingIntent
                intent_obj = TeachingIntent(**{
                    k: result.intent_json.get(k, v)
                    for k, v in TeachingIntent().__dict__.items()
                    if k != "raw_json"
                })
                intent_obj.raw_json = result.intent_json
                instructions = self.intent_extractor.generate_instructions(
                    intent=intent_obj,
                    rag_content=rag_context,
                    reference_content=dialogue_mgr._format_references() if dialogue_mgr else "",
                )
                result.instructions_json = instructions
            except Exception as e:
                result.errors.append(f"指令集生成失败(将用默认模式): {e}")

        # --- Step 4: 生成课件 ---
        # 4a) PPT
        if "ppt" in output_types:
            try:
                ppt_outline = result.instructions_json.get("ppt_outline")
                if ppt_outline and ppt_outline.get("slides"):
                    ppt_result = self.ppt_gen.generate_from_outline(
                        outline=ppt_outline, output_dir="outputs/pptx")
                else:
                    ppt_result = self.ppt_gen.generate_from_text(
                        topic=topic, teaching_goal=teaching_goal,
                        key_points=key_points, style=style,
                        slide_count=12, context=rag_context,
                        output_dir="outputs/pptx")
                result.pptx_path = ppt_result["pptx_path"]
                result.pptx_slide_count = ppt_result.get("slide_count", 0)
                result.pptx_status = f"成功 ({ppt_result.get('generation_time', 0)}s)"
            except Exception as e:
                result.pptx_status = str(e)
                result.errors.append(f"PPT生成: {e}")

        # 4b) Word
        if "docx" in output_types:
            try:
                docx_outline = result.instructions_json.get("docx_outline")
                if docx_outline and docx_outline.get("sections"):
                    # 将简易大纲转为完整格式
                    full_outline = {
                        "title": docx_outline.get("title", topic),
                        "subject": result.intent_json.get("subject", ""),
                        "grade": target_audience,
                        "duration": duration,
                        "teaching_goal": result.intent_json.get("key_focus", [teaching_goal]),
                        "key_points": result.intent_json.get("key_focus", [key_points]),
                        "difficulties": result.intent_json.get("difficulties", []),
                        "teaching_method": ["讲授法", "讨论法", "演示法"],
                    }
                    docx_result = self.docx_gen.generate_from_outline(
                        outline=full_outline, output_dir="outputs/docx")
                else:
                    docx_result = self.docx_gen.generate_from_text(
                        topic=topic, teaching_goal=teaching_goal,
                        key_points=key_points, duration=duration,
                        context=rag_context, output_dir="outputs/docx")
                result.docx_path = docx_result["docx_path"]
                result.docx_status = f"成功 ({docx_result.get('generation_time', 0)}s)"
            except Exception as e:
                result.docx_status = str(e)
                result.errors.append(f"Word生成: {e}")

        # 4c) 游戏
        if "game" in output_types:
            try:
                game_suggestions = result.intent_json.get("game_suggestions", [])
                gt = game_type
                gc = game_count
                greq = ""
                if game_suggestions:
                    gs = game_suggestions[0]
                    gt = gs.get("type", game_type)
                    greq = gs.get("description", "")

                if rag_service:
                    game_result = self.game_engine.generate_with_rag(
                        question=topic, game_type=gt, rag_service=rag_service,
                        indexes=["kb"], teacher_requirement=greq, count=gc,
                        output_dir="outputs/games")
                else:
                    game_result = self.game_engine.generate(
                        knowledge_topic=topic, game_type=gt,
                        teacher_requirement=greq, count=gc,
                        context=rag_context, output_dir="outputs/games")

                result.game_html = game_result["html"]
                result.game_path = game_result["html_path"]
                result.game_status = f"成功 ({game_result.get('generation_time', 0)}s)"

                # 5c) 将游戏互动页嵌入到PPT中
                if result.pptx_path:
                    try:
                        from pptx import Presentation as _Prs
                        from .ppt_generator import _make_interactive_slide
                        prs = _Prs(result.pptx_path)
                        game_filename = Path(result.game_path).name if result.game_path else "game.html"
                        game_title = game_result.get("title", topic)
                        from .game.game_prompts import GAME_DESCRIPTIONS
                        game_desc = GAME_DESCRIPTIONS.get(gt, "HTML5互动游戏")
                        # 在倒数第二页（总结前）插入互动页
                        _make_interactive_slide(prs, game_title, game_filename, game_desc)
                        prs.save(result.pptx_path)  # 覆盖保存
                        result.pptx_slide_count = len(prs.slides)
                    except Exception:
                        pass  # 嵌入失败不影响主流程
            except Exception as e:
                result.game_status = str(e)
                result.errors.append(f"游戏生成: {e}")

        # 4c-2) 知识点动画（A04: "动画创意"）
        if "game" in output_types or "animation" in output_types:
            try:
                from .game.animation_renderer import render_process_animation, ANIMATION_PROMPT
                # 用LLM生成动画脚本
                anim_prompt = ANIMATION_PROMPT.format(
                    context=rag_context[:2000] if rag_context else f"知识点: {topic}",
                    teacher_requirement=f"围绕{topic}的核心过程",
                    count=5,
                )
                raw_anim = self.game_engine.generator.generate(anim_prompt)
                anim_data = self.game_engine._parse_json_response(raw_anim)
                if not anim_data.get("steps"):
                    # fallback: 从意图中的teaching_logic构建
                    logic = result.intent_json.get("teaching_logic", [])
                    if logic:
                        anim_data = {
                            "title": f"{topic} — 流程动画",
                            "steps": [{"title": f"第{i+1}步: {s}", "description": s, "icon": "📌"} for i, s in enumerate(logic)]
                        }

                if anim_data.get("steps"):
                    anim_html = render_process_animation(anim_data)
                    from datetime import datetime
                    import re as _re
                    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                    safe = _re.sub(r'[^\w\u4e00-\u9fff]', '_', topic)[:30]
                    anim_dir = Path("outputs/animations")
                    anim_dir.mkdir(parents=True, exist_ok=True)
                    anim_path = str(anim_dir / f"anim_{safe}_{ts}.html")
                    Path(anim_path).write_text(anim_html, encoding="utf-8")
                    result.animation_html = anim_html
                    result.animation_path = anim_path
                    result.animation_status = "成功"
            except Exception as e:
                result.animation_status = str(e)
                # 动画失败不算严重错误

        return result

    # ─────────────────────────────────────────
    # 2. 根据修改意见迭代再生成
    # ─────────────────────────────────────────

    def regenerate_with_feedback(
        self,
        feedback: str,
        previous_result: CoursewareResult,
        rag_service=None,
        regenerate_types: Optional[List[str]] = None,
    ) -> CoursewareResult:
        """
        根据教师修改意见，迭代再生成课件。

        Args:
            feedback: 教师的修改意见，如"把第3页简化"、"增加一个案例"
            previous_result: 上一次生成的结果
            regenerate_types: 要重新生成的类型 ["ppt","docx","game"]，None=全部

        Returns:
            新的 CoursewareResult
        """
        if regenerate_types is None:
            regenerate_types = ["ppt", "docx", "game"]

        # 把修改意见融入上下文
        prev_intent = previous_result.intent_json
        topic = prev_intent.get("chapter", "") or prev_intent.get("subject", "课件")

        # 构造包含修改意见的增强上下文
        enhanced_context = previous_result.rag_context or ""
        enhanced_context += f"\n\n【教师修改意见】\n{feedback}\n"

        # 如果有之前的指令集，附加修改意见
        prev_instructions = previous_result.instructions_json
        if prev_instructions:
            enhanced_context += f"\n【之前的课件大纲（需要根据修改意见调整）】\n{json.dumps(prev_instructions, ensure_ascii=False, indent=2)[:3000]}\n"

        # 用修改后的信息重新生成
        result = CoursewareResult()
        result.intent_json = prev_intent
        result.rag_context = enhanced_context

        key_points = ", ".join(prev_intent.get("key_focus", []))
        teaching_goal = ", ".join(prev_intent.get("teaching_logic", []))
        target_audience = prev_intent.get("grade_level", "")

        # 重新生成需要的类型
        if "ppt" in regenerate_types:
            try:
                ppt_result = self.ppt_gen.generate_from_text(
                    topic=topic,
                    teaching_goal=teaching_goal,
                    key_points=key_points + f"\n\n教师修改意见: {feedback}",
                    style="根据教师修改意见调整",
                    slide_count=previous_result.pptx_slide_count or 12,
                    context=enhanced_context,
                    output_dir="outputs/pptx",
                )
                result.pptx_path = ppt_result["pptx_path"]
                result.pptx_slide_count = ppt_result.get("slide_count", 0)
                result.pptx_status = f"✅ 已根据修改意见重新生成"
            except Exception as e:
                result.pptx_status = str(e)
        else:
            result.pptx_path = previous_result.pptx_path
            result.pptx_slide_count = previous_result.pptx_slide_count

        if "docx" in regenerate_types:
            try:
                docx_result = self.docx_gen.generate_from_text(
                    topic=topic, teaching_goal=teaching_goal,
                    key_points=key_points + f"\n教师修改意见: {feedback}",
                    context=enhanced_context, output_dir="outputs/docx")
                result.docx_path = docx_result["docx_path"]
                result.docx_status = "✅ 已根据修改意见重新生成"
            except Exception as e:
                result.docx_status = str(e)
        else:
            result.docx_path = previous_result.docx_path

        if "game" in regenerate_types:
            try:
                gt = "quiz"
                game_suggestions = prev_intent.get("game_suggestions", [])
                if game_suggestions:
                    gt = game_suggestions[0].get("type", "quiz")

                game_result = self.game_engine.generate(
                    knowledge_topic=topic, game_type=gt,
                    teacher_requirement=feedback, count=5,
                    context=enhanced_context, output_dir="outputs/games")
                result.game_html = game_result["html"]
                result.game_path = game_result["html_path"]
                result.game_status = "✅ 已根据修改意见重新生成"
            except Exception as e:
                result.game_status = str(e)
        else:
            result.game_html = previous_result.game_html
            result.game_path = previous_result.game_path

        return result
