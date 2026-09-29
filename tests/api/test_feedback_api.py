"""Rating an answer, and reading the ratings back.

Like the memory router, this one is SQL and serialisation - no endpoint here
calls a model, and the last test in this file fails if that ever changes.

Two properties carry the feature. A rating is an opinion rather than a log, so
rating the same answer twice must leave one row; and the stored text is masked,
because this is a store and what reaches a store is masked. The rest is the
tally being arithmetic rather than a guess.
"""

from __future__ import annotations

from career_copilot.storage import feedback as store
from career_copilot.storage.db import init_db


def _rate(
    client,
    *,
    message_id="a1",
    rating="up",
    mode="chat",
    question="how do I start?",
    answer="Start with the summary.",
):
    return client.post(
        "/api/feedback",
        json={
            "messageId": message_id,
            "threadId": "thread-1",
            "rating": rating,
            "mode": mode,
            "model": "openai/gpt-4o-mini",
            "question": question,
            "answer": answer,
        },
    )


# -------------------------------------------------------------------- rating


def test_nothing_is_rated_to_begin_with(client, api_settings):
    body = client.get("/api/feedback").json()

    assert body["total"] == 0
    assert body["recent"] == []
    # Not 0.0. "No ratings yet" and "every rating was negative" are opposite
    # readings, and a zero here would report the second when the first is true.
    assert body["approval"] is None


def test_a_rating_comes_back_with_the_turn_it_judged(client, api_settings):
    response = _rate(client, rating="down", question="why so slow?", answer="Because of IPv6.")

    assert response.status_code == 201
    body = response.json()
    assert body["rating"] == "down"
    assert body["question"] == "why so slow?"
    assert body["answer"] == "Because of IPv6."


def test_changing_your_mind_replaces_the_rating_rather_than_adding_one(client, api_settings):
    _rate(client, message_id="b2", rating="down")
    _rate(client, message_id="b2", rating="up")

    body = client.get("/api/feedback").json()

    assert body["total"] == 1, "a tally of clicks rather than of answers"
    assert body["up"] == 1
    assert body["down"] == 0


def test_a_rating_can_be_withdrawn(client, api_settings):
    _rate(client, message_id="c3")

    assert client.delete("/api/feedback/c3").status_code == 204
    assert client.get("/api/feedback").json()["total"] == 0


def test_withdrawing_a_rating_that_was_never_given_is_a_404(client, api_settings):
    assert client.delete("/api/feedback/never-rated").status_code == 404


# --------------------------------------------------------------------- store


def test_the_stored_text_is_masked(client, api_settings):
    _rate(
        client,
        message_id="d4",
        question="mail it to prathiba@example.com",
        answer="Sent to prathiba@example.com.",
    )

    init_db()
    row = store.list_feedback()[0]

    assert "example.com" not in row.question
    assert "example.com" not in row.answer
    assert "[EMAIL]" in row.question


def test_the_tally_splits_by_mode(client, api_settings):
    _rate(client, message_id="e5", rating="up", mode="chat")
    _rate(client, message_id="e6", rating="down", mode="jobs")
    _rate(client, message_id="e7", rating="up", mode="jobs")

    body = client.get("/api/feedback").json()

    assert body["up"] == 2
    assert body["down"] == 1
    assert body["approval"] == 2 / 3
    assert {entry["mode"]: (entry["up"], entry["down"]) for entry in body["byMode"]} == {
        "chat": (1, 0),
        "jobs": (1, 1),
    }


def test_the_listing_can_be_filtered_to_the_answers_that_went_wrong(client, api_settings):
    _rate(client, message_id="f8", rating="up")
    _rate(client, message_id="f9", rating="down")

    body = client.get("/api/feedback", params={"rating": "down"}).json()

    assert [row["messageId"] for row in body["recent"]] == ["f9"]
    # The filter narrows the listing, not the arithmetic - a tally that moved
    # when you clicked a filter would be reporting the filter, not the ratings.
    assert body["total"] == 2


def test_the_store_is_bounded(client, api_settings, monkeypatch):
    monkeypatch.setattr(store, "MAX_STORED", 3)
    for number in range(5):
        _rate(client, message_id=f"g{number}")

    assert store.count() == 3


def test_clearing_removes_every_rating(client, api_settings):
    _rate(client, message_id="h1")
    _rate(client, message_id="h2")

    assert client.delete("/api/feedback").json() == {"removed": 2}
    assert client.get("/api/feedback").json()["total"] == 0


# ------------------------------------------------------------- no model here


def test_nothing_in_this_router_calls_a_model(client, api_settings):
    """The autouse fixture in tests/conftest.py fails any real provider call.

    This test exists so that a future version which quietly asks a model to
    summarise the feedback cannot slip in unnoticed.
    """
    _rate(client, message_id="i1", rating="down")

    assert client.get("/api/feedback").status_code == 200
