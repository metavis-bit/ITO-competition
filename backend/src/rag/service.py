from __future__ import annotations

import inspect
import json
from dataclasses import asdict, is_dataclass
from typing import Any, Dict, List, Optional, Sequence, Union

from .rag_engine import RAGEngine


# ----------------------------
# JSON / trace normalization
# ----------------------------
def _to_jsonable(obj: Any) -> Any:
    """Best-effort convert any object into JSON-serializable structure."""
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(x) for x in obj]
    if isinstance(obj, dict):
        return {str(k): _to_jsonable(v) for k, v in obj.items()}

    if is_dataclass(obj):
        try:
            return _to_jsonable(asdict(obj))
        except Exception:
            pass

    # pydantic v2
    if hasattr(obj, "model_dump") and callable(getattr(obj, "model_dump")):
        try:
            return _to_jsonable(obj.model_dump())
        except Exception:
            pass

    if hasattr(obj, "__dict__"):
        try:
            return _to_jsonable(vars(obj))
        except Exception:
            pass

    return str(obj)


def _trace_to_list_of_dict(trace: Any) -> List[Dict[str, Any]]:
    """
    Normalize trace to list[dict] for stable machine interface + JSON serialization.
    Supports:
      - TraceLog.as_dicts()
      - TraceLog._events (TraceEvent objects)
      - dict wrapper {"_events": [...]}
      - list[TraceEvent|dict]
    """
    if trace is None:
        return []

    # TraceLog.as_dicts()
    if hasattr(trace, "as_dicts") and callable(getattr(trace, "as_dicts")):
        try:
            v = _to_jsonable(trace.as_dicts())
            if isinstance(v, list):
                return [x if isinstance(x, dict) else {"value": str(x)} for x in v]
            if isinstance(v, dict):
                return [v]
            return [{"value": str(v)}]
        except Exception:
            pass

    # dict wrapper
    if isinstance(trace, dict):
        if "_events" in trace:
            return _trace_to_list_of_dict(trace.get("_events"))
        if "events" in trace:
            return _trace_to_list_of_dict(trace.get("events"))
        d = _to_jsonable(trace)
        return [d if isinstance(d, dict) else {"value": str(d)}]

    # list of events
    if isinstance(trace, list):
        out: List[Dict[str, Any]] = []
        for e in trace:
            ee = _to_jsonable(e)
            out.append(ee if isinstance(ee, dict) else {"value": str(ee)})
        return out

    # TraceLog._events
    if hasattr(trace, "_events"):
        try:
            return _trace_to_list_of_dict(getattr(trace, "_events"))
        except Exception:
            pass

    return [{"value": str(trace)}]


# ----------------------------
# Human-view rendering helpers
# ----------------------------
def _short(s: str, n: int = 140) -> str:
    s = (s or "").replace("\n", " ").strip()
    return s if len(s) <= n else (s[: n - 1] + "…")


def _meta_loc(meta: Dict[str, Any]) -> str:
    if not isinstance(meta, dict):
        return ""
    for k in ("page", "slide", "sheet", "frame_ts", "timestamp", "timecode", "loc"):
        v = meta.get(k)
        if v is not None and str(v).strip() != "":
            return str(v)
    ci = meta.get("chunk_index")
    cc = meta.get("chunk_count")
    if ci is not None:
        if cc is not None:
            return f"chunk {ci+1}/{cc}"
        return f"chunk {ci+1}"
    return ""


def _meta_source(meta: Dict[str, Any]) -> str:
    if not isinstance(meta, dict):
        return ""
    for k in ("source", "rel_path", "file_name"):
        v = meta.get(k)
        if v:
            return str(v)
    ap = meta.get("abs_path")
    if ap:
        return str(ap).split("/")[-1]
    return ""


def _render_sources_md(evidence: List[Dict[str, Any]]) -> str:
    if not evidence:
        return "（暂无证据来源）"
    lines = []
    seen = set()
    idx = 1
    for ev in evidence:
        meta = ev.get("meta") if isinstance(ev, dict) else {}
        src = _meta_source(meta or {})
        loc = _meta_loc(meta or {})
        key = (src, loc)
        if key in seen:
            continue
        seen.add(key)
        loc_part = f"（{loc}）" if loc else ""
        lines.append(f"{idx}. {src}{loc_part}")
        idx += 1
        if idx > 12:
            break
    return "\n".join(lines)


