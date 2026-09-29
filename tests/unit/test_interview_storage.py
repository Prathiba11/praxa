"""The interview repository against a real SQLite file.

Not mocked: the things most likely to be wrong here are position assignment,
the foreign key, and the AVG aggregation, and a mock would confirm all three
whatever they did.
"""

from __future__ import annotations

import pytest

from career_copilot.core.types import Profile
from career_copilot.interview.rubric import RubricScore
from career_copilot.storage import interviews as repo
from career_copilot.storage import jobs as jobs_repo
from career_copilot.storage.db import StorageError, init_db, session_scope
from career_copilot.storage.models import Job


@pytest.fixture()
def database(isolated_settings):
    init_db()
    return isolated_settings


def _score(**overrides: float) -> RubricScore:
    base = dict.fromkeys(("structure", "specificity", "ownership", "impact", "relevance"), 3.0)
    base.update(overrides)
    return RubricScore(**base)


def _session(database, **overrides):
    kwargs = {"profile": Profile.DEVOPS, "persona": "tech_lead", "difficulty": "standard"}
    kwargs.update(overrides)
    return repo.start_session(**kwargs)


# ------------------------------------------------------------------ sessions


def test_a_session_exists_before_the_first_answer(database):
    """An abandoned session is still data about how you perform."""
    session = _session(database)
    assert repo.get_session(session.id) is not None
    assert repo.answer_count(session.id) == 0


def test_a_session_can_be_attached_to_a_job(database):
    job = jobs_repo.upsert_job(
        source="paste", title="SRE", company="Bosch", description="Kubernetes."
    )
    session = _session(database, job_id=job.id)
    assert repo.get_session(session.id).job_id == job.id


def test_answers_survive_the_job_being_deleted(database):
    """SET NULL, not CASCADE: how you performed against a posting outlives your
    interest in the posting."""
    job = jobs_repo.upsert_job(
        source="paste", title="SRE", company="Bosch", description="Kubernetes."
    )
    session = _session(database, job_id=job.id)
    repo.record_answer(session.id, question="q", answer="a", score=_score())

    with session_scope() as raw:
        raw.delete(raw.get(Job, job.id))

    reloaded = repo.get_session(session.id)
    assert reloaded is not None
    assert reloaded.job_id is None
    assert len(reloaded.answers) == 1


def test_recording_against_an_unknown_session_is_a_typed_error(database):
    with pytest.raises(StorageError, match="no interview session"):
        repo.record_answer("nope", question="q", answer="a", score=_score())


# ------------------------------------------------------------------ positions


def test_positions_are_assigned_by_the_repository(database):
    """The caller is a Streamlit page that re-runs on every click. Letting it
    own the counter is how you get two answers at position 3."""
    session = _session(database)
    for index in range(3):
        repo.record_answer(session.id, question=f"q{index}", answer="a", score=_score())

    positions = [answer.position for answer in repo.get_session(session.id).answers]
    assert positions == [1, 2, 3]


def test_probes_do_not_count_as_new_questions(database):
    session = _session(database)
    repo.record_answer(session.id, question="q1", answer="a", score=_score())
    repo.record_answer(session.id, question="follow up", answer="a", score=_score(), is_probe=True)
    repo.record_answer(session.id, question="q2", answer="a", score=_score())

    assert repo.questions_asked(session.id) == ["q1", "q2"]
    assert repo.answer_count(session.id) == 3
    assert repo.answer_count(session.id, probes=True) == 1


def test_word_count_is_derived_not_supplied(database):
    session = _session(database)
    answer = repo.record_answer(
        session.id, question="q", answer="four words right here", score=_score()
    )
    assert answer.word_count == 4


# ------------------------------------------------------------------ aggregation


def test_dimension_averages_average(database):
    session = _session(database)
    repo.record_answer(session.id, question="q1", answer="a", score=_score(impact=1.0))
    repo.record_answer(session.id, question="q2", answer="a", score=_score(impact=4.0))

    averages = repo.dimension_averages(session_id=session.id)
    assert averages["impact"] == 2.5
    assert averages["structure"] == 3.0


def test_averages_split_by_profile(database):
    devops = _session(database, profile=Profile.DEVOPS)
    cyber = _session(database, profile=Profile.AUTOMOTIVE_CYBER)
    repo.record_answer(devops.id, question="q", answer="a", score=_score(specificity=5.0))
    repo.record_answer(cyber.id, question="q", answer="a", score=_score(specificity=1.0))

    assert repo.dimension_averages(profile=Profile.DEVOPS)["specificity"] == 5.0
    assert repo.dimension_averages(profile=Profile.AUTOMOTIVE_CYBER)["specificity"] == 1.0


