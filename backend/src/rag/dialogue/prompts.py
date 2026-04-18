"""
多轮对话 + 教学意图理解 Prompt 模板

对应 A04 要求:
  - 2b) 智能对话：能主动发起提问以澄清模糊需求，支持多轮对话，总结确认最终需求
  - 3a) 利用大模型技术，结构化提取教学要素
"""

from __future__ import annotations

# ────────────────────────────────────────────
# 1. 多轮对话 — 需求收集与追问
# ────────────────────────────────────────────
DIALOGUE_SYSTEM_PROMPT = """\
你是一位专业的教学课件设计助手。你的任务是通过自然对话，帮助教师精准表达他们的课件需求。

你需要收集以下关键信息（缺失项必须主动追问）：
1. 学科/课程名称
2. 具体知识点或章节
3. 教学目标（学生学完后应该掌握什么）
4. 教学对象（年级/水平）
5. 课时时长
6. 期望的课件类型（PPT / Word教案 / 互动游戏 / 全部）
7. 重点与难点
8. 教学风格偏好（严谨学术 / 生动活泼 / 案例驱动等）
9. 是否有参考资料需要融合

对话规则：
- 每次回复最多追问 2 个缺失信息，不要一次性问太多
- 对教师已给出的信息进行简要复述确认
- 当所有关键信息收集完毕后，输出结构化的需求总结，用 [READY] 标记
- 始终保持专业友好的语气
"""

DIALOGUE_TURN_PROMPT = """\
【对话历史】
{history}

【教师最新输入】
{user_input}

【已收集的信息】
{collected_info}

【参考资料摘要】（如有）
{reference_summary}

请根据对话历史和教师输入，做以下其中一件事：
1. 如果还有关键信息缺失 → 友好地追问（最多问 2 个问题）
2. 如果信息已基本完整 → 输出需求总结并请教师确认

你的回复：
"""

# ────────────────────────────────────────────
# 2. 需求确认总结
# ────────────────────────────────────────────
CONFIRM_SUMMARY_PROMPT = """\
根据以下对话历史和已收集的信息，生成一份结构化的教学需求总结。

【对话历史】
{history}

【已收集信息】
{collected_info}

【参考资料信息】
{reference_summary}

请严格按以下 JSON 格式输出：
{{
  "subject": "学科名称",
  "topic": "具体知识点/章节",
  "teaching_goal": "教学目标",
  "target_audience": "教学对象",
  "duration_minutes": 45,
  "output_types": ["ppt", "docx", "game"],
  "key_points": ["重点1", "重点2"],
  "difficulties": ["难点1", "难点2"],
  "style": "教学风格",
  "special_requirements": "其他特殊要求",
  "reference_notes": "参考资料使用说明"
}}
"""

# ────────────────────────────────────────────
# 3. 教学意图结构化提取
# ────────────────────────────────────────────
INTENT_EXTRACTION_PROMPT = """\
你是一位教学设计分析师。请从以下教师的对话和需求描述中，提取结构化的教学意图。

【教师输入/对话历史】
{dialogue_text}

【知识库检索结果】（如有）
{rag_context}

【参考资料内容】（如有）
{reference_content}

请严格按以下 JSON 格式输出，不要输出多余文字：
{{
  "subject": "学科",
  "grade_level": "年级/水平",
  "chapter": "章节名称",
  "knowledge_points": [
    {{
      "name": "知识点名称",
      "description": "简要描述",
      "importance": "核心/重要/了解",
      "related_points": ["关联知识点"]
    }}
  ],
  "teaching_logic": ["步骤1: ...", "步骤2: ...", "步骤3: ..."],
  "key_focus": ["重点内容"],
  "difficulties": ["难点内容"],
  "suggested_activities": ["建议的教学活动"],
  "content_blocks": [
    {{
      "title": "内容块标题",
      "type": "introduction/explanation/example/exercise/summary",
      "content_hint": "该块内容要点",
      "duration_minutes": 5
    }}
  ],
  "game_suggestions": [
    {{
      "type": "quiz/matching/sorting/fill_blank/true_false/flashcard/flow_fill",
      "topic": "对应知识点",
      "description": "游戏描述"
    }}
  ]
}}
"""

# ────────────────────────────────────────────
# 4. 参考资料内容解析指令
# ────────────────────────────────────────────
REFERENCE_ANALYSIS_PROMPT = """\
请分析以下参考资料的内容，提取对课件制作有用的信息。

【参考资料类型】{file_type}
【教师关于此资料的说明】{teacher_note}

【资料内容摘要】
{content}

请提取以下信息（JSON格式）：
{{
  "main_topics": ["主要知识点"],
  "content_structure": "内容组织结构描述",
  "key_examples": ["重要案例或示例"],
  "figures_description": ["图表/图片描述"],
  "style_notes": "排版/风格特点",
  "usable_content": ["可直接用于课件的内容片段"],
  "suggested_usage": "建议如何在课件中使用此资料"
}}
"""

# ────────────────────────────────────────────
# 5. 课件生成指令集
# ────────────────────────────────────────────
COURSEWARE_INSTRUCTION_PROMPT = """\
你是一位高级教学设计师。基于以下教学需求和知识内容，生成详细的课件制作指令。

【教学意图（结构化）】
{intent_json}

【知识库内容】
{rag_content}

【参考资料内容】
{reference_content}

请输出详细的课件制作指令（JSON），后续引擎将根据此指令生成PPT/Word/游戏：
{{
  "ppt_outline": {{
    "title": "课件标题",
    "slides": [
      {{
        "slide_number": 1,
        "type": "cover/toc/content/example/exercise/summary",
        "title": "幻灯片标题",
        "content_points": ["要点1", "要点2"],
        "speaker_notes": "演讲备注",
        "visual_suggestion": "视觉建议"
      }}
    ]
  }},
  "docx_outline": {{
    "title": "教案标题",
    "sections": [
      {{
        "heading": "节标题",
        "content": "内容描述"
      }}
    ]
  }},
  "games": [
    {{
      "type": "游戏类型",
      "knowledge_point": "对应知识点",
      "count": 5,
      "requirement": "具体要求"
    }}
  ]
}}
"""
