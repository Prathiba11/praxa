"""Where does a turn's time actually go - cold and warm?

    python scripts/profile_turn.py "What ISO 21434 work have I done?"

Every stage runs twice. The first pass pays whatever one-time cost it triggers -
opening the Chroma client, loading the embedder, loading the cross-encoder,
building the BM25 index. The second pass is the steady-state cost.

That distinction is the whole point. A Streamlit process pays the cold column
once at startup; every question after that pays only the warm column. Quoting
the cold number as "how slow the app is" would be wrong, and quoting the warm
number without saying startup exists would be dishonest.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable
from typing import Any

import torch

from career_copilot.core.config import get_settings
from career_copilot.core.errors import CopilotError
from career_copilot.core.llm import chat
from career_copilot.core.logging import configure_logging
from career_copilot.core.usage import new_session_id
from career_copilot.rag.query_analysis import analyse_query
from career_copilot.rag.rerank import rerank
from career_copilot.rag.retrieve import hybrid_search
from career_copilot.rag.translate import QueryPlan, expand_query

_PING = [{"role": "user", "content": "Reply with the single word: ok"}]


def _twice(call: Callable[[], Any]) -> tuple[float, float, Any]:
    """Run twice; return (cold_ms, warm_ms, second result)."""
    started = time.perf_counter()
    call()
    cold = (time.perf_counter() - started) * 1000

    started = time.perf_counter()
    value = call()
    warm = (time.perf_counter() - started) * 1000
    return cold, warm, value


def _threads() -> str:
    """One thread means the cross-encoder is running on a single core."""
    return f"torch threads: {torch.get_num_threads()}"


def _run(question: str) -> int:
    session_id = new_session_id()
    configure_logging()
    settings = get_settings()
    print(f"model:    {settings.chat_model}")
    print(f"question: {question}")
    print(f"{_threads()}\n")

    rows: list[tuple[str, float, float]] = []

    cold, warm, _ = _twice(lambda: chat(_PING, session_id=session_id, operation="profile-ping"))
    rows.append(("bare chat round-trip (network floor)", cold, warm))

    cold, warm, analysis = _twice(lambda: analyse_query(question, session_id=session_id))
    rows.append(("analyse_query (1 LLM call)", cold, warm))

    cold, warm, plan = _twice(lambda: expand_query(question, analysis=analysis))
    rows.append(("expand_query (1 LLM call)", cold, warm))
    print(f"  -> {len(plan.search_queries())} search queries")

    single = QueryPlan(original=question, keywords=analysis.keywords)
    cold, warm, one = _twice(lambda: hybrid_search(single))
    rows.append(("hybrid_search, 1 query", cold, warm))
    print(f"  -> {len(one)} candidates")

    cold, warm, many = _twice(lambda: hybrid_search(plan, where=analysis.where()))
    rows.append((f"hybrid_search, {len(plan.search_queries())} queries", cold, warm))
    print(f"  -> {len(many)} candidates")

    cold, warm, kept = _twice(lambda: rerank(question, many))
    rows.append((f"rerank, {len(many)} candidates", cold, warm))
    print(f"  -> {len(kept)} passages kept")

    width = max(len(label) for label, _, _ in rows)
    cold_total = sum(c for _, c, _ in rows)
    warm_total = sum(w for _, _, w in rows)

    print("\n" + "-" * (width + 26))
    print(f"{'stage':<{width}}  {'cold':>9}  {'warm':>9}")
    print("-" * (width + 26))
    for label, cold_ms, warm_ms in rows:
        print(f"{label:<{width}}  {cold_ms:>7.0f}ms  {warm_ms:>7.0f}ms")
    print("-" * (width + 26))
    print(f"{'sum':<{width}}  {cold_total:>7.0f}ms  {warm_total:>7.0f}ms")

    print(
        "\nThe cold column includes one-time startup (Chroma client, embedder,\n"
        "cross-encoder, BM25 index). Streamlit pays that once per process.\n"
        "A full chat turn adds two more model calls - roughly two more\n"
        "'bare chat round-trip' rows - plus a second analyse_query inside the tool."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Profile one retrieval turn, cold and warm.")
    parser.add_argument("question")
    args = parser.parse_args(argv)
    try:
        return _run(args.question)
    except CopilotError as exc:
        print(f"{exc.user_message}   ·   reference: {exc.correlation_id}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
