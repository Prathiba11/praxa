"""The scoring behind the evaluation report.

These are the functions that turn retrieved passages into the numbers the
report states, and the report is the artefact that gets defended. A quietly
wrong `_rank_of` would not crash anything - it would produce a plausible table
that says the opposite of the truth, which is worse than a crash.

The script's expensive half (real retrieval, real grading) is not exercised
here. This covers the arithmetic and the wording, which are the parts that can
be wrong without anyone noticing.
"""

from __future__ import annotations

import pytest

from career_copilot.rag.pipeline import Source
from scripts.evaluate_grading import Outcome, Row, Score, _rank_of, _report, _tally


def _source(name: str, section: str | None = None, index: int = 1) -> Source:
    return Source(
        index=index,
        citation=f"{name}#{index}",
        source=name,
        section=section,
        score=0.9,
        found_by=["dense"],
        text="...",
    )


def _outcome(
    config: str, *, doc: int | None, section: int | None = None, rounds: int = 1
) -> Outcome:
    return Outcome(
        config=config,
        doc_rank=doc,
        section_rank=section,
        rounds=rounds,
        verdict="sufficient",
        graded=True,
        queries=["q"] * rounds,
        sources=[],
        latency_ms=1000.0,
        cost_usd=0.0001,
        calls=2,
    )


def _row(*, ungraded: int | None, graded: int | None, rounds: int = 1) -> Row:
    row = Row("a question", ["cv.md"], ["Experience"], "")
    row.outcomes["ungraded"] = _outcome("ungraded", doc=ungraded)
    row.outcomes["graded"] = _outcome("graded", doc=graded, rounds=rounds)
    return row


# ------------------------------------------------------------------- ranking


def test_the_rank_is_the_position_of_the_first_expected_document():
    sources = [_source("other.md"), _source("cv.md"), _source("cv.md")]

    assert _rank_of(sources, ["cv.md"], None, 5) == 2


def test_nothing_expected_in_the_top_k_is_a_miss():
    sources = [_source("other.md"), _source("another.md")]

    assert _rank_of(sources, ["cv.md"], None, 5) is None


def test_the_cut_off_is_respected():
    """A hit at position 4 is not a hit at k=3. That is the whole point of k."""
    sources = [_source("a.md"), _source("b.md"), _source("c.md"), _source("cv.md")]

    assert _rank_of(sources, ["cv.md"], None, 5) == 4
    assert _rank_of(sources, ["cv.md"], None, 3) is None


def test_a_section_hit_needs_the_right_document_too():
    """The right heading in the wrong file is a coincidence, not a hit.

    'Experience' appears in every CV in the set, so scoring it without checking
    the document would report near-perfect section retrieval no matter what the
    pipeline did.
    """
    sources = [_source("wrong.md", "Experience"), _source("cv.md", "Experience")]

    assert _rank_of(sources, ["cv.md"], ["Experience"], 5) == 2


def test_the_right_document_with_the_wrong_section_is_not_a_section_hit():
    sources = [_source("cv.md", "Education"), _source("cv.md", "Languages")]

    assert _rank_of(sources, ["cv.md"], None, 5) == 1
    assert _rank_of(sources, ["cv.md"], ["Experience"], 5) is None


def test_a_passage_with_no_section_never_matches_a_section():
    sources = [_source("cv.md", None)]

    assert _rank_of(sources, ["cv.md"], ["Experience"], 5) is None


def test_any_of_several_expected_documents_counts():
    sources = [_source("other.md"), _source("devops.md")]

    assert _rank_of(sources, ["automotive_cyber.md", "devops.md"], None, 5) == 2


# --------------------------------------------------------------------- score


def test_a_miss_lowers_the_hit_rate_without_touching_the_ranks():
    score = Score()
    score.record(1)
    score.record(None)

    assert score.hit_rate == 0.5
    assert score.mrr == 0.5  # (1/1 + 0) / 2


@pytest.mark.parametrize(("rank", "expected"), [(1, 1.0), (2, 0.5), (4, 0.25)])
def test_reciprocal_rank_rewards_being_near_the_top(rank, expected):
    score = Score()
    score.record(rank)

    assert score.mrr == pytest.approx(expected)


