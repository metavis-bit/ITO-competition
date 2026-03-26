"""
Schema normalizer 鈥?the firewall between LLM chaos and deterministic generation.

Takes raw LLM JSON output (which may have missing keys, wrong types, extra fields,
markdown-contaminated strings) and produces a validated CoursewarePlan.

This is the HIGHEST-VALUE single component: without it, generators crash on
malformed LLM output. With it, they always receive typed, validated data.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from ..domain.models import (
    CoursewarePlan,
    GameTypeEnum,
    SlideSpec,
    TeachingIntent,
)

logger = logging.getLogger("schema_normalizer")

_VALID_LAYOUTS = {"cover", "toc", "content", "summary", "interactive"}

_GAME_TYPE_ALIASES: Dict[str, str] = {
    "quiz": "quiz",
    "测验": "quiz",
    "娴嬮獙": "quiz",
    "matching": "matching",
    "连连看": "matching",
    "杩炶繛鐪?": "matching",
    "sorting": "sorting",
    "分类": "sorting",
    "鍒嗙被": "sorting",
    "fill_blank": "fill_blank",
    "填空": "fill_blank",
    "濉┖": "fill_blank",
    "true_false": "true_false",
    "判断": "true_false",
    "鍒ゆ柇": "true_false",
    "flashcard": "flashcard",
    "闪卡": "flashcard",
    "闂崱": "flashcard",
    "flow_fill": "flow_fill",
    "流程填空": "flow_fill",
    "娴佺▼濉┖": "flow_fill",
}


class SchemaNormalizer:
    """
    Validates and repairs raw LLM output into typed domain models.

    Usage:
        normalizer = SchemaNormalizer()
        plan = normalizer.normalize_plan(raw_json_str, intent)
    """

    def normalize_plan(
        self,
        raw_json: str,
        intent: TeachingIntent,
    ) -> CoursewarePlan:
        """
        Parse and normalize raw LLM JSON into a CoursewarePlan.

        Steps:
          1. Parse JSON (strip markdown fences, handle truncation)
          2. Extract and normalize slides
          3. Extract and normalize lesson plan sections
          4. Extract and normalize game specs
          5. Clamp slide count to intent.page_range
          6. Return typed CoursewarePlan
        """
        data = self._parse_raw(raw_json)

        # Normalize slides
        raw_slides = data.get("slides") or data.get("ppt_outline") or data.get("outline") or []
        if isinstance(raw_slides, dict):
            # Sometimes LLM wraps slides in a dict: {"slides": [...]}
            raw_slides = raw_slides.get("slides", [raw_slides])
        slides = [self.normalize_slide_spec(s, i) for i, s in enumerate(raw_slides)]

        # Auto-add cover and summary if missing
        if slides and slides[0].layout != "cover":
            cover = SlideSpec(
                slide_number=0,
                title=intent.topic or intent.chapter or "课程封面",
                layout="cover",
            )
            slides.insert(0, cover)

        # Clamp slide count
        slides = self._clamp_slides(slides, intent.page_range)

        # Re-number slides
        for i, s in enumerate(slides):
            s.slide_number = i + 1

        # Normalize lesson plan sections
        sections = data.get("lesson_plan_sections") or data.get("docx_outline") or data.get("sections") or []
        if isinstance(sections, dict):
            sections = [sections]

        # Normalize game specs
        raw_games = data.get("game_specs") or data.get("games") or []
        if isinstance(raw_games, dict):
            raw_games = [raw_games]
        game_specs = [
            self.normalize_game_spec(g, intent.topic or intent.chapter)
            for g in raw_games
        ]

        # Animation steps (pass through)
        animation_steps = data.get("animation_steps") or data.get("animations") or []

        return CoursewarePlan(
            intent=intent,
            slides=slides,
            lesson_plan_sections=sections,
            game_specs=game_specs,
            animation_steps=animation_steps,
            raw_llm_output=raw_json,
            plan_version=1,
        )

    def normalize_slide_spec(self, raw: Any, index: int) -> SlideSpec:
        """
        Normalize a single slide dict into SlideSpec.

        Handles:
          - Missing title (fallback: "Slide {index}")
          - bullet_points as string instead of list
          - Invalid layout values
          - HTML/markdown in text fields
        """
        if isinstance(raw, str):
            return SlideSpec(
                slide_number=index + 1,
                title=raw.strip() or f"Slide {index + 1}",
                layout="content",
            )

        if not isinstance(raw, dict):
            return SlideSpec(slide_number=index + 1, title=f"Slide {index + 1}")

        # Title
        title = str(
            raw.get("title")
            or raw.get("标题")
            or raw.get("鏍囬")
            or f"Slide {index + 1}"
        ).strip()
        title = self._clean_text(title)

        # Bullet points
        points = (
            raw.get("bullet_points")
            or raw.get("points")
            or raw.get("内容")
            or raw.get("鍐呭")
            or raw.get("content")
            or []
        )
        if isinstance(points, str):
            points = [p.strip() for p in points.split("\n") if p.strip()]
        elif isinstance(points, list):
            points = [self._clean_text(str(p)) for p in points if str(p).strip()]

        # Notes
        notes = str(raw.get("notes") or raw.get("备注") or raw.get("澶囨敞") or "")
        notes = self._clean_text(notes)

        # Layout
        layout = str(raw.get("layout") or raw.get("type") or "content").lower().strip()
        if layout not in _VALID_LAYOUTS:
            layout = "content"

        # Visual suggestion
        visual = str(
            raw.get("visual_suggestion")
            or raw.get("visual")
            or raw.get("图片建议")
            or raw.get("鍥剧墖寤鸿")
            or ""
        )

        return SlideSpec(
            slide_number=index + 1,
            title=title,
            bullet_points=points,
            notes=notes,
            layout=layout,
            visual_suggestion=visual,
        )

    def normalize_game_spec(self, raw: Any, fallback_topic: str) -> Dict[str, Any]:
        """
        Normalize a single game spec dict.

        Ensures:
          - 'type' is a valid GameTypeEnum value
          - 'questions' is a list with required sub-keys
          - question text is clean (no HTML)
          - IDs are auto-generated if missing
        """
        if not isinstance(raw, dict):
            return {"type": "quiz", "topic": fallback_topic, "questions": []}

        # Normalize game type
        raw_type = str(
            raw.get("type")
            or raw.get("game_type")
            or raw.get("类型")
            or raw.get("绫诲瀷")
            or "quiz"
        ).lower().strip()
        game_type = _GAME_TYPE_ALIASES.get(raw_type, raw_type)
        try:
            GameTypeEnum(game_type)
        except ValueError:
            logger.warning("Unknown game type '%s', defaulting to 'quiz'", raw_type)
            game_type = "quiz"

        # Normalize questions
        questions = raw.get("questions") or raw.get("题目") or raw.get("棰樼洰") or []
        if isinstance(questions, dict):
            questions = [questions]
        normalized_questions = []
        for i, q in enumerate(questions):
            if isinstance(q, str):
                q = {"question": q}
            elif not isinstance(q, dict):
                continue
            nq = {
                "id": q.get("id", f"q_{i + 1}"),
                "question": self._clean_text(
                    str(q.get("question") or q.get("题目") or q.get("棰樼洰") or "")
                ),
            }
            # Preserve other fields (options, answer, explanation, etc.)
            for k, v in q.items():
                if k not in nq:
                    nq[k] = v
            if nq["question"]:
                normalized_questions.append(nq)

        result = {
            "type": game_type,
            "topic": str(raw.get("topic") or raw.get("主题") or raw.get("涓婚") or fallback_topic),
            "questions": normalized_questions,
        }
        # Preserve other fields
        for k, v in raw.items():
            if k not in (
                "type",
                "game_type",
                "类型",
                "绫诲瀷",
                "topic",
                "主题",
                "涓婚",
                "questions",
                "题目",
                "棰樼洰",
            ):
                result[k] = v

        return result

    def _parse_raw(self, raw_json: str) -> Dict[str, Any]:
        """Parse JSON string with markdown fence stripping and error recovery."""
        text = raw_json.strip()

        # Strip markdown fences
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
        text = re.sub(r"```\s*$", "", text, flags=re.MULTILINE)
        text = text.strip()

        # Fix unescaped newlines inside JSON string values
        # Replace literal newlines inside strings with \\n
        text = self._fix_json_newlines(text)

        # Try direct parse
        try:
            result = json.loads(text)
            if isinstance(result, dict):
                return result
            if isinstance(result, list):
                return {"slides": result}
            return {}
        except json.JSONDecodeError:
            pass

        # Find first { ... } block
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            candidate = match.group(0)
            candidate = re.sub(r",\s*([}\]])", r"\1", candidate)
            try:
                result = json.loads(candidate)
                if isinstance(result, dict):
                    return result
            except json.JSONDecodeError:
                pass

        # Find first [ ... ] block (list of slides)
        match = re.search(r"\[[\s\S]*\]", text)
        if match:
            candidate = match.group(0)
            candidate = re.sub(r",\s*([}\]])", r"\1", candidate)
            try:
                result = json.loads(candidate)
                if isinstance(result, list):
                    return {"slides": result}
            except json.JSONDecodeError:
                pass

        # Last resort: try to repair truncated JSON by closing open brackets
        repaired = self._repair_truncated_json(text)
        if repaired:
            return repaired

        logger.error("Failed to parse LLM output as JSON (first 300 chars): %s", text[:300])
        return {}

    @staticmethod
    def _repair_truncated_json(text: str) -> Optional[Dict[str, Any]]:
        """Attempt to repair JSON truncated by max_tokens limit."""
        # Find the start of JSON
        start = -1
        for i, ch in enumerate(text):
            if ch in ('{', '['):
                start = i
                break
        if start < 0:
            return None

        fragment = text[start:]
        # Remove trailing comma and whitespace
        fragment = re.sub(r",\s*$", "", fragment)

        # Count open brackets and detect whether we ended inside a JSON string.
        stack = []
        in_string = False
        escape = False
        for ch in fragment:
            if escape:
                escape = False
                continue
            if ch == '\\':
                escape = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch in ('{', '['):
                stack.append(ch)
            elif ch == '}' and stack and stack[-1] == '{':
                stack.pop()
            elif ch == ']' and stack and stack[-1] == '[':
                stack.pop()

        # If output ended while escaping (e.g. trailing backslash), drop the orphan slash.
        if fragment.endswith('\\'):
            slash_count = 0
            for ch in reversed(fragment):
                if ch == '\\':
                    slash_count += 1
                else:
                    break
            if slash_count % 2 == 1:
                fragment = fragment[:-1]

        # If output ended inside a string value, close the quote first.
        if in_string:
            fragment += '"'

        # Clean up dangling comma before synthetic closing braces/brackets.
        fragment = re.sub(r",\s*$", "", fragment)

        # Close unclosed brackets
        closing = ""
        for bracket in reversed(stack):
            closing += ']' if bracket == '[' else '}'

        candidate = fragment + closing
        candidate = re.sub(r",\s*([}\]])", r"\1", candidate)
        try:
            result = json.loads(candidate)
            if isinstance(result, dict):
                logger.warning(
                    "Repaired truncated JSON (%d unclosed brackets, closed_string=%s)",
                    len(stack),
                    in_string,
                )
                return result
            if isinstance(result, list):
                return {"slides": result}
        except json.JSONDecodeError:
            pass
        return None

    @staticmethod
    def _fix_json_newlines(text: str) -> str:
        """Replace literal newlines inside JSON string values with \\n.

        LLMs sometimes output multi-line strings without proper escaping,
        which breaks json.loads(). We scan the text character-by-character
        and replace raw newlines found inside quoted strings.
        """
        result = []
        in_string = False
        escape = False
        for ch in text:
            if escape:
                result.append(ch)
                escape = False
                continue
            if ch == '\\' and in_string:
                result.append(ch)
                escape = True
                continue
            if ch == '"':
                in_string = not in_string
                result.append(ch)
                continue
            if in_string and ch == '\n':
                result.append('\\n')
                continue
            if in_string and ch == '\r':
                continue  # drop \r inside strings
            if in_string and ch == '\t':
                result.append('\\t')
                continue
            result.append(ch)
        return ''.join(result)

    @staticmethod
    def _clean_text(text: str) -> str:
        """Remove HTML tags and excessive whitespace from text."""
        text = re.sub(r"<[^>]+>", "", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    @staticmethod
    def _clamp_slides(slides: List[SlideSpec], page_range: str) -> List[SlideSpec]:
        """Clamp slide count to the range specified in intent."""
        clean_range = re.sub(r"[^0-9\-]", "", page_range or "")
        try:
            parts = [p.strip() for p in clean_range.split("-") if p.strip()]
            if len(parts) >= 2:
                max_pages = int(parts[-1])
            elif len(parts) == 1:
                max_pages = int(parts[0])
            else:
                max_pages = 20
        except (ValueError, IndexError):
            max_pages = 20  # safe default

        if len(slides) > max_pages:
            logger.info("Clamping slides from %d to %d", len(slides), max_pages)
            slides = slides[:max_pages]

        return slides


