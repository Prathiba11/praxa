"""A whole interview, against a real database and a scripted model.

The unit tests prove the transition rule is correct in isolation. This proves
the parts are wired together: that a probe is stored as a probe and does not
consume a question slot, that the session ends by itself, that the debrief sees
the real transcript, and that what lands in the database is what the Progress
page will later average.

The model is scripted rather than mocked per-call, so the test exercises the
same `submit_answer` the Interview page calls, in the same order.
"""

from __future__ import annotations

import json

import pytest

from career_copilot.core.types import Profile
from career_copilot.interview import questions as questions_module
from career_copilot.interview import rubric as rubric_module
from career_copilot.interview import session as session_module
from career_copilot.interview.engine import Move, Plan
from career_copilot.interview.personas import Difficulty, get_persona
from career_copilot.storage import interviews as repo
from career_copilot.storage.db import init_db
from tests.helpers import make_chat_result

_STRONG = dict.fromkeys(("structure", "specificity", "ownership", "impact", "relevance"), 5) | {
    "feedback": "Strong.",
    "improved_answer": "",
    "probe": "",
}

_WEAK = dict.fromkeys(("structure", "specificity", "ownership", "impact", "relevance"), 1) | {
    "feedback": "No detail.",
    "improved_answer": "",
    "probe": "Which cluster, and how many nodes?",
}


class _Model:
    """Scores from a queue; every other call returns a plausible string.

    Question generation and the closing summary go through the same `chat`
    entry point, so the double has to answer all three - and recording what it
    was asked is how the transcript assertion below works.
    """

    def __init__(self, scores: list[dict]) -> None:
        self._scores = list(scores)
        self.questions_asked = 0
        self.summary_prompt = ""

    def score(self, messages, **_):
        payload = self._scores.pop(0) if self._scores else _STRONG
        return make_chat_result(json.dumps(payload))

    def question(self, messages, **_):
        self.questions_asked += 1
        return make_chat_result(f"Question number {self.questions_asked}?")

    def summarise(self, messages):
        self.summary_prompt = messages[-1]["content"]
        return make_chat_result("You buried the result every time.")


@pytest.fixture()
def model(monkeypatch, isolated_settings):
    init_db()

    def _make(scores: list[dict]) -> _Model:
        double = _Model(scores)
        monkeypatch.setattr(rubric_module, "chat", double.score)
        monkeypatch.setattr(questions_module, "chat", double.question)
        monkeypatch.setattr(
            questions_module, "_kb_grounding", lambda p, topic="", s=None: ("", "general")
        )

        def _summary(transcript, averages, *, plan, session_id=None):
            double.summary_prompt = transcript
            return "You buried the result every time."

        monkeypatch.setattr(session_module, "write_summary", _summary)
        return double

    return _make


def _plan(**overrides) -> Plan:
    kwargs = {
        "profile": Profile.DEVOPS,
        "persona": get_persona("tech_lead"),
        "difficulty": Difficulty.STANDARD,
        "questions": 2,
    }
    kwargs.update(overrides)
    return Plan(**kwargs)


def test_a_weak_answer_is_followed_up_and_the_probe_is_stored_as_one(model):
    double = model([_WEAK])
    plan = _plan()
    session_id = session_module.start_session(plan)

    result = session_module.submit_answer(
        session_id,
        plan=plan,
        question="Tell me about a rollback.",
        answer="It went fine.",
    )

    assert result.move is Move.PROBE
    assert result.probe is not None
    assert result.probe.text == "Which cluster, and how many nodes?"
    assert result.probe.grounding == "your previous answer"
    assert repo.answer_count(session_id, probes=True) == 0  # the probe is not answered yet

    # The follow-up came back with the score. Asking it costs no second call.
    assert double.questions_asked == 0


def test_a_probe_does_not_consume_a_question_slot(model):
    """The whole point of the is_probe flag: two answers, one question used."""
    model([_WEAK, _WEAK])
    plan = _plan()
    session_id = session_module.start_session(plan)

    first = session_module.submit_answer(
        session_id,
        plan=plan,
        question="Tell me about a rollback.",
        answer="It went fine.",
    )
    session_module.submit_answer(
        session_id,
        plan=plan,
        question=first.probe.text,
        answer="Still vague.",
        is_probe=True,
    )

    assert repo.questions_asked(session_id) == ["Tell me about a rollback."]
    assert repo.answer_count(session_id) == 2
    assert repo.answer_count(session_id, probes=True) == 1


def test_a_strong_answer_moves_straight_on(model):
    double = model([_STRONG])
    plan = _plan()
    session_id = session_module.start_session(plan)

    result = session_module.submit_answer(
        session_id, plan=plan, question="Tell me about a rollback.", answer="Detailed."
    )
    assert result.move is Move.NEXT
    # Deliberately not generated here: the page paints the score first, then
    # calls `following_question`. Doing both inside submit was the five seconds.
    assert result.probe is None
    assert double.questions_asked == 0

    question = session_module.following_question(session_id, plan=plan)
    assert question.text == "Question number 1?"