def _render_evidence_md(evidence: List[Dict[str, Any]]) -> str:
    if not evidence:
        return "未检索到可用证据。建议：上传相关资料或换一种问法。"
    header = "| # | 相关度 | 来源 | 位置 | 摘要 |\n|---:|:---:|---|---|---|\n"
    rows = []
    for i, ev in enumerate(evidence, 1):
        score = ev.get("score", "")
        score_s = f"{float(score):.4f}" if isinstance(score, (int, float)) else (str(score)[:8] if score else "")
        meta = ev.get("meta") if isinstance(ev, dict) else {}
        src = _meta_source(meta or {})
        loc = _meta_loc(meta or {})
        text = ev.get("text", "")
        rows.append(f"| {i} | {score_s} | {_short(src, 40)} | {_short(loc, 18)} | {_short(text, 120)} |")
        if i >= 8:
            break
    return header + "\n".join(rows)


def _render_trace_md(trace: List[Dict[str, Any]]) -> str:
    if not trace:
        return "（未记录 trace）"
    lines = []
    for e in trace:
        step = e.get("step", "")
        msg = e.get("message", "")
        data = e.get("data", None)
        if data is not None:
            try:
                data_s = json.dumps(data, ensure_ascii=False)
            except Exception:
                data_s = str(data)
            lines.append(f"- **{step}**：{msg}  \n  `{_short(data_s, 200)}`")
        else:
            lines.append(f"- **{step}**：{msg}")
    return "\n".join(lines)


def _build_human_view(question: str, answer: str, evidence: List[Dict[str, Any]], trace: List[Dict[str, Any]]) -> Dict[str, str]:
    sources_md = _render_sources_md(evidence)
    evidence_md = _render_evidence_md(evidence)
    trace_md = _render_trace_md(trace)
    answer_md = (
        "## ✅ 回答\n"
        f"{(answer or '').strip()}\n\n"
        "## 📌 证据来源\n"
        f"{sources_md}\n"
    )
    return {
        "question": question,
        "answer_md": answer_md,
        "evidence_md": evidence_md,
        "sources_md": sources_md,
        "trace_md": trace_md,
    }


