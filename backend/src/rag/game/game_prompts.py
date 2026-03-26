"""
LLM Prompt Templates for Game Content Generation.

Each prompt asks the LLM to return **strict JSON** so that the game engine
can deterministically render HTML5 games without fragile regex parsing.
"""

from __future__ import annotations

# ────────────────────────────────────────────
# 1. 选择题 Quiz
# ────────────────────────────────────────────
QUIZ_PROMPT = """\
你是一位经验丰富的教学设计专家。请根据以下【知识点材料】，为学生设计 {count} 道高质量的单选题。

【知识点材料】
{context}

【教师补充要求】
{teacher_requirement}

【输出要求】
请严格按照以下 JSON 格式输出，不要输出任何多余文字、注释或 Markdown 代码块标记：
{{
  "title": "本组题目的标题（简洁，如：中心法则基础测验）",
  "questions": [
    {{
      "id": 1,
      "stem": "题干文字",
      "options": ["A. 选项一", "B. 选项二", "C. 选项三", "D. 选项四"],
      "answer": "A",
      "explanation": "简要解析（1-2句话）"
    }}
  ]
}}
"""

# ────────────────────────────────────────────
# 2. 连线配对 Matching
# ────────────────────────────────────────────
MATCHING_PROMPT = """\
你是一位教学设计专家。请根据以下【知识点材料】，设计 {count} 组连线配对题。
每组包含左侧概念和右侧对应的定义/功能/描述，学生需要将左右正确配对。

【知识点材料】
{context}

【教师补充要求】
{teacher_requirement}

【输出要求】
请严格按照以下 JSON 格式输出，不要输出多余文字：
{{
  "title": "配对题标题",
  "pairs": [
    {{
      "left": "左侧概念（如：mRNA）",
      "right": "右侧定义（如：携带遗传信息从DNA到核糖体）"
    }}
  ]
}}
"""

# ────────────────────────────────────────────
# 3. 排序题 Sorting
# ────────────────────────────────────────────
SORTING_PROMPT = """\
你是一位教学设计专家。请根据以下【知识点材料】，设计 {count} 道排序题。
学生需要将打乱的步骤/环节按正确顺序排列。

【知识点材料】
{context}

【教师补充要求】
{teacher_requirement}

【输出要求】
请严格按照以下 JSON 格式输出，不要输出多余文字：
{{
  "title": "排序游戏标题",
  "tasks": [
    {{
      "id": 1,
      "description": "请将以下步骤按正确顺序排列",
      "correct_order": ["步骤1", "步骤2", "步骤3", "步骤4", "步骤5"]
    }}
  ]
}}

注意：correct_order 中的元素顺序就是正确顺序，游戏会自动打乱后让学生排列。
"""

# ────────────────────────────────────────────
# 4. 填空题 Fill-in-the-Blank
# ────────────────────────────────────────────
FILL_BLANK_PROMPT = """\
你是一位教学设计专家。请根据以下【知识点材料】，设计 {count} 道填空题。

【知识点材料】
{context}

【教师补充要求】
{teacher_requirement}

【输出要求】
请严格按照以下 JSON 格式输出，不要输出多余文字：
{{
  "title": "填空题标题",
  "questions": [
    {{
      "id": 1,
      "sentence": "DNA的双螺旋结构由____和____通过氢键连接。",
      "blanks": ["碱基对", "磷酸-脱氧核糖骨架"],
      "hint": "提示信息（可选）"
    }}
  ]
}}

注意：sentence 中用 ____ （四个下划线）表示空格位置，blanks 按顺序给出答案。
"""

# ────────────────────────────────────────────
# 5. 判断题 True/False
# ────────────────────────────────────────────
TRUE_FALSE_PROMPT = """\
你是一位教学设计专家。请根据以下【知识点材料】，设计 {count} 道判断题（对/错）。
需要一半左右的题目答案为"对"，一半为"错"，确保迷惑性和教育价值。

【知识点材料】
{context}

【教师补充要求】
{teacher_requirement}

【输出要求】
请严格按照以下 JSON 格式输出，不要输出多余文字：
{{
  "title": "判断题标题",
  "questions": [
    {{
      "id": 1,
      "statement": "陈述句",
      "answer": true,
      "explanation": "解析（1-2句话）"
    }}
  ]
}}
"""

# ────────────────────────────────────────────
# 6. 翻卡记忆 Flashcard Memory
# ────────────────────────────────────────────
FLASHCARD_PROMPT = """\
你是一位教学设计专家。请根据以下【知识点材料】，设计 {count} 张翻卡记忆卡片。
每张卡片正面是关键术语/概念，背面是定义/解释。

【知识点材料】
{context}

【教师补充要求】
{teacher_requirement}

【输出要求】
请严格按照以下 JSON 格式输出，不要输出多余文字：
{{
  "title": "记忆卡片标题",
  "cards": [
    {{
      "front": "正面：关键术语",
      "back": "背面：定义或解释"
    }}
  ]
}}
"""

# ────────────────────────────────────────────
# 7. 概念填图 / 流程图补全
# ────────────────────────────────────────────
FLOW_FILL_PROMPT = """\
你是一位教学设计专家。请根据以下【知识点材料】，设计一个流程图/概念图补全游戏。
提供一个生物学过程的流程，其中部分节点被挖空，学生需要填入正确内容。

【知识点材料】
{context}

【教师补充要求】
{teacher_requirement}

【输出要求】
请严格按照以下 JSON 格式输出，不要输出多余文字：
{{
  "title": "流程图补全游戏标题",
  "description": "简要说明这个流程的背景",
  "nodes": [
    {{
      "id": 1,
      "label": "DNA双链解开",
      "is_blank": false
    }},
    {{
      "id": 2,
      "label": "RNA聚合酶结合",
      "is_blank": true
    }}
  ],
  "arrows": [
    {{"from": 1, "to": 2, "label": "解旋酶作用"}}
  ],
  "blank_answers": {{
    "2": "RNA聚合酶结合启动子"
  }}
}}

注意：is_blank=true 的节点在游戏中会被隐藏，学生需要从选项中选择或拖拽填入。
"""

# ────────────────────────────────────────────
# Prompt registry
# ────────────────────────────────────────────
GAME_PROMPTS = {
    "quiz":       QUIZ_PROMPT,
    "matching":   MATCHING_PROMPT,
    "sorting":    SORTING_PROMPT,
    "fill_blank": FILL_BLANK_PROMPT,
    "true_false": TRUE_FALSE_PROMPT,
    "flashcard":  FLASHCARD_PROMPT,
    "flow_fill":  FLOW_FILL_PROMPT,
}

GAME_DESCRIPTIONS = {
    "quiz":       "选择题测验 — 单选题，答对得分，即时反馈",
    "matching":   "连线配对 — 拖拽连线，概念与定义配对",
    "sorting":    "排序游戏 — 将打乱的步骤拖拽至正确顺序",
    "fill_blank": "填空题 — 补全关键术语和概念",
    "true_false": "判断题 — 判断陈述正误，附带解析",
    "flashcard":  "翻卡记忆 — 翻转卡片记忆概念",
    "flow_fill":  "流程补全 — 在流程图中填入缺失环节",
}
