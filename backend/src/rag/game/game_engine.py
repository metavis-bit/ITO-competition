"""
GameEngine — 互动小游戏生成引擎

完整流程:
  1. 教师输入知识点 + 游戏类型 + 补充要求
  2. RAG 检索知识库相关证据
  3. LLM 根据证据 + prompt 生成结构化 JSON 游戏数据
  4. HTML5 模板渲染器将 JSON 渲染为可独立运行的 HTML5 游戏
  5. 输出 HTML 文件（可下载/嵌入PPT/在浏览器中运行）

对应 A04 赛题要求:
  - 4c) 内容生成多样性：应能根据教师要求生成知识点相关的互动小游戏
  - 5c) 动画或小游戏可以以html5网页导出或集成到PPT中
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .game_prompts import GAME_DESCRIPTIONS, GAME_PROMPTS
from .game_templates import GAME_RENDERERS


class GameType(str, Enum):
    QUIZ       = "quiz"
    MATCHING   = "matching"
    SORTING    = "sorting"
    FILL_BLANK = "fill_blank"
    TRUE_FALSE = "true_false"
    FLASHCARD  = "flashcard"
    FLOW_FILL  = "flow_fill"


class GameEngine:
    """
    互动小游戏生成引擎。

    可以两种方式使用：
    1. 独立使用（自带 LLM 调用）
    2. 与 RAGService 集成（先检索再生成）

    Example:
        # 独立使用
        engine = GameEngine(config_path="config.yaml")
        result = engine.generate(
            knowledge_topic="中心法则 - 转录过程",
            game_type=GameType.QUIZ,
            teacher_requirement="侧重于RNA聚合酶的作用",
            count=5,
        )
        print(result["html_path"])  # 生成的HTML5文件路径

        # 与 RAG 集成
        engine = GameEngine(config_path="config.yaml")
        result = engine.generate_with_rag(
            question="转录过程的步骤",
            game_type=GameType.SORTING,
            rag_service=svc,
            indexes=["kb"],
        )
    """

    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = config_path
        self._cfg = None
        self._generator = None

    @property
    def cfg(self) -> Dict[str, Any]:
        if self._cfg is None:
            from ..config import load_config
            self._cfg = load_config(self.config_path)
        return self._cfg

    @property
    def generator(self):
        """Lazy-load the LLM generator (same as RAG module uses)."""
        if self._generator is None:
            from ..generator import GeneratorConfig, QwenGenerator
            g_cfg = self.cfg.get("generator", {}) or {}
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

    # ─────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────

    @staticmethod
    def available_game_types() -> Dict[str, str]:
        """返回所有支持的游戏类型及其描述。"""
        return dict(GAME_DESCRIPTIONS)

    def generate(
        self,
        knowledge_topic: str,
        game_type: str | GameType,
        teacher_requirement: str = "",
        count: int = 5,
        context: str = "",
        output_dir: str = "outputs/games",
    ) -> Dict[str, Any]:
        """
        生成互动小游戏。

        Args:
            knowledge_topic: 知识点描述
            game_type:       游戏类型 (quiz/matching/sorting/...)
            teacher_requirement: 教师补充要求
            count:           题目数量
            context:         已有的知识文本（若为空则仅用 knowledge_topic）
            output_dir:      HTML 输出目录

        Returns:
            {
                "game_type": str,
                "title": str,
                "html": str,           # 完整 HTML 字符串
                "html_path": str,      # 保存的文件路径
                "game_data": dict,     # 结构化 JSON 数据
                "prompt_used": str,    # 使用的 prompt
                "generation_time": float,
            }
        """
        gt = game_type.value if isinstance(game_type, GameType) else str(game_type)
        if gt not in GAME_PROMPTS:
            raise ValueError(f"不支持的游戏类型: {gt}。支持: {list(GAME_PROMPTS.keys())}")

        # Build context from topic if not provided
        if not context.strip():
            context = f"知识点主题：{knowledge_topic}"

        # Prepare prompt
        prompt_template = GAME_PROMPTS[gt]
        prompt = prompt_template.format(
            context=context,
            teacher_requirement=teacher_requirement or "无特殊要求",
            count=count,
        )

        # Call LLM
        t0 = time.time()
        raw_response = self.generator.generate(prompt)
        gen_time = time.time() - t0

        # Parse JSON from LLM response
        game_data = self._parse_json_response(raw_response)

        # Render HTML
        renderer = GAME_RENDERERS.get(gt)
        if renderer is None:
            raise ValueError(f"No renderer for game type: {gt}")

        html_content = renderer(game_data)

        # Save to file
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_topic = re.sub(r'[^\w\u4e00-\u9fff]', '_', knowledge_topic)[:30]
        filename = f"game_{gt}_{safe_topic}_{ts}.html"
        filepath = str(Path(output_dir) / filename)
        Path(filepath).write_text(html_content, encoding="utf-8")

        return {
            "game_type": gt,
            "title": game_data.get("title", knowledge_topic),
            "html": html_content,
            "html_path": filepath,
            "game_data": game_data,
            "prompt_used": prompt,
            "generation_time": round(gen_time, 2),
        }

    def generate_with_rag(
        self,
        question: str,
        game_type: str | GameType,
        rag_service,
        indexes: Optional[List[str]] = None,
        top_k: int = 5,
        teacher_requirement: str = "",
        count: int = 5,
        output_dir: str = "outputs/games",
    ) -> Dict[str, Any]:
        """
        先通过 RAG 检索知识库，再基于检索到的证据生成游戏。

        Args:
            question:           检索用的问题
            game_type:          游戏类型
            rag_service:        RAGService 实例
            indexes:            要检索的索引列表
            top_k:              检索数量
            teacher_requirement: 教师补充要求
            count:              题目数量
            output_dir:         输出目录

        Returns:
            与 generate() 相同的结构 + "rag_evidence" 字段
        """
        if indexes is None:
            indexes = ["kb"]

        # Step 1: RAG 检索
        rag_result = rag_service.query(
            question=question,
            indexes=indexes,
            top_k=top_k,
        )

        # Step 2: 组装 context
        evidence_list = rag_result.get("evidence", [])
        context_parts = []
        for ev in evidence_list:
            text = ev.get("text", "") if isinstance(ev, dict) else str(ev)
            meta = ev.get("meta", {}) if isinstance(ev, dict) else {}
            source = meta.get("source", "") or meta.get("rel_path", "")
            if text.strip():
                context_parts.append(f"[来源: {source}]\n{text}")

        context = "\n\n".join(context_parts)
        if not context.strip():
            context = f"知识点主题：{question}"

        # Step 3: 生成游戏
        result = self.generate(
            knowledge_topic=question,
            game_type=game_type,
            teacher_requirement=teacher_requirement,
            count=count,
            context=context,
            output_dir=output_dir,
        )

        result["rag_evidence"] = evidence_list
        result["rag_answer"] = rag_result.get("answer", "")
        return result

    def generate_from_text(
        self,
        text: str,
        game_type: str | GameType,
        teacher_requirement: str = "",
        count: int = 5,
        output_dir: str = "outputs/games",
    ) -> Dict[str, Any]:
        """
        直接从教师提供的文本内容生成游戏（不经过 RAG）。

        适用场景：教师直接粘贴/上传了一段教材文本，想基于这段文本生成游戏。
        """
        return self.generate(
            knowledge_topic="教师提供的内容",
            game_type=game_type,
            teacher_requirement=teacher_requirement,
            count=count,
            context=text,
            output_dir=output_dir,
        )

    # ─────────────────────────────────────────
    # Internal helpers
    # ─────────────────────────────────────────

    def _parse_json_response(self, raw: str) -> Dict[str, Any]:
        """
        Robust JSON extraction from LLM response.
        Handles markdown code blocks, trailing commas, etc.
        """
        text = raw.strip()

        # Remove markdown code fences
        text = re.sub(r'^```(?:json)?\s*', '', text, flags=re.MULTILINE)
        text = re.sub(r'```\s*$', '', text, flags=re.MULTILINE)
        text = text.strip()

        # Try direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try to find JSON object in text
        match = re.search(r'\{[\s\S]*\}', text)
        if match:
            candidate = match.group(0)
            # Remove trailing commas before } or ]
            candidate = re.sub(r',\s*([}\]])', r'\1', candidate)
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass

        # Fallback: return minimal valid structure
        return {
            "title": "游戏（LLM 输出解析失败）",
            "questions": [],
            "pairs": [],
            "tasks": [],
            "cards": [],
            "nodes": [],
            "arrows": [],
            "blank_answers": {},
            "_raw_response": raw[:2000],
        }


# ─────────────────────────────────────────
# Convenience function
# ─────────────────────────────────────────

def create_game(
    knowledge_topic: str,
    game_type: str = "quiz",
    teacher_requirement: str = "",
    count: int = 5,
    config_path: str = "config.yaml",
    output_dir: str = "outputs/games",
) -> Dict[str, Any]:
    """One-shot convenience function."""
    engine = GameEngine(config_path=config_path)
    return engine.generate(
        knowledge_topic=knowledge_topic,
        game_type=game_type,
        teacher_requirement=teacher_requirement,
        count=count,
        output_dir=output_dir,
    )
