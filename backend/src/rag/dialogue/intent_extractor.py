"""
教学意图理解与知识融合模块

对应 A04 要求:
  - 3a) 利用大模型，结构化提取教学要素（知识点清单、逻辑顺序、重点难点等）
  - 3b) 对上传参考资料进行内容解析
  - 3c) 将教师意图与参考资料、知识库信息有效融合，形成课件生成指令集
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .prompts import (
    CONFIRM_SUMMARY_PROMPT,
    COURSEWARE_INSTRUCTION_PROMPT,
    INTENT_EXTRACTION_PROMPT,
    REFERENCE_ANALYSIS_PROMPT,
)


@dataclass
class TeachingIntent:
    """结构化教学意图"""
    subject: str = ""
    grade_level: str = ""
    chapter: str = ""
    knowledge_points: List[Dict[str, Any]] = field(default_factory=list)
    teaching_logic: List[str] = field(default_factory=list)
    key_focus: List[str] = field(default_factory=list)
    difficulties: List[str] = field(default_factory=list)
    suggested_activities: List[str] = field(default_factory=list)
    content_blocks: List[Dict[str, Any]] = field(default_factory=list)
    game_suggestions: List[Dict[str, Any]] = field(default_factory=list)
    raw_json: Dict[str, Any] = field(default_factory=dict)

    def summary_text(self) -> str:
        lines = [
            f"学科: {self.subject}",
            f"年级: {self.grade_level}",
            f"章节: {self.chapter}",
            f"知识点: {', '.join(kp.get('name', '') for kp in self.knowledge_points)}",
            f"重点: {', '.join(self.key_focus)}",
            f"难点: {', '.join(self.difficulties)}",
            f"教学逻辑: {' → '.join(self.teaching_logic)}",
        ]
        return "\n".join(lines)


class IntentExtractor:
    """
    教学意图提取器。

    使用 LLM 从对话历史、RAG检索结果、参考资料中提取结构化教学意图，
    并融合成课件生成指令集。

    Example:
        extractor = IntentExtractor(config_path="config.yaml")
        intent = extractor.extract_intent(
            dialogue_text="我想做一节关于中心法则的课...",
            rag_context="中心法则是分子生物学的...",
        )
        print(intent.summary_text())
    """

    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = config_path
        self._generator = None

    @property
    def generator(self):
        if self._generator is None:
            from ..config import load_config
            from ..generator import GeneratorConfig, QwenGenerator
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
                temperature=float(g_cfg.get("temperature", 0.3)),
            ))
        return self._generator

    def _parse_json(self, raw: str) -> Dict[str, Any]:
        """从LLM响应中稳健地提取JSON"""
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

    # ─────────────────────────────────────────
    # 意图提取
    # ─────────────────────────────────────────

    def extract_intent(
        self,
        dialogue_text: str,
        rag_context: str = "",
        reference_content: str = "",
    ) -> TeachingIntent:
        """
        从对话文本中提取结构化教学意图。

        Args:
            dialogue_text: 教师的对话历史或需求描述
            rag_context: RAG检索到的知识库内容
            reference_content: 参考资料解析后的内容

        Returns:
            TeachingIntent 结构化对象
        """
        prompt = INTENT_EXTRACTION_PROMPT.format(
            dialogue_text=dialogue_text,
            rag_context=rag_context or "无",
            reference_content=reference_content or "无",
        )
        raw = self.generator.generate(prompt)
        data = self._parse_json(raw)

        return TeachingIntent(
            subject=data.get("subject", ""),
            grade_level=data.get("grade_level", ""),
            chapter=data.get("chapter", ""),
            knowledge_points=data.get("knowledge_points", []),
            teaching_logic=data.get("teaching_logic", []),
            key_focus=data.get("key_focus", []),
            difficulties=data.get("difficulties", []),
            suggested_activities=data.get("suggested_activities", []),
            content_blocks=data.get("content_blocks", []),
            game_suggestions=data.get("game_suggestions", []),
            raw_json=data,
        )

    # ─────────────────────────────────────────
    # 参考资料分析
    # ─────────────────────────────────────────

    def analyze_reference(
        self,
        content: str,
        file_type: str = "PDF",
        teacher_note: str = "",
    ) -> Dict[str, Any]:
        """
        分析参考资料内容。

        Args:
            content: 资料内容文本
            file_type: 文件类型
            teacher_note: 教师关于此资料的说明

        Returns:
            分析结果字典
        """
        prompt = REFERENCE_ANALYSIS_PROMPT.format(
            file_type=file_type,
            teacher_note=teacher_note or "无",
            content=content[:5000],  # 截断避免过长
        )
        raw = self.generator.generate(prompt)
        return self._parse_json(raw)

    # ─────────────────────────────────────────
    # 需求总结
    # ─────────────────────────────────────────

    def summarize_requirements(
        self,
        history: str,
        collected_info: str,
        reference_summary: str = "",
    ) -> Dict[str, Any]:
        """根据对话历史生成结构化需求总结"""
        prompt = CONFIRM_SUMMARY_PROMPT.format(
            history=history,
            collected_info=collected_info,
            reference_summary=reference_summary or "无",
        )
        raw = self.generator.generate(prompt)
        return self._parse_json(raw)

    # ─────────────────────────────────────────
    # 课件生成指令
    # ─────────────────────────────────────────

    def generate_instructions(
        self,
        intent: TeachingIntent,
        rag_content: str = "",
        reference_content: str = "",
    ) -> Dict[str, Any]:
        """
        基于教学意图生成课件制作指令集。

        Args:
            intent: 结构化教学意图
            rag_content: 知识库检索内容
            reference_content: 参考资料内容

        Returns:
            包含 ppt_outline, docx_outline, games 的指令字典
        """
        prompt = COURSEWARE_INSTRUCTION_PROMPT.format(
            intent_json=json.dumps(intent.raw_json, ensure_ascii=False, indent=2),
            rag_content=rag_content or "无",
            reference_content=reference_content or "无",
        )
        raw = self.generator.generate(prompt)
        return self._parse_json(raw)
