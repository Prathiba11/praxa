"""A/B comparison of retrieval strategies against a golden set.

    python scripts/compare_retrieval.py
    python scripts/compare_retrieval.py --verbose      # per-question detail
    python scripts/compare_retrieval.py --k 3          # stricter cut-off

Four configurations, each adding one technique to the last:

    naive            dense vector search on the raw question
    + translation    multi-query paraphrases and step-back
    + hybrid         BM25 fused with dense results via RRF
    + rerank         cross-encoder rescoring of the fused candidates

Metrics are deterministic - no LLM judge:

    hit@k  fraction of questions where an expected source appears in the top k
    MRR    mean reciprocal rank of the first expected source (1.0 = always #1)

Both are reported twice. **Document level** asks whether the right file was
found. **Section level** asks whether the right part of it was, which is the
question that matters for a document with eleven sections: retrieving
`llmops_and_safety.md` is not useful if the chunk is about cost accounting when
the question was about prompt injection.

Cost control: query analysis and translation run ONCE per question and the
results are reused across configurations. Twenty-eight questions costs two LLM
calls each, not eight.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from career_copilot.core.errors import CopilotError
from career_copilot.core.logging import configure_logging
from career_copilot.rag.query_analysis import analyse_query
from career_copilot.rag.rerank import rerank
from career_copilot.rag.retrieve import hybrid_search
from career_copilot.rag.translate import QueryPlan, expand_query

GOLDEN_SET = Path("tests/eval/golden_set.json")


@dataclass(frozen=True)
class Config:
    name: str
    translation: bool
    bm25: bool
    reranking: bool


CONFIGS = [
    Config("naive", translation=False, bm25=False, reranking=False),
    Config("+ translation", translation=True, bm25=False, reranking=False),
    Config("+ hybrid", translation=True, bm25=True, reranking=False),
    Config("+ rerank", translation=True, bm25=True, reranking=True),
]


@dataclass
class Score:
    hits: int = 0
    reciprocal_ranks: float = 0.0
    total: int = 0

    @property
    def hit_rate(self) -> float:
        return self.hits / self.total if self.total else 0.0

    @property
    def mrr(self) -> float:
        return self.reciprocal_ranks / self.total if self.total else 0.0

    def record(self, rank: int | None) -> None:
        self.total += 1
        if rank is not None:
            self.hits += 1
            self.reciprocal_ranks += 1.0 / rank


@dataclass
class Board:
    """One metric across every configuration."""

    label: str
    scores: dict[str, Score] = field(default_factory=dict)

    def score(self, name: str) -> Score:
        return self.scores.setdefault(name, Score())


def _source_of(item: Any) -> str:
    return str(item.metadata.get("source", ""))


def _section_of(item: Any) -> str:
    return str(item.metadata.get("section") or "")


def _document_rank(results: list[Any], expected: list[str]) -> int | None:
    """1-based rank of the first result from an expected file."""
    for rank, item in enumerate(results, start=1):
        if _source_of(item) in expected:
            return rank
    return None


def _section_rank(results: list[Any], expected: list[str], sections: list[str]) -> int | None:
    """1-based rank of the first result from an expected file AND section."""
    for rank, item in enumerate(results, start=1):
        if _source_of(item) in expected and _section_of(item) in sections:
            return rank
    return None


def _table(board: Board, k: int) -> None:
    print(f"\n### {board.label}\n")
    print("| strategy | hit@k | MRR |")
    print("|---|---|---|")
    for config in CONFIGS:
        score = board.score(config.name)
        print(f"| {config.name} | {score.hit_rate:.0%} | {score.mrr:.3f} |")

    baseline = board.score(CONFIGS[0].name)
    best = board.score(CONFIGS[-1].name)
    if baseline.mrr > 0:
        lift = (best.mrr - baseline.mrr) / baseline.mrr
        print(f"\nMRR change over naive retrieval: {lift:+.0%}")
    print(f"Found by the full pipeline, missed by naive: {best.hits - baseline.hits}")
    print(f"Scored over {best.total} question(s) at k = {k}")


def _run(args: argparse.Namespace) -> int:
    payload = json.loads(GOLDEN_SET.read_text(encoding="utf-8"))
    questions = payload["questions"]

    scored = [q for q in questions if q.get("expected")]
    probes = [q for q in questions if not q.get("expected")]

    documents = Board("Document level - was the right file retrieved?")
    sections = Board("Section level - was the right part of it retrieved?")
    detail: list[tuple[dict[str, Any], dict[str, int | None]]] = []

    print(f"\nEvaluating {len(scored)} questions at k={args.k}")
    if probes:
        print(f"({len(probes)} out-of-domain probe(s) excluded - the guardrail handles those)\n")

    for number, item in enumerate(scored, start=1):
        question: str = item["question"]
        expected: list[str] = item["expected"]
        expected_sections: list[str] = item.get("expected_sections") or []
        print(f"  [{number:2}/{len(scored)}] {question[:64]}")

        # Computed once, reused by every configuration that needs them.
        analysis = analyse_query(question)
        translated = expand_query(question, analysis=analysis, use_hyde=False)
        untranslated = QueryPlan(original=question, keywords=analysis.keywords)

        ranks: dict[str, int | None] = {}
        for config in CONFIGS:
            plan = translated if config.translation else untranslated
            candidates = hybrid_search(
                plan,
                where=analysis.where(),
                use_bm25=config.bm25,
                use_dense=True,
                final_k=max(args.k * 4, 20),
            )
            results = (
                rerank(question, candidates, top_k=args.k)
                if config.reranking
                else candidates[: args.k]
            )

            rank = _document_rank(results, expected)
            ranks[config.name] = rank
            documents.score(config.name).record(rank)

            if expected_sections:
                sections.score(config.name).record(
                    _section_rank(results, expected, expected_sections)
                )

        detail.append((item, ranks))

    # ---------------------------------------------------------------- report

    print("\n\n## Retrieval strategy comparison")
    print(f"\nGolden set: {len(scored)} scored questions | k = {args.k}")

    _table(documents, args.k)
    _table(sections, args.k)

    if args.verbose:
        print("\n\n### Rank of the first expected source (- = not found)\n")
        header = " | ".join(c.name for c in CONFIGS)
        print(f"| question | {header} |")
        print("|---|" + "---|" * len(CONFIGS))
        for item, ranks in detail:
            cells = " | ".join(
                str(ranks[c.name]) if ranks[c.name] is not None else "-" for c in CONFIGS
            )
            print(f"| {item['question'][:58]} | {cells} |")

        misses = [(item, ranks) for item, ranks in detail if ranks[CONFIGS[-1].name] is None]
        if misses:
            print("\n\n### Still missed by the full pipeline\n")
            for item, _ranks in misses:
                print(f"- **{item['question']}**")
                print(f"  expected: {', '.join(item['expected'])}")
                if item.get("why_hard"):
                    print(f"  why it is hard: {item['why_hard']}")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare retrieval strategies.")
    parser.add_argument("--k", type=int, default=5, help="cut-off for hit@k")
    parser.add_argument("--verbose", action="store_true", help="per-question ranks")
    args = parser.parse_args()

    configure_logging(level="ERROR")

    try:
        return _run(args)
    except CopilotError as exc:
        print(f"\nFAILED: {exc.user_message}\n  {exc.detail}", file=sys.stderr)
        return 1
    except FileNotFoundError:
        print(f"\nFAILED: golden set not found at {GOLDEN_SET}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