# ----------------------------
# RAG service (stable machine fields + human_view)
# ----------------------------
class RAGService:
    """
    ✅ 对内：结构化稳定字段（answer/evidence/trace/subqueries...）
    ✅ 对外：human_view（中文美观易读）
    ✅ 自动开启 trace（解决你现在 trace 为空的问题）
    """

    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = config_path
        self.engine = RAGEngine(config_path)

    def list_indexes(self) -> List[str]:
        if hasattr(self.engine, "list_indexes") and callable(getattr(self.engine, "list_indexes")):
            try:
                v = list(self.engine.list_indexes())
                if v:
                    return v
            except Exception:
                pass

        idxs: List[str] = []
        try:
            from pymilvus import utility  # type: ignore
            cols = utility.list_collections()
            for c in cols:
                name = str(c)
                if name.endswith("_col"):
                    name = name[:-4]
                if name == "kb":
                    idxs.append("kb")
                elif name.startswith("ref_"):
                    idxs.append("ref:" + name[4:])
                else:
                    idxs.append(name)
        except Exception:
            pass

        if "kb" not in idxs:
            idxs.insert(0, "kb")

        seen = set()
        uniq: List[str] = []
        for x in idxs:
            if x and x not in seen:
                uniq.append(x)
                seen.add(x)
        return uniq

    def _call_engine_answer(
        self,
        question_text: str,
        idxs: List[str],
        top_k: Optional[int],
        evidence_tag: str,
        enable_trace: bool = True,   # ✅ 默认开启
    ):
        """
        关键修复点：自动把 trace/with_trace/return_trace 打开，让 engine 记录 trace。
        同时用 inspect.signature 只传 engine 支持的参数，避免 unexpected keyword。
        """
        fn = self.engine.answer
        sig = inspect.signature(fn)
        params = sig.parameters

        # 构造 kwargs
        kwargs: Dict[str, Any] = {}

        # question
        if "question" in params:
            kwargs["question"] = question_text
        elif "q" in params:
            kwargs["q"] = question_text

        # indexes
        if "indexes" in params:
            kwargs["indexes"] = idxs
        elif "index" in params:
            kwargs["index"] = idxs

        # top_k
        if top_k is not None and "top_k" in params:
            kwargs["top_k"] = top_k

        # evidence_tag（仅当支持时传）
        if "evidence_tag" in params:
            kwargs["evidence_tag"] = evidence_tag

        # ✅ 自动开启 trace：优先传 TraceLog 对象；不支持就传 with_trace=True
        tlog = None
        if enable_trace:
            try:
                from .utils.trace import TraceLog  # type: ignore
                tlog = TraceLog()
            except Exception:
                tlog = None

            if "trace" in params and tlog is not None:
                kwargs["trace"] = tlog
            elif "trace_log" in params and tlog is not None:
                kwargs["trace_log"] = tlog
            elif "with_trace" in params:
                kwargs["with_trace"] = True
            elif "return_trace" in params:
                kwargs["return_trace"] = True

        # 调用（带兜底：如果 trace 对象不匹配类型，则去掉再试）
        try:
            out = fn(**kwargs)  # type: ignore
        except TypeError:
            # 去掉 trace 对象再试（有些版本 trace 不是对象）
            kwargs.pop("trace", None)
            kwargs.pop("trace_log", None)
            if "with_trace" in params:
                kwargs["with_trace"] = True
            if "return_trace" in params:
                kwargs["return_trace"] = True
            out = fn(**kwargs)  # type: ignore

        # ✅ 如果 out.trace 为空但我们有 tlog，则把 tlog 的事件写回 out
        try:
            if tlog is not None:
                out_trace = getattr(out, "trace", None)
                if not out_trace:
                    setattr(out, "trace", getattr(tlog, "_events", None) or tlog)
        except Exception:
            pass

        return out

    def query(
        self,
        q: Optional[str] = None,
        indexes: Optional[List[str]] = None,
        evidence_tag: str = "ui",
        top_k: Optional[int] = None,
        # UI/旧调用兼容
        question: Optional[str] = None,
        index: Optional[Union[str, Sequence[str]]] = None,
        query: Optional[str] = None,
        enable_trace: bool = True,   # ✅ 默认开启
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        返回结构化稳定字段 + human_view（新增 human_view，不污染 machine 字段）
        """
        text = question or q or query or ""

        if indexes is not None:
            idxs = list(indexes)
        elif index is not None:
            idxs = [index] if isinstance(index, str) else list(index)
        else:
            idxs = ["kb"]

        out = self._call_engine_answer(text, idxs, top_k, evidence_tag, enable_trace=enable_trace)

        # normalize evidence/citations
        citations_obj = getattr(out, "citations", None)
        evidence_obj = getattr(out, "evidence", None)

        citations: List[Dict[str, Any]] = []
        if citations_obj:
            c = _to_jsonable(citations_obj)
            if isinstance(c, list):
                citations = [x if isinstance(x, dict) else {"value": str(x)} for x in c]
            elif isinstance(c, dict):
                citations = [c]
            else:
                citations = [{"value": str(c)}]

        evidence: List[Dict[str, Any]] = []
        if evidence_obj:
            e = _to_jsonable(evidence_obj)
            if isinstance(e, list):
                evidence = [x if isinstance(x, dict) else {"value": str(x)} for x in e]
            elif isinstance(e, dict):
                evidence = [e]
            else:
                evidence = [{"value": str(e)}]

        if not evidence and citations:
            evidence = citations
        if not citations and evidence:
            citations = evidence

        trace = _trace_to_list_of_dict(getattr(out, "trace", None))

        subqueries = _to_jsonable(getattr(out, "subqueries", []))
        if not isinstance(subqueries, list):
            subqueries = [subqueries]

        answer = getattr(out, "answer", "") or ""
        question_final = getattr(out, "question", text)
        indexes_final = getattr(out, "indexes", idxs)

        payload: Dict[str, Any] = {
            # ---- machine fields（稳定、结构化）----
            "schema_version": "1.0",
            "question": question_final,
            "indexes": indexes_final,
            "subqueries": subqueries,
            "answer": answer,
            "evidence": evidence,
            "citations": citations,
            "trace": trace,
            "retrieved_context": _to_jsonable(getattr(out, "retrieved_context", None)),
            "evidence_path": getattr(out, "evidence_path", None),
            "prompt": getattr(out, "prompt", None),

            # ---- human view（仅展示用，字符串）----
            "human_view": _build_human_view(question_final, answer, evidence, trace),
        }
        return payload
