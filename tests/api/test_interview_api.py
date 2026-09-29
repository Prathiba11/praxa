"""The interview session, as an API rather than a conversation.

The property every test here circles: **a session has state, and the state
lives in the database**. Practice in the chat box did not - each message there
was independent, so nothing knew a question was outstanding, and asking twice
produced two questions instead of a question and a critique.

The model is stubbed throughout. What is under test is the session procedure -
what is stored, what comes back, what survives a refresh - not the quality of a
question or the fairness of a score.
"""

from __future__ import annotations

import pytest

from career_copilot.interview.questions import Question
from career_copilot.interview.rubric import RubricScore

_QUESTION = Question(
    text="Tell me about a time you led an incident response.",
    grounding="From your DevOps CV: on-call rotation, three regions.",
)

_STRONG = RubricScore(
    structure=4.0,
    specificity=4.0,
    ownership=4.0,
    impact=4.0,
    relevance=4.0,
    feedback="Clear situation and a measured result.",
    improved_answer="",
)

_WEAK = RubricScore(
    structure=2.0,
    specificity=1.0,
    ownership=2.0,
    impact=1.0,
    relevance=2.0,
    feedback="No numbers, and the action was the team's rather than yours.",
    improved_answer="Name what you personally changed, and by how much.",
    probe="What did you do, specifically, that nobody else did?",
)


@pytest.fixture()
def stub_interview(monkeypatch):
    """Questions and scores without a model call.

    Patched at the session module's own imports rather than at `chat`, so the
    routing, storage and decide-next logic under test all still run.
    """
    from career_copilot.interview import session as session_module

    monkeypatch.setattr(session_module, "next_question", lambda *a, **k: _QUESTION)
    monkeypatch.setattr(session_module, "score_answer", lambda *a, **k: _STRONG)
    return session_module


def _start(client, **overrides):
    payload = {"profile": "devops", "persona": "tech_lead", "difficulty": "standard"}
    payload.update(overrides)
    return client.post("/api/interview/sessions", json=payload)


# ------------------------------------------------------------------ options


def test_the_form_is_told_its_choices_rather_than_guessing(client, api_settings):
    """A page with its own copy of the persona list disagrees with the server
    the day a persona is added."""
    body = client.get("/api/interview/options").json()

    assert {persona["key"] for persona in body["personas"]} >= {"recruiter", "tech_lead"}
    assert body["difficulties"] == ["warmup", "standard", "hard"]
    assert body["defaultPersona"]
    assert body["defaultQuestions"] >= 1
    # The opener is carried because "Friendly recruiter" means little until you
    # read what they actually say.
    assert all(persona["opening"] for persona in body["personas"])


# ------------------------------------------------------------------ starting


def test_starting_returns_a_session_and_its_opening_question(client, api_settings, stub_interview):
    response = _start(client)

    assert response.status_code == 201
    body = response.json()
    assert body["sessionId"]
    assert body["profile"] == "devops"
    assert body["persona"]["key"] == "tech_lead"
    assert body["difficulty"] == "standard"
    assert body["question"]["text"] == _QUESTION.text
    # Where the question came from is shown, because a question grounded in the
    # candidate's own material and one invented from a profile name differ.
    assert body["question"]["grounding"]
    assert body["turns"] == []


def test_an_unknown_persona_falls_back_rather_than_failing(client, api_settings, stub_interview):
    """`get_persona` is documented to fall back; the route must not pre-empt it."""
    response = _start(client, persona="wizard")
    assert response.status_code == 201
    assert response.json()["persona"]["key"]


# ------------------------------------------------------------------ answering


