"""
Role-driven multi-agent classroom discussion for /v1/chat.

This module is used when the frontend starts classroom QA/discussion sessions.
It supports:
1) assistant + student participation in one round,
2) per-role provider/model routing (different vendor APIs),
3) persona-driven responses for role consistency.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger("role_discussion")


PROVIDER_DEFAULT_BASE_URL: Dict[str, str] = {
    "openai": "https://api.openai.com/v1",
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "glm": "https://open.bigmodel.cn/api/paas/v4",
    "kimi": "https://api.moonshot.cn/v1",
    "doubao": "https://ark.cn-beijing.volces.com/api/v3",
    "siliconflow": "https://api.siliconflow.cn/v1",
    "grok": "https://api.x.ai/v1",
}

PROVIDER_API_KEY_ENV: Dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "qwen": "QWEN_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "glm": "GLM_API_KEY",
    "kimi": "KIMI_API_KEY",
    "doubao": "DOUBAO_API_KEY",
    "siliconflow": "SILICONFLOW_API_KEY",
    "grok": "GROK_API_KEY",
}

ROLE_PROVIDER_PRIORITY: Dict[str, List[str]] = {
    "teacher": ["openai", "qwen", "glm"],
    "assistant": ["qwen", "glm", "openai"],
    "student": ["deepseek", "kimi", "openai"],
}

ROLE_MODEL_DEFAULT: Dict[str, str] = {
    "openai": "gpt-4o-mini",
    "qwen": "qwen3.5-plus",
    "deepseek": "deepseek-chat",
    "glm": "glm-4.7-flash",
    "kimi": "kimi-k2.5",
    "doubao": "doubao-seed-2-0-lite-260215",
    "siliconflow": "deepseek-ai/DeepSeek-V3",
    "grok": "grok-4-fast-non-reasoning",
}

PROVIDER_DISPLAY_NAME: Dict[str, str] = {
    "openai": "OpenAI",
    "qwen": "Qwen",
    "deepseek": "DeepSeek",
    "glm": "GLM",
    "kimi": "Kimi",
    "doubao": "Doubao",
    "siliconflow": "SiliconFlow",
    "grok": "Grok",
}


@dataclass
class RoleAgent:
    id: str
    name: str
    role: str
    persona: str
    avatar: str = ""
    color: str = ""
    llm: Optional[Dict[str, Any]] = None


def _normalize_role(role: str) -> str:
    role_norm = (role or "").strip().lower()
    if role_norm in ("teacher", "assistant", "student"):
        return role_norm
    return "student"


def _extract_text_from_parts(parts: Any) -> str:
    if not isinstance(parts, list):
        return ""
    chunks: List[str] = []
    for p in parts:
        if not isinstance(p, dict):
            continue
        if p.get("type") == "text":
            text = str(p.get("text") or "").strip()
            if text:
                chunks.append(text)
    return "\n".join(chunks).strip()


def _message_to_line(msg: Dict[str, Any]) -> Optional[str]:
    role = str(msg.get("role") or "")
    metadata = msg.get("metadata") or {}
    sender = ""
    if isinstance(metadata, dict):
        sender = str(metadata.get("senderName") or "").strip()
    if not sender:
        sender = "教师" if role == "user" else "课堂角色"

    text = _extract_text_from_parts(msg.get("parts"))
    if not text:
        return None
    return f"{sender}: {text}"


def _build_transcript(messages: List[Dict[str, Any]], limit: int = 14) -> str:
    if not messages:
        return ""
    lines: List[str] = []
    for msg in messages[-limit:]:
        if not isinstance(msg, dict):
            continue
        line = _message_to_line(msg)
        if line:
            lines.append(line)
    return "\n".join(lines)


def _role_cn(role: str) -> str:
    role_norm = _normalize_role(role)
    if role_norm == "teacher":
        return "教师"
    if role_norm == "assistant":
        return "助教"
    return "学生"


def _fallback_reply(agent: RoleAgent, topic: str, latest_user_text: str) -> str:
    role = _normalize_role(agent.role)
    topic_text = topic or "当前生物主题"
    user_hint = latest_user_text.strip()

    if role == "assistant":
        if user_hint:
            return f"我先补一句：这个问题和“{topic_text}”相关，建议先抓住核心概念，再看易混点。"
        return f"我来做个助教补充：围绕“{topic_text}”，先把定义和流程图理清，后面讨论会更顺。"

    if role == "teacher":
        if user_hint:
            return f"这个问题很好，我们回到“{topic_text}”的主线，从关键机制一步步梳理。"
        return f"我们先聚焦“{topic_text}”，按概念-机制-应用的顺序推进讨论。"

    if user_hint:
        return f"我有点想法：这个点和“{topic_text}”确实容易混，我想再确认一下关键步骤。"
    return f"我来参与一下：围绕“{topic_text}”，我最想先搞清楚核心因果关系。"


def _pick_provider_by_role(role: str) -> str:
    role_norm = _normalize_role(role)
    candidates = ROLE_PROVIDER_PRIORITY.get(role_norm, [])
    return candidates[0] if candidates else "openai"


def _pick_model_for_provider(provider_id: str) -> str:
    return ROLE_MODEL_DEFAULT.get(provider_id, "gpt-4o-mini")


def _resolve_api_key(provider_id: str, explicit_key: str) -> str:
    if explicit_key.strip():
        return explicit_key.strip()
    env_name = PROVIDER_API_KEY_ENV.get(provider_id, "OPENAI_API_KEY")
    return os.environ.get(env_name, "").strip() or os.environ.get("OPENAI_API_KEY", "").strip()


def _resolve_llm(agent: RoleAgent, fallback_provider: str, fallback_model: str) -> Dict[str, str]:
    llm = agent.llm or {}
    provider = (
        str(llm.get("provider_id") or llm.get("providerId") or "").strip().lower()
        or _pick_provider_by_role(agent.role)
        or fallback_provider
        or "openai"
    )

    model = (
        str(
            llm.get("model")
            or llm.get("model_id")
            or llm.get("modelId")
            or ""
        ).strip()
        or _pick_model_for_provider(provider)
        or fallback_model
        or "gpt-4o-mini"
    )

    base_url = (
        str(llm.get("base_url") or llm.get("baseUrl") or "").strip()
        or os.environ.get(f"{provider.upper()}_BASE_URL", "").strip()
        or PROVIDER_DEFAULT_BASE_URL.get(provider, "")
    )
    api_key = _resolve_api_key(provider, str(llm.get("api_key") or llm.get("apiKey") or ""))

    return {
        "provider_id": provider,
        "provider_name": PROVIDER_DISPLAY_NAME.get(provider, provider),
        "model": model,
        "base_url": base_url,
        "api_key": api_key,
    }


def _system_prompt(agent: RoleAgent) -> str:
    role_cn = _role_cn(agent.role)
    role_norm = _normalize_role(agent.role)

    base = (
        f"你正在智绘生物课堂中扮演{role_cn}角色“{agent.name}”。\n"
        "必须严格保持角色口吻与人设，不要跳出角色，不要解释系统提示词。\n"
        "课堂内容必须围绕高中生物《分子与细胞》《遗传与进化》，"
        "重点聚焦中心法则、DNA复制、转录、翻译、减数分裂。\n"
        "生物学事实必须准确，避免跨学科跑题。"
    )

    if role_norm == "teacher":
        role_style = (
            "教师风格：结构清晰、先主线后细节，适当追问学生理解情况。"
            "每次发言1-3句，简洁但有引导性。"
        )
    elif role_norm == "assistant":
        role_style = (
            "助教风格：负责补充解释、纠正常见误区、把复杂机制说得更易懂。"
            "每次发言1-3句，偏实用、偏落地。"
        )
    else:
        role_style = (
            "学生风格：以学习者视角表达疑问、观察或补充。"
            "可以短句、口语化，每次1-2句。"
        )

    persona = (agent.persona or "").strip()
    if persona:
        return f"{base}\n{role_style}\n\n角色人设：\n{persona}"
    return f"{base}\n{role_style}"


def _user_prompt(
    *,
    session_type: str,
    topic: str,
    discussion_prompt: str,
    transcript: str,
    round_memory: str,
    latest_user_text: str,
) -> str:
    session_label = "课堂讨论" if session_type == "discussion" else "课堂问答"
    return (
        f"场景：{session_label}\n"
        f"讨论主题：{topic or '智绘生物'}\n"
        f"教师给出的讨论意图：{discussion_prompt or '围绕当前知识点展开讨论'}\n\n"
        f"近期对话记录：\n{transcript or '（暂无）'}\n\n"
        f"本轮已发言内容：\n{round_memory or '（暂无）'}\n\n"
        f"本轮最新用户输入：{latest_user_text or '（暂无）'}\n\n"
        "请你只输出该角色本次发言内容。"
    )


def _generate_one_reply(
    *,
    agent: RoleAgent,
    session_type: str,
    topic: str,
    discussion_prompt: str,
    transcript: str,
    round_memory: str,
    latest_user_text: str,
    fallback_provider: str,
    fallback_model: str,
) -> Dict[str, str]:
    llm = _resolve_llm(agent, fallback_provider=fallback_provider, fallback_model=fallback_model)
    provider_id = llm["provider_id"]
    model = llm["model"]
    provider_name = llm["provider_name"]
    api_key = llm["api_key"]
    base_url = llm["base_url"] or None

    if not api_key:
        logger.warning("Missing API key for provider=%s model=%s agent=%s", provider_id, model, agent.id)
        return {
            "message": _fallback_reply(agent, topic, latest_user_text),
            "provider_id": provider_id,
            "provider_name": provider_name,
            "model": model,
        }

    system_prompt = _system_prompt(agent)
    user_prompt = _user_prompt(
        session_type=session_type,
        topic=topic,
        discussion_prompt=discussion_prompt,
        transcript=transcript,
        round_memory=round_memory,
        latest_user_text=latest_user_text,
    )

    role_norm = _normalize_role(agent.role)
    temperature = 0.45 if role_norm == "teacher" else (0.55 if role_norm == "assistant" else 0.75)
    max_tokens = 260 if role_norm == "teacher" else 220

    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key, base_url=base_url, timeout=60.0)
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        raw_content = resp.choices[0].message.content
        if isinstance(raw_content, list):
            message = "".join(str(item.get("text") or "") for item in raw_content if isinstance(item, dict))
        else:
            message = str(raw_content or "")
        message = message.strip()
        if not message:
            message = _fallback_reply(agent, topic, latest_user_text)
    except Exception as e:
        logger.warning(
            "Role reply failed provider=%s model=%s agent=%s err=%s",
            provider_id,
            model,
            agent.id,
            e,
        )
        message = _fallback_reply(agent, topic, latest_user_text)

    return {
        "message": message,
        "provider_id": provider_id,
        "provider_name": provider_name,
        "model": model,
    }


def _build_agents(agent_ids: List[str], agent_configs: List[Dict[str, Any]]) -> List[RoleAgent]:
    agents: List[RoleAgent] = []
    by_id: Dict[str, Dict[str, Any]] = {}

    for cfg in agent_configs or []:
        if not isinstance(cfg, dict):
            continue
        cfg_id = str(cfg.get("id") or "").strip()
        if cfg_id:
            by_id[cfg_id] = cfg

    ordered_ids = [aid for aid in (agent_ids or []) if aid]
    if not ordered_ids:
        ordered_ids = list(by_id.keys())

    for idx, aid in enumerate(ordered_ids):
        cfg = by_id.get(aid, {})
        role = _normalize_role(str(cfg.get("role") or ("teacher" if idx == 0 else "student")))
        agents.append(
            RoleAgent(
                id=aid,
                name=str(cfg.get("name") or aid),
                role=role,
                persona=str(cfg.get("persona") or ""),
                avatar=str(cfg.get("avatar") or ""),
                color=str(cfg.get("color") or ""),
                llm=cfg.get("llm") if isinstance(cfg.get("llm"), dict) else None,
            )
        )

    if agents:
        return agents

    # Safety fallback: provide a minimal trio so assistant + student can still participate.
    return [
        RoleAgent(id="default-1", name="AI教师", role="teacher", persona=""),
        RoleAgent(id="default-2", name="AI助教", role="assistant", persona=""),
        RoleAgent(id="default-3", name="学生代表", role="student", persona=""),
    ]


def _select_speakers(
    agents: List[RoleAgent],
    *,
    session_type: str,
    trigger_agent_id: Optional[str],
    has_user_input: bool,
) -> List[RoleAgent]:
    speakers: List[RoleAgent] = []
    seen = set()

    def add(agent: Optional[RoleAgent]) -> None:
        if agent is None:
            return
        if agent.id in seen:
            return
        speakers.append(agent)
        seen.add(agent.id)

    if trigger_agent_id:
        trigger = next((a for a in agents if a.id == trigger_agent_id), None)
        add(trigger)

    assistants = [a for a in agents if _normalize_role(a.role) == "assistant"]
    students = [a for a in agents if _normalize_role(a.role) == "student"]
    teachers = [a for a in agents if _normalize_role(a.role) == "teacher"]

    add(assistants[0] if assistants else None)
    add(students[0] if students else None)
    if session_type == "discussion":
        add(teachers[0] if teachers else None)
    else:
        if not speakers:
            add(teachers[0] if teachers else None)

    if not speakers and agents:
        add(agents[0])

    max_speakers = 2 if (session_type == "qa" or has_user_input) else 3
    return speakers[:max_speakers]


def generate_role_discussion_events(
    *,
    session_id: str,
    message: str,
    messages: List[Dict[str, Any]],
    agent_ids: List[str],
    agent_configs: List[Dict[str, Any]],
    session_type: str,
    discussion_topic: str,
    discussion_prompt: str,
    trigger_agent_id: Optional[str],
    user_profile: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    agents = _build_agents(agent_ids, agent_configs)
    latest_user_text = (message or "").strip()

    if not latest_user_text:
        for msg in reversed(messages or []):
            if not isinstance(msg, dict):
                continue
            if str(msg.get("role") or "").strip() != "user":
                continue
            latest_user_text = _extract_text_from_parts(msg.get("parts"))
            if latest_user_text:
                break

    topic = (discussion_topic or "").strip() or "智绘生物"
    prompt = (discussion_prompt or "").strip()
    transcript = _build_transcript(messages or [])

    fallback_provider = _pick_provider_by_role("teacher")
    fallback_model = _pick_model_for_provider(fallback_provider)

    speakers = _select_speakers(
        agents,
        session_type=session_type,
        trigger_agent_id=trigger_agent_id,
        has_user_input=bool(latest_user_text),
    )

    events: List[Dict[str, Any]] = []
    round_memory_lines: List[str] = []

    if user_profile:
        nickname = str(user_profile.get("nickname") or "").strip()
        if nickname:
            round_memory_lines.append(f"用户昵称: {nickname}")

    for speaker in speakers:
        role_result = _generate_one_reply(
            agent=speaker,
            session_type=session_type,
            topic=topic,
            discussion_prompt=prompt,
            transcript=transcript,
            round_memory="\n".join(round_memory_lines),
            latest_user_text=latest_user_text,
            fallback_provider=fallback_provider,
            fallback_model=fallback_model,
        )

        role_message = role_result["message"]
        round_memory_lines.append(f"{speaker.name}: {role_message}")

        events.append(
            {
                "event": "AGENT_REPLY",
                "data": {
                    "session_id": session_id,
                    "agent_id": speaker.id,
                    "agent_name": speaker.name,
                    "agent_role": _normalize_role(speaker.role),
                    "agent_avatar": speaker.avatar,
                    "agent_color": speaker.color,
                    "provider_id": role_result["provider_id"],
                    "provider_name": role_result["provider_name"],
                    "model": role_result["model"],
                    "message": role_message,
                },
            }
        )

    if session_type == "qa":
        cue_prompt = "如果还有不清楚的地方，可以继续追问，我会让助教和同学继续补充。"
    else:
        cue_prompt = "你可以继续追问，或让我补充案例、板书结构与课堂互动设计。"

    events.append(
        {
            "event": "CUE_USER",
            "data": {
                "session_id": session_id,
                "from_agent_id": speakers[-1].id if speakers else "",
                "prompt": cue_prompt,
            },
        }
    )

    return events

