from __future__ import annotations

import argparse
import json
from typing import Any, Dict, List

from .service import RAGService


def _print_human(res: Dict[str, Any], show_trace: bool = True) -> None:
    hv = res.get("human_view", {}) or {}
    q = hv.get("question", res.get("question", ""))

    print("============================================================")
    print("🧠 Edu-RAG（Human View）")
    print("============================================================")
    if q:
        print(f"【问题】{q}\n")

    print((hv.get("answer_md", "") or "").strip())
    print()

    print("## 📚 证据表格（摘要）")
    print((hv.get("evidence_md", "") or "").strip())
    print()

    print("## 🔗 证据来源（可引用）")
    print((hv.get("sources_md", "") or "").strip())
    print()

    if show_trace:
        print("## 🧾 Trace（检索过程，可解释）")
        print((hv.get("trace_md", "") or "").strip())
        print()


def _cmd_ingest(args: argparse.Namespace) -> None:
    svc = RAGService(args.config)
    if args.reset:
        svc.engine.reset_index(args.index)
    out = svc.engine.ingest_dir(
        index=args.index,
        dir_path=args.dir,
        source_type=args.source_type,
        session_id=args.session_id,
    )
    print(json.dumps(out, ensure_ascii=False, indent=2))


def _cmd_query(args: argparse.Namespace) -> None:
    svc = RAGService(args.config)

    indexes: List[str] = args.index or ["kb"]

    res = svc.query(
        question=args.question,
        indexes=indexes,
        top_k=args.top_k,
        evidence_tag="cli",
        enable_trace=(not args.no_trace),  # ✅ 默认有 trace
    )

    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        _print_human(res, show_trace=(not args.no_trace))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="edu-rag",
        description="Edu-RAG CLI (default: human_view; use --json for machine output)",
    )
    p.add_argument("--config", default="config.yaml", help="Path to config.yaml")

    sp = p.add_subparsers(dest="cmd", required=True)

    pin = sp.add_parser("ingest", help="Ingest files from a directory into an index")
    pin.add_argument("--dir", required=True, help="Directory containing files to ingest")
    pin.add_argument("--index", default="kb", help='Index name, e.g. "kb" or "ref:demo01"')
    pin.add_argument("--source-type", default="knowledge_base", help="Source type tag saved in metadata")
    pin.add_argument("--session-id", default="kb", help="Session id (e.g., kb or demo01)")
    pin.add_argument("--reset", action="store_true", help="Drop & rebuild the target index/collection")
    pin.set_defaults(func=_cmd_ingest)

    pq = sp.add_parser("query", help="Query the RAG system")
    pq.add_argument("--question", required=True, help="User question text")
    pq.add_argument(
        "--index",
        action="append",
        help='Index name (repeatable). Example: --index kb --index "ref:demo01"',
    )
    pq.add_argument("--top-k", type=int, default=5, help="How many evidence chunks to return")
    pq.add_argument("--no-trace", action="store_true", help="Hide trace in output")
    pq.add_argument("--json", action="store_true", help="Print machine JSON instead of human view")
    pq.set_defaults(func=_cmd_query)

    return p


def main(argv: List[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
