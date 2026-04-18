"""
多轮对话管理器 — 需求收集状态机

对应 A04 要求:
  - 2a) 提供语音/文字输入
  - 2b) 智能对话：主动提问、多轮对话、总结确认需求
  - 2c) 参考资料上传功能
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from ..config import load_config
from ..infrastructure.llm import LLMRouter
from .intent_extractor import IntentExtractor, TeachingIntent
from .prompts import DIALOGUE_SYSTEM_PROMPT, DIALOGUE_TURN_PROMPT
from .reference_handler import ReferenceHandler


class DialogueState(str, Enum):
    """对话阶段"""
    GREETING    = "greeting"     # 初始问候
    COLLECTING  = "collecting"   # 需求收集中
    CONFIRMING  = "confirming"   # 需求确认中
    READY       = "ready"        # 需求已确认，准备生成
    GENERATING  = "generating"   # 正在生成课件
    ITERATING   = "iterating"    # 迭代修改中


@dataclass
class CollectedInfo:
    """已收集的教学需求信息"""
    subject: str = ""
    topic: str = ""
    teaching_goal: str = ""
    target_audience: str = ""
    duration_minutes: int = 0
    output_types: List[str] = field(default_factory=list)
    key_points: List[str] = field(default_factory=list)
    difficulties: List[str] = field(default_factory=list)
    style: str = ""
    special_requirements: str = ""
    reference_files: List[Dict[str, Any]] = field(default_factory=list)

    def to_text(self) -> str:
        lines = []
        if self.subject: lines.append(f"学科: {self.subject}")
        if self.topic: lines.append(f"知识点: {self.topic}")
        if self.teaching_goal: lines.append(f"教学目标: {self.teaching_goal}")
        if self.target_audience: lines.append(f"教学对象: {self.target_audience}")
        if self.duration_minutes: lines.append(f"课时: {self.duration_minutes}分钟")
        if self.output_types: lines.append(f"输出类型: {', '.join(self.output_types)}")
        if self.key_points: lines.append(f"重点: {', '.join(self.key_points)}")
        if self.difficulties: lines.append(f"难点: {', '.join(self.difficulties)}")
        if self.style: lines.append(f"风格: {self.style}")
        if self.special_requirements: lines.append(f"特殊要求: {self.special_requirements}")
        if self.reference_files:
            refs = [f"  - {r.get('file_name', '未知')} ({r.get('teacher_note', '')})" for r in self.reference_files]
            lines.append("参考资料:\n" + "\n".join(refs))
        return "\n".join(lines) if lines else "（尚未收集到信息）"

    def missing_fields(self) -> List[str]:
        missing = []
        if not self.topic: missing.append("知识点/章节")
        if not self.teaching_goal: missing.append("教学目标")
        if not self.target_audience: missing.append("教学对象")
        return missing

    def is_complete(self) -> bool:
        return len(self.missing_fields()) == 0


@dataclass
class PreparedDialogueTurn:
    mode: str
    state: DialogueState
    reply: str = ""
    task: str = "dialogue"
    messages: List[Dict[str, str]] = field(default_factory=list)


class DialogueManager:
    """
    多轮对话管理器。

    管理教师与AI之间的多轮对话，收集需求、追问补充信息、
    确认最终需求、触发课件生成。

    Example:
        dm = DialogueManager(config_path="config.yaml")
        reply, state = dm.chat("我想做一个关于中心法则的PPT")
        print(reply)  # AI会追问缺失信息
        reply, state = dm.chat("面向高二学生，45分钟")
        ...
    """

    def __init__(self, config_path: str = "config.yaml", llm: Optional[LLMRouter] = None):
        self.config_path = config_path
        self.state = DialogueState.GREETING
        self.history: List[Dict[str, str]] = []  # [{"role": "user/assistant", "content": ...}]
        self.collected = CollectedInfo(subject="生物")
        self.intent: Optional[TeachingIntent] = None

        cfg = load_config(self.config_path)
        g_cfg = cfg.get("generator", {}) or {}
        self.llm = llm or LLMRouter(g_cfg)
        self.dialogue_timeout_sec = int(g_cfg.get("dialogue_timeout_sec", 60))
        self.dialogue_max_new_tokens = int(g_cfg.get("dialogue_max_new_tokens", 320))
        self.dialogue_temperature = float(g_cfg.get("temperature", 0.2))
        self._intent_extractor = None
        self._ref_handler = None

    @property
    def intent_extractor(self) -> IntentExtractor:
        if self._intent_extractor is None:
            self._intent_extractor = IntentExtractor(self.config_path)
        return self._intent_extractor

    @property
    def ref_handler(self) -> ReferenceHandler:
        if self._ref_handler is None:
            self._ref_handler = ReferenceHandler(self.config_path)
        return self._ref_handler

    # ─────────────────────────────────────────
    # 核心对话接口
    # ─────────────────────────────────────────

    def chat(
        self,
        user_input: str,
        uploaded_files: Optional[List[str]] = None,
        file_notes: Optional[List[str]] = None,
    ) -> Tuple[str, DialogueState]:
        """
        处理一轮对话。

        Args:
            user_input: 教师输入的文字
            uploaded_files: 本轮上传的文件路径列表
            file_notes: 对应的文件说明

        Returns:
            (assistant_reply, current_state)
        """
        turn = self.prepare_turn(
            user_input,
            uploaded_files=uploaded_files,
            file_notes=file_notes,
        )
        if turn.mode == "local":
            self.history.append({"role": "assistant", "content": turn.reply})
            return turn.reply, turn.state

        reply = self._generate_reply(
            user_input,
            task=turn.task,
            messages=turn.messages,
        )
        visible_reply = self.finalize_cloud_reply(reply)
        return visible_reply, self.state
        # 处理上传的文件
        if uploaded_files:
            notes = file_notes or [""] * len(uploaded_files)
            for fp, note in zip(uploaded_files, notes):
                parsed = self.ref_handler.parse_file(fp, teacher_note=note)
                self.collected.reference_files.append(parsed)

        # 记录用户输入
        self.history.append({"role": "user", "content": user_input})

        # 根据状态处理
        if self.state == DialogueState.GREETING:
            self.state = DialogueState.COLLECTING

        previous_missing = self.collected.missing_fields()

        # 尝试从用户输入中提取信息并更新 collected
        self._update_collected_from_input(user_input)

        llm_collecting_applied = False
        if self.state == DialogueState.COLLECTING and self._should_use_llm_collecting_pass(user_input):
            llm_collecting_applied = self._enhance_collected_with_llm(user_input)

        # 检查是否教师发了确认指令
        if self._is_confirm_signal(user_input):
            if self.collected.is_complete():
                self.state = DialogueState.READY
                reply = self._generate_final_summary()
                self.history.append({"role": "assistant", "content": reply})
                return reply, self.state

        # 检查信息是否完整
        completed_this_turn = self.collected.is_complete() and self.state == DialogueState.COLLECTING
        if completed_this_turn:
            self.state = DialogueState.CONFIRMING

        if self.state == DialogueState.COLLECTING and (
            llm_collecting_applied
            or self._should_use_local_collecting_reply(
                user_input,
                previous_missing=previous_missing,
                current_missing=self.collected.missing_fields(),
            )
        ):
            reply = self._generate_local_collecting_reply()
            self.history.append({"role": "assistant", "content": reply})
            return reply, self.state

        if self.state == DialogueState.CONFIRMING and completed_this_turn and (
            llm_collecting_applied or not self._looks_complex_or_ambiguous(user_input)
        ):
            reply = self._generate_local_confirmation()
            self.history.append({"role": "assistant", "content": reply})
            return reply, self.state

        # 保留云端模型给更复杂的确认/修改场景。
        reply = self._generate_reply(user_input)
        self.history.append({"role": "assistant", "content": reply})

        if "[READY]" in reply:
            self.state = DialogueState.CONFIRMING

        return reply, self.state

    def confirm_and_extract(self) -> TeachingIntent:
        """确认需求并提取结构化教学意图"""
        history_text = self._format_history()
        ref_text = self._format_references()

        self.intent = self.intent_extractor.extract_intent(
            dialogue_text=history_text,
            reference_content=ref_text,
        )
        # Project constraint: biology-only knowledge base.
        self.intent.subject = "生物"
        if not self.intent.chapter:
            self.intent.chapter = self.collected.topic or "智绘生物"
        self.state = DialogueState.READY
        return self.intent

    def reset(self):
        """重置对话"""
        self.state = DialogueState.GREETING
        self.history = []
        self.collected = CollectedInfo(subject="生物")
        self.intent = None

    def prepare_turn(
        self,
        user_input: str,
        uploaded_files: Optional[List[str]] = None,
        file_notes: Optional[List[str]] = None,
    ) -> PreparedDialogueTurn:
        if uploaded_files:
            notes = file_notes or [""] * len(uploaded_files)
            for fp, note in zip(uploaded_files, notes):
                parsed = self.ref_handler.parse_file(fp, teacher_note=note)
                self.collected.reference_files.append(parsed)

        self.history.append({"role": "user", "content": user_input})

        if self.state == DialogueState.GREETING:
            self.state = DialogueState.COLLECTING

        previous_missing = self.collected.missing_fields()
        self._update_collected_from_input(user_input)

        if self._is_confirm_signal(user_input) and self.collected.is_complete():
            self.state = DialogueState.READY
            return PreparedDialogueTurn(
                mode="local",
                state=self.state,
                reply=self._generate_final_summary(),
            )

        if self.state == DialogueState.COLLECTING and self._is_greeting_or_smalltalk(user_input):
            return PreparedDialogueTurn(
                mode="cloud",
                state=self.state,
                task="dialogue",
                messages=self._build_cloud_messages(user_input, task="dialogue"),
            )

        completed_this_turn = self.collected.is_complete() and self.state == DialogueState.COLLECTING
        if completed_this_turn:
            self.state = DialogueState.CONFIRMING

        if self.state == DialogueState.COLLECTING and self._should_use_local_collecting_reply(
            user_input,
            previous_missing=previous_missing,
            current_missing=self.collected.missing_fields(),
        ):
            return PreparedDialogueTurn(
                mode="local",
                state=self.state,
                reply=self._generate_local_collecting_reply(),
            )

        if self.state == DialogueState.CONFIRMING and completed_this_turn and not self._looks_complex_or_ambiguous(user_input):
            return PreparedDialogueTurn(
                mode="local",
                state=self.state,
                reply=self._generate_local_confirmation(),
            )

        task = "intent" if self._should_use_strong_cloud_understanding(user_input) else "dialogue"
        return PreparedDialogueTurn(
            mode="cloud",
            state=self.state,
            task=task,
            messages=self._build_cloud_messages(user_input, task=task),
        )

    # ─────────────────────────────────────────
    # 内部方法
    # ─────────────────────────────────────────

    def _generate_reply(
        self,
        user_input: str,
        *,
        task: str = "dialogue",
        messages: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        """调用单次云端主回复，避免复杂轮次双调用。"""
        actual_messages = messages or self._build_cloud_messages(user_input, task=task)
        return self.llm.generate(
            "",
            task=task,
            messages=actual_messages,
            max_tokens=self._select_cloud_max_tokens(task),
            temperature=self._select_cloud_temperature(task),
            timeout_sec=self.dialogue_timeout_sec,
            cache=False,
            max_retries=0,
        )

    def _should_use_strong_cloud_understanding(self, user_input: str) -> bool:
        return self.state in (DialogueState.COLLECTING, DialogueState.CONFIRMING) and self._looks_complex_or_ambiguous(user_input)

    def _select_cloud_max_tokens(self, task: str) -> int:
        if task == "intent":
            return min(max(self.dialogue_max_new_tokens, 220), 320)
        return self.dialogue_max_new_tokens

    def _select_cloud_temperature(self, task: str) -> float:
        if task == "intent":
            return 0.15
        return self.dialogue_temperature

    def _build_cloud_messages(self, user_input: str, *, task: str) -> List[Dict[str, str]]:
        system_prompt = (
            "You are a professional biology teaching copilot.\n"
            "Respond in natural Chinese.\n"
            "For complex teacher requests, first briefly confirm the key constraints you understood in one sentence.\n"
            "Then ask at most one or two truly missing questions, or summarize for confirmation if the core information is already enough.\n"
            "Do not sound like a rigid form-filling bot.\n"
            "At the very end, append exactly one line that starts with [[ITO_META]] followed by compact JSON.\n"
            "The JSON schema is: "
            "{\"topic\":\"\",\"teaching_goal\":\"\",\"target_audience\":\"\",\"duration_minutes\":0,"
            "\"key_points\":[],\"difficulties\":[],\"style\":\"\",\"special_requirements\":\"\",\"ready\":false}\n"
            "Do not mention the metadata line in the visible answer."
        )
        prompt = (
            f"Current state: {self.state.value}\n"
            f"Known teaching requirements:\n{self._build_dialogue_context_summary()}\n\n"
            f"Recent chat:\n{self._format_recent_history(max_turns=3)}\n\n"
            f"Current teacher input:\n{user_input}\n\n"
            "Please answer now."
        )
        if task == "intent":
            system_prompt += "\nPrioritize accurate understanding of nuanced teaching constraints such as style, cases, interaction, difficulty, and exclusions."
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]

    def finalize_cloud_reply(self, raw_reply: str) -> str:
        visible_reply, meta = self._split_reply_and_meta(raw_reply)
        self._merge_reply_meta(meta)

        if meta.get("ready") and self.collected.is_complete():
            self.state = DialogueState.CONFIRMING
        elif self.state == DialogueState.COLLECTING and self.collected.is_complete():
            self.state = DialogueState.CONFIRMING

        self.history.append({"role": "assistant", "content": visible_reply})
        return visible_reply

    def _split_reply_and_meta(self, raw_reply: str) -> Tuple[str, Dict[str, Any]]:
        marker = "[[ITO_META]]"
        if marker not in raw_reply:
            return raw_reply.strip(), {}

        visible, meta_text = raw_reply.split(marker, 1)
        meta = self._parse_json_fragment(meta_text)
        return visible.strip(), meta

    @staticmethod
    def _parse_json_fragment(text: str) -> Dict[str, Any]:
        text = text.strip()
        if not text:
            return {}
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{[\s\S]*\}", text)
            if match:
                try:
                    return json.loads(match.group(0))
                except json.JSONDecodeError:
                    return {}
        return {}

    def _merge_reply_meta(self, data: Dict[str, Any]) -> None:
        if not isinstance(data, dict):
            return

        topic = str(data.get("topic", "") or "").strip()
        if topic and (not self.collected.topic or len(topic) > len(self.collected.topic)):
            self.collected.topic = topic

        teaching_goal = str(data.get("teaching_goal", "") or "").strip()
        if teaching_goal and (not self.collected.teaching_goal or len(teaching_goal) > len(self.collected.teaching_goal)):
            self.collected.teaching_goal = teaching_goal

        target_audience = str(data.get("target_audience", "") or "").strip()
        if target_audience and (not self.collected.target_audience or len(target_audience) > len(self.collected.target_audience)):
            self.collected.target_audience = target_audience

        duration_minutes = data.get("duration_minutes", 0)
        if isinstance(duration_minutes, int) and duration_minutes > 0:
            self.collected.duration_minutes = duration_minutes

        style = str(data.get("style", "") or "").strip()
        if style and (not self.collected.style or len(style) > len(self.collected.style)):
            self.collected.style = style

        special_requirements = str(data.get("special_requirements", "") or "").strip()
        if special_requirements:
            if not self.collected.special_requirements:
                self.collected.special_requirements = special_requirements
            elif special_requirements not in self.collected.special_requirements:
                self.collected.special_requirements = f"{self.collected.special_requirements}; {special_requirements}"

        for key, target in (("key_points", self.collected.key_points), ("difficulties", self.collected.difficulties)):
            values = data.get(key, [])
            if isinstance(values, list):
                for item in values:
                    text = str(item or "").strip()
                    if text and text not in target:
                        target.append(text)

    def _build_dialogue_context_summary(self) -> str:
        parts: List[str] = [self.collected.to_text()]
        if self.collected.reference_files:
            parts.append(f"Reference files received: {len(self.collected.reference_files)}")
        return "\n".join(part for part in parts if part).strip()

    def _format_recent_history(self, max_turns: int = 3) -> str:
        if not self.history:
            return "(empty)"

        recent = self.history[-max_turns * 2:]
        earlier = self.history[:-max_turns * 2]
        lines: List[str] = []
        if earlier:
            lines.append(f"Earlier context summary: {self._summarize_history(earlier)}")
        for msg in recent:
            role = "教师" if msg["role"] == "user" else "AI助手"
            lines.append(f"{role}: {msg['content']}")
        return "\n".join(lines)

    def _summarize_history(self, messages: List[Dict[str, str]]) -> str:
        user_messages = [msg["content"].strip() for msg in messages if msg["role"] == "user" and msg["content"].strip()]
        if not user_messages:
            return "No earlier teacher constraints."
        summary = "；".join(user_messages[-2:])
        return summary[:180]

    def _generate_local_collecting_reply(self) -> str:
        """Generate a deterministic follow-up for the fast collecting stage."""
        missing = self.collected.missing_fields()
        if not missing:
            self.state = DialogueState.CONFIRMING
            return self._generate_local_confirmation()

        prompts = self._build_missing_field_prompts(missing[:2])
        known_bits = self._build_known_bits()
        parts: List[str] = []
        if known_bits:
            parts.append(f"目前我已理解到：{known_bits}。")
        parts.append("为了更快生成首版课件，我还需要补充以下信息：")
        parts.extend(f"{idx}. {prompt}" for idx, prompt in enumerate(prompts, start=1))
        parts.append("你可以直接连续回复，我会自动整理。")
        return "\n".join(parts)

    def _generate_local_confirmation(self) -> str:
        """Generate a local summary once the core teaching slots are complete."""
        summary_parts = []
        if self.collected.topic:
            summary_parts.append(f"课题：{self.collected.topic}")
        if self.collected.teaching_goal:
            summary_parts.append(f"教学目标：{self.collected.teaching_goal}")
        if self.collected.target_audience:
            summary_parts.append(f"授课对象：{self.collected.target_audience}")
        if self.collected.duration_minutes:
            summary_parts.append(f"课时：{self.collected.duration_minutes}分钟")
        if self.collected.key_points:
            summary_parts.append(f"重点：{'、'.join(self.collected.key_points[:4])}")
        if self.collected.difficulties:
            summary_parts.append(f"难点：{'、'.join(self.collected.difficulties[:4])}")
        if self.collected.style:
            summary_parts.append(f"风格：{self.collected.style}")
        if self.collected.special_requirements:
            summary_parts.append(f"特殊要求：{self.collected.special_requirements}")

        lines = ["我已经完成本轮需求整理：", *[f"- {item}" for item in summary_parts]]
        if self.collected.reference_files:
            lines.append(f"- 参考资料：已接收 {len(self.collected.reference_files)} 份")
        lines.append("如果这些信息无误，请直接回复“确认”或点击“确认并生成课件”。")
        lines.append("如果还要调整，也可以继续补充，我会据此更新。")
        return "\n".join(lines)

    def _generate_final_summary(self) -> str:
        """生成最终的需求确认总结"""
        summary = self.collected.to_text()
        ref_text = self._format_references_brief()
        reply = (
            "✅ **需求确认完毕！** 以下是您的教学课件需求总结：\n\n"
            f"{summary}\n\n"
        )
        if ref_text:
            reply += f"**参考资料：**\n{ref_text}\n\n"
        reply += (
            "如果以上信息无误，您可以：\n"
            "- 点击「生成课件」开始制作\n"
            "- 继续补充或修改需求\n"
        )
        return reply

    def _update_collected_from_input(self, text: str):
        """从用户输入中提取并更新已收集信息（规则增强版）。"""
        t = text.lower()

        # 项目知识库仅支持生物，固定学科以避免检索跑偏
        self.collected.subject = "生物"

        # 主题/章节
        if not self.collected.topic:
            topic = self._extract_topic(text)
            if topic:
                self.collected.topic = topic

        # 教学目标
        if not self.collected.teaching_goal:
            goal = self._extract_teaching_goal(text)
            if goal:
                self.collected.teaching_goal = goal

        # 教学对象
        grade_match = re.search(r"(高[一二三]|初[一二三]|[一二三四五六]年级|大[一二三四]|小学[一二三四五六]年级)", text)
        if grade_match and not self.collected.target_audience:
            self.collected.target_audience = grade_match.group(1)

        # 时长（分钟 / 课时）
        duration_match = re.search(r"(\d+)\s*分钟", text)
        if duration_match and not self.collected.duration_minutes:
            self.collected.duration_minutes = int(duration_match.group(1))
        elif not self.collected.duration_minutes and re.search(r"(一|1)\s*课时", text):
            self.collected.duration_minutes = 45

        # 课件类型
        output_map = {
            "ppt": "ppt",
            "powerpoint": "ppt",
            "演示": "ppt",
            "幻灯片": "ppt",
            "课件": "ppt",
            "教案": "docx",
            "word": "docx",
            "文档": "docx",
            "游戏": "game",
            "互动": "game",
            "动画": "animation",
        }
        for kw, out in output_map.items():
            if kw in t and out not in self.collected.output_types:
                self.collected.output_types.append(out)

        # 重点/难点
        key_points = self._extract_list_after_keywords(text, ("重点", "关键点", "核心点", "要点"))
        for item in key_points:
            if item not in self.collected.key_points:
                self.collected.key_points.append(item)

        difficulties = self._extract_list_after_keywords(text, ("难点", "易错点", "易混点"))
        for item in difficulties:
            if item not in self.collected.difficulties:
                self.collected.difficulties.append(item)

        # 风格
        if not self.collected.style:
            style_match = re.search(r"(?:风格|教学方式|课堂形式|教学方法)(?:是|为|：|:)?\s*([^。；;\n]{2,50})", text)
            if style_match:
                self.collected.style = style_match.group(1).strip()
            elif any(kw in t for kw in ("互动", "探究", "启发", "案例", "实验", "讨论")):
                self.collected.style = "互动探究"

    @staticmethod
    def _extract_topic(text: str) -> str:
        patterns = [
            r"(?:主题|章节|知识点)(?:是|为|：|:)?\s*([^，。；;\n]{2,40})",
            r"(?:关于|讲解|讲|学习|复习|准备|制作|设计)([^，。；;\n]{2,40})(?:的?(?:课件|课程|课堂|教案|ppt|PPT)|[，。；;]|$)",
            r"(?:我想|想要|需要|希望)(?:做|准备|上)?(?:一节)?([^，。；;\n]{2,40})(?:课|课程|课堂|课件|教案)",
            r"(?:学会|理解|掌握|能够|能|说出|口述|描述|解释|分析|比较|归纳|总结|完成)([^，。；;\n]{2,40})",
        ]
        for pat in patterns:
            match = re.search(pat, text)
            if match:
                topic = DialogueManager._clean_topic_candidate(match.group(1))
                if topic:
                    return topic
        return ""

    @staticmethod
    def _extract_teaching_goal(text: str) -> str:
        patterns = [
            r"(?:教学目标|目标)(?:是|为|：|:)?\s*([^。；;\n]{4,120})",
            r"(?:希望学生|让学生|使学生)\s*([^。；;\n]{4,120})",
            r"(?:达到|实现)([^。；;\n]{4,120})",
            r"((?:学会|理解|掌握|能够|能|说出|口述|描述|解释|分析|比较|归纳|总结|完成)[^。；;\n]{4,120})",
        ]
        for pat in patterns:
            match = re.search(pat, text)
            if match:
                goal = match.group(1).strip(" ，。；;：:")
                if goal:
                    return goal
        return ""

    @staticmethod
    def _clean_topic_candidate(value: str) -> str:
        topic = value.strip(" ，。；;：:")
        topic = re.sub(r"^(?:关于|有关|围绕)", "", topic)
        topic = re.sub(r"(?:的详细内容|的具体内容|的全部内容|的内容|相关内容|相关知识|知识点|课程|课件|教案)$", "", topic)
        topic = re.sub(r"^(?:口述|说出|描述|解释|分析|比较|归纳|总结)", "", topic)
        topic = topic.strip(" ，。；;：:")
        return topic[:40]

    @staticmethod
    def _extract_list_after_keywords(text: str, keywords: Tuple[str, ...]) -> List[str]:
        items: List[str] = []
        for kw in keywords:
            match = re.search(rf"(?:{kw})(?:是|为|：|:)?\s*([^。；;\n]+)", text)
            if not match:
                continue
            raw = match.group(1).strip()
            for part in re.split(r"[、,，/；;]|(?:和)|(?:及)|(?:与)", raw):
                p = part.strip(" 　")
                if not p:
                    continue
                if len(p) > 30:
                    p = p[:30]
                if p and p not in items:
                    items.append(p)
        return items

    @staticmethod
    def _is_confirm_signal(text: str) -> bool:
        signals = ["确认", "没问题", "可以了", "就这样", "开始生成", "生成课件", "ok", "好的开始"]
        return any(s in text.lower() for s in signals)

    @staticmethod
    def _build_missing_field_prompts(fields: List[str]) -> List[str]:
        prompt_map = {
            "知识点/章节": "这节课具体讲哪个知识点、章节或主题？",
            "教学目标": "你希望学生通过这节课学会什么、理解什么，或完成什么任务？",
            "教学对象": "这节课面向哪个年级或学段？例如高一、高二、初二等。",
        }
        return [prompt_map.get(field, f"请补充：{field}") for field in fields]

    def _build_known_bits(self) -> str:
        bits: List[str] = []
        if self.collected.topic:
            bits.append(f"主题是“{self.collected.topic}”")
        if self.collected.teaching_goal:
            bits.append(f"目标是“{self.collected.teaching_goal}”")
        if self.collected.target_audience:
            bits.append(f"对象是“{self.collected.target_audience}”")
        return "；".join(bits)

    def _should_use_llm_collecting_pass(self, user_input: str) -> bool:
        """Use a short structured LLM pass for complex collecting turns."""
        if self._is_confirm_signal(user_input):
            return False
        return self._looks_complex_or_ambiguous(user_input)

    def _enhance_collected_with_llm(self, user_input: str) -> bool:
        """Run a short extraction-only cloud pass, then keep the reply local and fast."""
        current_snapshot = json.dumps(
            {
                "topic": self.collected.topic,
                "teaching_goal": self.collected.teaching_goal,
                "target_audience": self.collected.target_audience,
                "duration_minutes": self.collected.duration_minutes,
                "key_points": self.collected.key_points,
                "difficulties": self.collected.difficulties,
                "style": self.collected.style,
                "special_requirements": self.collected.special_requirements,
            },
            ensure_ascii=False,
        )
        extraction_prompt = (
            "Extract structured teaching requirements from the recent chat and the current teacher input.\n"
            "Return JSON only. If a field is unknown, keep it as an empty string, 0, or an empty array.\n"
            "Prefer preserving existing confirmed information, and only refine it when the new input is more specific.\n"
            "JSON schema:\n"
            "{\n"
            '  "topic": "",\n'
            '  "teaching_goal": "",\n'
            '  "target_audience": "",\n'
            '  "duration_minutes": 0,\n'
            '  "key_points": [],\n'
            '  "difficulties": [],\n'
            '  "style": "",\n'
            '  "special_requirements": ""\n'
            "}\n\n"
            f"Known fields:\n{current_snapshot}\n\n"
            f"Recent chat:\n{self._format_history(max_turns=6)}\n\n"
            f"Current teacher input:\n{user_input}"
        )
        try:
            raw = self.llm.generate(
                extraction_prompt,
                task="intent",
                max_tokens=min(self.dialogue_max_new_tokens, 220),
                temperature=0.0,
                expect_json=True,
                timeout_sec=min(self.dialogue_timeout_sec, 12),
                max_retries=0,
                cache=False,
            )
            data = json.loads(raw)
        except Exception:
            return False

        updated = False

        topic = str(data.get("topic", "") or "").strip()
        if topic and (not self.collected.topic or len(topic) > len(self.collected.topic)):
            self.collected.topic = topic
            updated = True

        teaching_goal = str(data.get("teaching_goal", "") or "").strip()
        if teaching_goal and (not self.collected.teaching_goal or len(teaching_goal) > len(self.collected.teaching_goal)):
            self.collected.teaching_goal = teaching_goal
            updated = True

        target_audience = str(data.get("target_audience", "") or "").strip()
        if target_audience and (
            not self.collected.target_audience
            or len(target_audience) > len(self.collected.target_audience)
        ):
            self.collected.target_audience = target_audience
            updated = True

        duration_minutes = data.get("duration_minutes", 0)
        if isinstance(duration_minutes, int) and duration_minutes > 0 and not self.collected.duration_minutes:
            self.collected.duration_minutes = duration_minutes
            updated = True

        style = str(data.get("style", "") or "").strip()
        if style and (not self.collected.style or len(style) > len(self.collected.style)):
            self.collected.style = style
            updated = True

        special_requirements = str(data.get("special_requirements", "") or "").strip()
        if special_requirements:
            if not self.collected.special_requirements:
                self.collected.special_requirements = special_requirements
                updated = True
            elif special_requirements not in self.collected.special_requirements:
                self.collected.special_requirements = (
                    f"{self.collected.special_requirements}; {special_requirements}"
                )
                updated = True

        for key, target in (("key_points", self.collected.key_points), ("difficulties", self.collected.difficulties)):
            values = data.get(key, [])
            if isinstance(values, list):
                for item in values:
                    text = str(item or "").strip()
                    if text and text not in target:
                        target.append(text)
                        updated = True

        return updated

    def _should_use_local_collecting_reply(
        self,
        user_input: str,
        *,
        previous_missing: List[str],
        current_missing: List[str],
    ) -> bool:
        """Use local slot-filling only for explicit slot values, not natural language requests."""
        if self._is_greeting_or_smalltalk(user_input):
            return False

        if self._looks_complex_or_ambiguous(user_input):
            return False

        filled_any_slot = len(current_missing) < len(previous_missing)
        short_direct_reply = len(user_input.strip()) <= 16
        goal_like_reply = bool(
            re.search(r"(学会|理解|掌握|能够|能|说出|口述|描述|解释|分析|比较|归纳|总结|完成)", user_input)
        )

        if re.search(r"(\d+)\s*分钟", user_input):
            return True
        if re.search(r"(高[一二三]|初[一二三]|[一二三四五六]年级)", user_input):
            return True
        if re.fullmatch(r"\s*(?:ppt|PPT|教案|docx|word|互动|游戏|动画)(?:\s*[/、,，+]\s*(?:ppt|PPT|教案|docx|word|互动|游戏|动画))*\s*", user_input):
            return True
        if goal_like_reply and not filled_any_slot:
            return False
        if self._looks_like_natural_language_request(user_input):
            return False

        return filled_any_slot and short_direct_reply

    @staticmethod
    def _is_greeting_or_smalltalk(text: str) -> bool:
        normalized = text.strip().lower()
        if not normalized:
            return False

        greeting_phrases = (
            "你好",
            "您好",
            "hi",
            "hello",
            "嗨",
            "在吗",
            "在不在",
            "有人吗",
            "帮我",
            "帮我备课",
            "帮我做课件",
            "想备课",
            "想做课件",
            "开始吧",
            "开始",
        )
        return any(phrase in normalized for phrase in greeting_phrases)

    @staticmethod
    def _looks_complex_or_ambiguous(text: str) -> bool:
        normalized = text.strip()
        if not normalized:
            return False

        if len(normalized) >= 28:
            return True

        complex_markers = (
            "但是", "不过", "同时", "并且", "此外", "另外", "最好", "希望", "想要",
            "风格", "参考", "按照", "模仿", "案例", "互动", "游戏", "动画", "重点",
            "难点", "修改", "调整", "不要", "而是", "加入", "增加", "减少", "结合",
            "如果", "能否", "可以帮我", "要求", "适合", "最好能",
        )
        if any(marker in normalized for marker in complex_markers):
            return True

        punctuation_count = sum(normalized.count(ch) for ch in ("，", "；", "。", ",", ";"))
        return punctuation_count >= 2

    @staticmethod
    def _looks_like_natural_language_request(text: str) -> bool:
        normalized = text.strip()
        if not normalized:
            return False

        natural_markers = (
            "我", "想", "希望", "需要", "关于", "内容", "过程", "原因", "特点", "意义", "详细",
            "如何", "为什么", "怎么", "请", "帮", "最好", "适合", "结合", "不要", "而是",
            "学会", "理解", "掌握", "能够", "说出", "口述", "描述", "解释", "分析", "比较", "归纳", "总结", "完成",
        )
        if any(marker in normalized for marker in natural_markers):
            return True

        return len(normalized) > 8

    def _format_history(self, max_turns: int = 20) -> str:
        recent = self.history[-max_turns * 2:]
        lines = []
        for msg in recent:
            role = "教师" if msg["role"] == "user" else "AI助手"
            lines.append(f"{role}: {msg['content']}")
        return "\n".join(lines)

    def _format_references(self) -> str:
        if not self.collected.reference_files:
            return ""
        parts = []
        for r in self.collected.reference_files:
            parts.append(f"[{r['file_name']}] ({r['file_type']})\n{r.get('text', '')[:2000]}")
        return "\n\n---\n\n".join(parts)

    def _format_references_brief(self) -> str:
        if not self.collected.reference_files:
            return ""
        return "\n".join(
            f"- {r['file_name']} ({r['file_type']}): {r.get('teacher_note', '无说明')}"
            for r in self.collected.reference_files
        )
