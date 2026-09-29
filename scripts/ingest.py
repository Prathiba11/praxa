"""Build or refresh the vector index.

python scripts/ingest.py              # upsert changed content
python scripts/ingest.py --reset      # wipe and rebuild from scratch
python scripts/ingest.py --dry-run    # chunk only, no embedding, no writes
python scripts/ingest.py --stats      # what is currently indexed
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter

from career_copilot.core.errors import CopilotError
from career_copilot.core.logging import configure_logging
from career_copilot.rag.chunkers import Chunk, chunk_documents
from career_copilot.rag.loaders import load_all
from career_copilot.rag.store import VectorStore


def _summarise(chunks: list[Chunk]) -> None:
    by_source = Counter(c.source for c in chunks)
    by_type = Counter(str(c.doc_type) for c in chunks)
    by_profile = Counter(str(c.profile) for c in chunks if c.profile)

    print(f"\n{len(chunks)} chunks from {len(by_source)} documents\n")
    print("by type:    " + ", ".join(f"{k}={v}" for k, v in sorted(by_type.items())))
    print("by profile: " + ", ".join(f"{k}={v}" for k, v in sorted(by_profile.items())))
    print("\nper document:")
    for source, count in sorted(by_source.items()):
        print(f"  {count:4}  {source}")


def _run(args: argparse.Namespace) -> int:
    if args.stats:
        print(f"{VectorStore().count()} chunks indexed")
        return 0

    chunks = chunk_documents(load_all())
    _summarise(chunks)

    if args.dry_run:
        print("\ndry run - nothing written")
        return 0

    store = VectorStore()
    if args.reset:
        store.reset()
        print("\ncollection reset")

    print("\nembedding and indexing (first run downloads the model)...")
    store.add(chunks)
    print(f"done - {store.count()} chunks in the index")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Index the knowledge base.")
    parser.add_argument("--reset", action="store_true", help="delete the collection first")
    parser.add_argument("--dry-run", action="store_true", help="chunk only, do not embed")
    parser.add_argument("--stats", action="store_true", help="show index contents and exit")
    args = parser.parse_args()

    configure_logging(level="WARNING")

    try:
        return _run(args)
    except CopilotError as exc:
        print(f"\nFAILED: {exc.user_message}\n  {exc.detail}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