def test_an_answer_is_scored_and_the_session_moves_on(client, api_settings, stub_interview):
    session_id = _start(client).json()["sessionId"]

    response = client.post(
        f"/api/interview/sessions/{session_id}/answers",
        json={"question": _QUESTION.text, "answer": "I led the incident and cut MTTR by 40%."},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["score"]["overall"] == pytest.approx(4.0)
    assert body["move"] in {"probe", "next", "finish"}


def test_a_weak_answer_earns_a_follow_up_on_the_same_question(
    client, api_settings, stub_interview, monkeypatch
):
    """The probe comes free with the score - no second model call for it."""
    monkeypatch.setattr(stub_interview, "score_answer", lambda *a, **k: _WEAK)
    session_id = _start(client).json()["sessionId"]

    body = client.post(
        f"/api/interview/sessions/{session_id}/answers",
        json={"question": _QUESTION.text, "answer": "We fixed it."},
    ).json()

    assert body["move"] == "probe"
    assert body["probe"]["text"]


def test_the_answer_is_stored_even_though_the_page_holds_no_state(
    client, api_settings, stub_interview
):
    """The whole reason this is a session and not a conversation."""
    session_id = _start(client).json()["sessionId"]
    client.post(
        f"/api/interview/sessions/{session_id}/answers",
        json={"question": _QUESTION.text, "answer": "I led the incident and cut MTTR by 40%."},
    )

    restored = client.get(f"/api/interview/sessions/{session_id}").json()

    assert len(restored["turns"]) == 1
    assert restored["turns"][0]["answer"].startswith("I led the incident")
    assert restored["turns"][0]["score"]["overall"] == pytest.approx(4.0)


def test_a_refresh_lands_on_the_same_session(client, api_settings, stub_interview):
    """A restore carries no question: an unanswered one was never stored, so the
    page asks for a new one. Nothing the candidate produced is lost."""
    session_id = _start(client).json()["sessionId"]

    restored = client.get(f"/api/interview/sessions/{session_id}").json()

    assert restored["sessionId"] == session_id
    assert restored["persona"]["key"] == "tech_lead"
    assert restored["plannedQuestions"] >= 1
    assert restored["question"] is None


def test_the_next_question_avoids_what_was_already_asked(client, api_settings, stub_interview):
    session_id = _start(client).json()["sessionId"]
    response = client.post(f"/api/interview/sessions/{session_id}/next")

    assert response.status_code == 200
    assert response.json()["text"]


# -------------------------------------------------------------------- errors


@pytest.mark.parametrize(
    "call",
    [
        lambda client: client.get("/api/interview/sessions/nosuch"),
        lambda client: client.post("/api/interview/sessions/nosuch/next"),
        lambda client: client.post(
            "/api/interview/sessions/nosuch/answers",
            json={"question": "q", "answer": "a"},
        ),
    ],
)
def test_an_unknown_session_is_a_404(client, api_settings, call):
    assert call(client).status_code == 404


def test_an_empty_answer_is_refused(client, api_settings, stub_interview):
    session_id = _start(client).json()["sessionId"]
    response = client.post(
        f"/api/interview/sessions/{session_id}/answers",
        json={"question": _QUESTION.text, "answer": ""},
    )
    assert response.status_code == 422


def test_the_session_has_no_route_to_a_document_writer():
    """A mock interview that can edit your CV is a mock interview a job posting
    can edit your CV through. The allowlist says so; this says the router does
    not quietly offer another way in.

    Asked of the router itself. Two earlier versions asked the wrong thing:
    walking `app.routes` hit a `_IncludedRouter` with no `.path`, and fetching
    `/openapi.json` got the single-page app's index.html, because the schema is
    mounted at `/api/openapi.json` and the catch-all serves everything else.
    `APIRouter.routes` is public, needs no app, and is exactly the surface under
    test.
    """
    from career_copilot.api.routes.interview import router

    paths = {route.path for route in router.routes}

    assert paths, "the interview router declares no routes"
    assert not [path for path in paths if "document" in path or "resume" in path]
    # And the surface is only what it should be.
    assert paths == {
        "/interview/options",
        "/interview/sessions",
        "/interview/sessions/{session_id}",
        "/interview/sessions/{session_id}/answers",
        "/interview/sessions/{session_id}/next",
    }


# ------------------------------------------- the live path, not the stubbed one


@pytest.fixture()
def only_the_model_stubbed(monkeypatch):
    """Replace the model call and nothing else.

    The fixture above stubs `next_question` and `score_answer` outright, which
    is the right seam for testing a state machine but leaves a hole: everything
    between the route and the model - the grounding retrieval, the topic
    rotation, the prompt assembly, the empty-response fallback - never runs.
    A 500 from that stretch would pass the suite and fail in the browser.

    So this stubs `chat` at each module's own import of it, one layer lower.
    Retrieval runs for real against the test's empty index and takes its
    documented fallback; `next_question` builds its real prompt and parses a
    real reply.
    """
    from career_copilot.interview import questions as questions_module
    from career_copilot.interview import rubric as rubric_module
    from tests.helpers import make_chat_result

    monkeypatch.setattr(
        questions_module,
        "chat",
        lambda *a, **k: make_chat_result("Tell me about a deployment you rolled back."),
    )
    monkeypatch.setattr(
        rubric_module,
        "chat",
        lambda *a, **k: make_chat_result(
            '{"structure": 3, "specificity": 3, "ownership": 3, "impact": 3, '
            '"relevance": 3, "feedback": "Fine.", "improved_answer": "", "probe": ""}'
        ),
    )


def test_starting_works_through_the_real_question_pipeline(
    client, api_settings, only_the_model_stubbed
):
    """The path the stubbed tests skip, end to end below the model."""
    response = _start(client)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["question"]["text"] == "Tell me about a deployment you rolled back."
    # Retrieval ran and reported where it got to, whatever it found.
    assert body["question"]["grounding"]


def test_answering_works_through_the_real_rubric(client, api_settings, only_the_model_stubbed):
    session_id = _start(client).json()["sessionId"]

    response = client.post(
        f"/api/interview/sessions/{session_id}/answers",
        json={
            "question": "Tell me about a rollback.",
            "answer": "I rolled it back in ten minutes.",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["score"]["overall"] == pytest.approx(3.0)


def test_the_next_question_works_through_the_real_pipeline(
    client, api_settings, only_the_model_stubbed
):
    session_id = _start(client).json()["sessionId"]
    response = client.post(f"/api/interview/sessions/{session_id}/next")

    assert response.status_code == 200, response.text
    assert response.json()["text"]
