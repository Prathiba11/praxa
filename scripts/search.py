"""Search the knowledge base directly - no LLM involved, just retrieval.

python scripts/search.py "what automotive security experience do I have?"
python scripts/search.py "kubernetes probes" --profile devops --k 3
python scripts/search.py "how should I quantify a STAR result?" --type guide
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from career_copilot.core.errors import CopilotError
from career_copilot.core.logging import configure_logging
from career_copilot.rag.store import VectorStore


def main() -> int:
    parser = argparse.ArgumentParser(description="Query the vector store.")
    parser.add_argument("query")
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--profile", choices=["automotive_cyber", "devops", "ai_eng"])
    parser.add_argument("--type", dest="doc_type", choices=["resume", "guide", "domain"])
    parser.add_argument("--full", action="store_true", help="print whole chunks")
    args = parser.parse_args()

    configure_logging(level="WARNING")

    filters: list[dict[str, Any]] = []
    if args.profile:
        filters.append({"profile": args.profile})
    if args.doc_type:
        filters.append({"doc_type": args.doc_type})

    where: dict[str, Any] | None = None
    if len(filters) == 1:
        where = filters[0]
    elif filters:
        where = {"$and": filters}

    try:
        hits = VectorStore().search(args.query, k=args.k, where=where)
    except CopilotError as exc:
        print(f"FAILED: {exc.user_message}\n  {exc.detail}", file=sys.stderr)
        return 1

    if not hits:
        print("no results")
        return 0

    print(f'\nQuery: "{args.query}"' + (f"   filter: {where}" if where else "") + "\n")
    for rank, hit in enumerate(hits, start=1):
        body = hit.text if args.full else hit.text[:280].replace("\n", " ")
        print(f"[{rank}] {hit.score:.3f}  {hit.citation}")
        print(f"     {body}{'' if args.full else '...'}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