def test_a_session_ends_itself_and_writes_a_debrief(model):
    double = model([_STRONG, _STRONG])
    plan = _plan(questions=2)
    session_id = session_module.start_session(plan)

    session_module.submit_answer(session_id, plan=plan, question="Q1", answer="Answer one.")
    final = session_module.submit_answer(session_id, plan=plan, question="Q2", answer="Answer two.")

    assert final.move is Move.WRAP_UP
    assert final.probe is None
    assert final.summary

    stored = repo.get_session(session_id)
    assert stored.ended_at is not None
    assert stored.summary == final.summary
    # The debrief saw the real transcript, not a summary of a summary.
    assert "Answer one." in double.summary_prompt
    assert "Answer two." in double.summary_prompt


def test_the_stored_scores_are_what_the_progress_page_will_average(model):
    model([_WEAK, _STRONG])
    plan = _plan(questions=2)
    session_id = session_module.start_session(plan)

    session_module.submit_answer(
        session_id, plan=plan, question="Q1", answer="Vague.", is_probe=True
    )
    session_module.submit_answer(session_id, plan=plan, question="Q2", answer="Detailed.")

    averages = repo.dimension_averages(session_id=session_id)
    assert averages["impact"] == 3.0  # (1 + 5) / 2
    assert repo.weakest_dimensions(profile=Profile.DEVOPS, limit=1)[0][1] == 3.0


def test_voice_and_typed_answers_are_distinguishable(model):
    """A spoken answer and a written one are not the same performance."""
    model([_STRONG])
    plan = _plan()
    session_id = session_module.start_session(plan)

    session_module.submit_answer(
        session_id,
        plan=plan,
        question="Q1",
        answer="Spoken answer.",
        captured_as="voice",
        duration_seconds=42.5,
    )

    answer = repo.get_session(session_id).answers[0]
    assert answer.captured_as == "voice"
    assert answer.duration_seconds == 42.5


def test_an_interrupted_session_keeps_the_answers_it_got(model):
    """Nothing marks it finished, but the data is there - which is the point of
    creating the session row up front."""
    model([_STRONG])
    plan = _plan(questions=5)
    session_id = session_module.start_session(plan)
    session_module.submit_answer(session_id, plan=plan, question="Q1", answer="Answer one.")

    stored = repo.get_session(session_id)
    assert stored.ended_at is None
    assert len(stored.answers) == 1
    assert repo.dimension_averages(session_id=session_id)["impact"] == 5.0


def test_a_refreshed_page_can_pick_the_interview_back_up(model):
    """The complaint this exists for: four answers given, F5, everything gone.

    The rows were always in the database - what was missing was any way back to
    them. `latest_unfinished` plus `restore` is that way back.
    """
    model([_STRONG, _STRONG])
    plan = _plan(questions=5, persona=get_persona("principal"), difficulty=Difficulty.HARD)
    session_id = session_module.start_session(plan)
    session_module.submit_answer(session_id, plan=plan, question="Q1", answer="Answer one.")
    session_module.submit_answer(session_id, plan=plan, question="Q2", answer="Answer two.")

    # The browser is refreshed: nothing survives except the database.
    found = repo.latest_unfinished()
    assert found is not None
    assert found.id == session_id

    restored = session_module.restore(found.id)
    assert restored is not None
    assert [turn.answer for turn in restored.turns] == ["Answer one.", "Answer two."]
    assert restored.turns[0].score.impact == 5.0
    assert restored.turns[0].question == "Q1"


def test_a_resumed_session_keeps_the_interviewer_it_started_with(model):
    """Not whatever the sidebar happens to be set to now - the scores already
    recorded were earned against a specific interviewer at a specific length."""
    model([_STRONG])
    plan = _plan(questions=7, persona=get_persona("principal"), difficulty=Difficulty.HARD)
    session_id = session_module.start_session(plan)
    session_module.submit_answer(session_id, plan=plan, question="Q1", answer="Answer one.")

    restored = session_module.restore(session_id)
    assert restored.plan.persona.key == "principal"
    assert restored.plan.difficulty is Difficulty.HARD
    assert restored.plan.questions == 7
    assert restored.plan.threshold == plan.threshold


def test_a_resumed_session_does_not_repeat_its_questions(model):
    model([_STRONG])
    plan = _plan(questions=5)
    session_id = session_module.start_session(plan)
    session_module.submit_answer(
        session_id,
        plan=plan,
        question="Tell me about a rollback.",
        answer="Answer one.",
    )

    seen: dict[str, str] = {}

    def _capture(messages, **_):
        seen["user"] = messages[-1]["content"]
        return make_chat_result("A brand new question?")

    questions_module.chat = _capture
    question = session_module.following_question(session_id, plan=plan)

    assert question.text == "A brand new question?"
    assert "Tell me about a rollback." in seen["user"]


def test_a_finished_session_is_not_offered_for_resuming(model):
    model([_STRONG])
    plan = _plan(questions=1)
    session_id = session_module.start_session(plan)
    session_module.submit_answer(session_id, plan=plan, question="Q1", answer="Answer one.")

    assert repo.get_session(session_id).ended_at is not None
    assert repo.latest_unfinished() is None


def test_an_empty_session_is_not_offered_for_resuming(model):
    """Clicking Start and closing the tab is not an interview to come back to."""
    model([])
    session_module.start_session(_plan())
    assert repo.latest_unfinished() is None