def test_an_empty_score_is_zero_rather_than_a_division_error():
    assert Score().hit_rate == 0.0
    assert Score().mrr == 0.0


# --------------------------------------------------------------------- tally


def test_each_configuration_is_tallied_separately():
    rows = [_row(ungraded=None, graded=1), _row(ungraded=2, graded=2)]

    scores = _tally(rows, "doc_rank")

    assert scores["ungraded"].hit_rate == 0.5
    assert scores["graded"].hit_rate == 1.0


def test_a_configuration_that_failed_on_a_question_is_not_counted_as_a_miss():
    """A crashed run is missing data, not a zero.

    Scoring it as a miss would make an outage look like a quality problem.
    """
    row = Row("q", ["cv.md"], [], "")
    row.outcomes["graded"] = _outcome("graded", doc=1)

    scores = _tally([row], "doc_rank")

    assert scores["graded"].total == 1
    assert scores["ungraded"].total == 0


# -------------------------------------------------------------------- report


def test_a_run_where_the_loop_never_fired_says_so_plainly():
    """The failure this report must never hide.

    If the grader approves every first round, both configurations retrieve
    identically and every table shows equal numbers. That looks like "no
    difference" and actually means "the feature did not run" - so the report
    has to say which of the two it is.
    """
    text = _report([_row(ungraded=1, graded=1), _row(ungraded=2, graded=2)], k=5)

    assert "**Nowhere.**" in text
    assert "it is evidence that it did not run" in text


def test_a_run_where_the_loop_fired_reports_that_subset():
    rows = [_row(ungraded=None, graded=1, rounds=2), _row(ungraded=1, graded=1)]

    text = _report(rows, k=5)

    assert "Where it actually fired" in text
    assert "re-queried questions only (n=1)" in text
    assert "**Nowhere.**" not in text


def test_the_report_states_the_cut_off_it_used():
    """A hit rate without its k is not a number anyone can check."""
    assert "k=3" in _report([_row(ungraded=1, graded=1)], k=3)


def test_the_report_carries_the_cost():
    text = _report([_row(ungraded=1, graded=1)], k=5)

    assert "What it cost" in text
    assert "$0.0002" in text  # two outcomes at $0.0001 each


# --------------------------------------------------------------- noise floor


def test_questions_where_the_loop_did_not_fire_measure_the_noise():
    """The control the first version of this report did not have.

    Grading judges round one; it does not change it. So on a question the
    grader approved immediately, the two configurations must retrieve the same
    passages - and any difference is the measurement moving under us. Without
    this number, a two-point gain in the headline table looks like a result
    when it may be smaller than the noise.
    """
    rows = [
        _row(ungraded=1, graded=1),  # agrees
        _row(ungraded=5, graded=1),  # differs, and cannot be the feature
        _row(ungraded=None, graded=1, rounds=2),  # fired: not part of the floor
    ]

    text = _report(rows, k=5)

    assert "How much of this is noise" in text
    assert "Questions where the loop did not fire: **2**" in text
    assert "the document rank still differed: **1** (**50%**)" in text


def test_a_clean_run_says_the_configurations_are_comparable():
    rows = [_row(ungraded=1, graded=1), _row(ungraded=2, graded=2)]

    text = _report(rows, k=5)

    assert "Nothing differed" in text
    assert "noise floor" not in text


def test_the_noise_floor_bounds_what_the_report_claims():
    rows = [_row(ungraded=3, graded=1), _row(ungraded=1, graded=1)]

    text = _report(rows, k=5)

    assert "bounds what can be claimed" in text
    assert "is not evidence of anything" in text


# ---------------------------------------------------------------------- cost


def test_calls_and_money_are_reported_next_to_latency():
    """Wall-clock is machine-specific; calls and cost are not.

    On the machine this was first run on, a call after the cross-encoder
    stalls for ~45 s, so the graded configuration - which makes more calls -
    looked thirty times slower than it is. The portable numbers have to be
    there, and the caveat has to be next to the number it applies to.
    """
    text = _report([_row(ungraded=1, graded=1)], k=5)

    assert "| configuration | model calls | cost | mean latency (this machine) |" in text
    assert "45 seconds" in text
    assert "not the cost of" in text or "Do not read the latency column" in text