def test_averages_with_no_data_return_every_dimension_at_zero(database):
    """So a chart never has to cope with a missing series."""
    averages = repo.dimension_averages()
    assert set(averages) == {"structure", "specificity", "ownership", "impact", "relevance"}
    assert set(averages.values()) == {0.0}


def test_weakest_dimensions_are_worst_first(database):
    session = _session(database)
    repo.record_answer(
        session.id,
        question="q",
        answer="a",
        score=_score(impact=0.5, specificity=1.5, structure=5.0),
    )
    weakest = repo.weakest_dimensions(limit=2)
    assert [key for key, _ in weakest] == ["impact", "specificity"]


def test_finishing_stamps_the_summary_and_the_end_time(database):
    session = _session(database)
    assert repo.get_session(session.id).ended_at is None

    repo.finish_session(session.id, "You buried the result every time.")
    finished = repo.get_session(session.id)
    assert finished.ended_at is not None
    assert "buried" in finished.summary


def test_completed_only_filters_out_abandoned_sessions(database):
    done = _session(database)
    _session(database)
    repo.finish_session(done.id, "done")

    assert [s.id for s in repo.list_sessions(completed_only=True)] == [done.id]
    assert len(repo.list_sessions()) == 2


# ------------------------------------------------------------------ cross-session


def test_session_scores_are_oldest_first(database):
    """The chart plots left to right; the caller should not have to know to
    reverse a 'most recent N' query."""
    first = _session(database)
    repo.record_answer(first.id, question="q", answer="a", score=_score(impact=1.0))
    second = _session(database)
    repo.record_answer(second.id, question="q", answer="a", score=_score(impact=5.0))

    points = repo.session_scores()
    assert [point.session_id for point in points] == [first.id, second.id]
    assert [point.scores["impact"] for point in points] == [1.0, 5.0]


def test_session_scores_average_within_a_session(database):
    session = _session(database)
    repo.record_answer(session.id, question="q1", answer="a", score=_score(structure=2.0))
    repo.record_answer(session.id, question="q2", answer="a", score=_score(structure=4.0))

    point = repo.session_scores()[0]
    assert point.scores["structure"] == 3.0
    assert point.answers == 2


def test_a_session_with_no_answers_is_not_a_point_on_the_chart(database):
    """Clicking Start and walking away is not a data point."""
    _session(database)
    assert repo.session_scores() == []


def test_session_scores_respect_the_profile_filter(database):
    devops = _session(database, profile=Profile.DEVOPS)
    repo.record_answer(devops.id, question="q", answer="a", score=_score())
    cyber = _session(database, profile=Profile.AUTOMOTIVE_CYBER)
    repo.record_answer(cyber.id, question="q", answer="a", score=_score())

    assert [p.session_id for p in repo.session_scores(profile=Profile.DEVOPS)] == [devops.id]


def test_the_overall_is_the_mean_of_the_five(database):
    session = _session(database)
    repo.record_answer(
        session.id,
        question="q",
        answer="a",
        score=_score(structure=1.0, specificity=2.0, ownership=3.0, impact=4.0, relevance=5.0),
    )
    assert repo.session_scores()[0].overall == 3.0


def test_capture_comparison_separates_spoken_from_written(database):
    session = _session(database)
    repo.record_answer(session.id, question="q", answer="two words", score=_score(structure=1.0))
    repo.record_answer(
        session.id,
        question="q",
        answer="a much longer spoken answer here",
        score=_score(structure=5.0),
        captured_as="voice",
    )

    capture = repo.capture_comparison()
    assert capture["typed"]["structure"] == 1.0
    assert capture["voice"]["structure"] == 5.0
    assert capture["typed"]["words"] == 2.0
    assert capture["voice"]["words"] == 6.0


def test_capture_comparison_omits_a_mode_with_no_answers(database):
    """The page uses the key count to decide whether the comparison is meaningful."""
    session = _session(database)
    repo.record_answer(session.id, question="q", answer="a", score=_score())
    assert set(repo.capture_comparison()) == {"typed"}


def test_totals_count_probes_separately_but_include_them_in_answers(database):
    session = _session(database)
    repo.record_answer(session.id, question="q", answer="a", score=_score())
    repo.record_answer(session.id, question="p", answer="a", score=_score(), is_probe=True)

    assert repo.totals() == {"sessions": 1, "answers": 2, "probes": 1}


def test_totals_respect_the_profile_filter(database):
    devops = _session(database, profile=Profile.DEVOPS)
    repo.record_answer(devops.id, question="q", answer="a", score=_score())
    _session(database, profile=Profile.AI_ENG)

    assert repo.totals(profile=Profile.DEVOPS) == {"sessions": 1, "answers": 1, "probes": 0}
