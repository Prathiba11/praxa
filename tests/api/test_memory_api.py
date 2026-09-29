"""The memory endpoints, against a real SQLite database.

Nothing is stubbed except the extractor, because there is nothing expensive
here to stub: this router is SQL and serialisation. No endpoint in it calls a
model, and the test at the bottom of this file says so in a way that fails if
that ever stops being true.

The endpoints that matter most are the ones that take things away. A memory
feature the user cannot inspect is a system forming opinions about them in
private; one they cannot correct is worse. So: every row is listed, every row
says where it came from, and every row can be deleted.
"""

from __future__ import annotations

from career_copilot.api.routes import chat as chat_route
from career_copilot.memory.recall import MAX_PROMPT_FACTS, recall_block
from career_copilot.storage import memory as store
from career_copilot.storage.db import init_db


def _seed(api_settings):
    init_db()
    store.remember("only wants remote or Stuttgart roles", category="location")
    store.remember("will not take on-call roles", category="deal_breaker", origin="stated")


# ------------------------------------------------------------------- listing


def test_listing_is_empty_before_anything_is_remembered(client, api_settings):
    response = client.get("/api/memory")

    assert response.status_code == 200
    assert response.json() == []


def test_every_fact_says_what_it_is_and_where_it_came_from(client, api_settings):
    _seed(api_settings)

    body = client.get("/api/memory").json()

    assert len(body) == 2
    fact = body[0]
    assert set(fact) == {"id", "category", "text", "origin", "createdAt", "lastSeenAt"}
    origins = {item["text"]: item["origin"] for item in body}
    # The distinction is the point: a user reviewing this needs to know which
    # of these they said outright and which was inferred from a turn.
    assert origins["will not take on-call roles"] == "stated"
    assert origins["only wants remote or Stuttgart roles"] == "extracted"


def test_a_category_written_by_an_older_version_still_lists(client, api_settings):
    """The database stores a string; the API promises a closed set.

    A row from an older version, or one edited by hand, falls back to the
    catch-all rather than breaking the page - a fact the user can see and
    delete is worth more than a listing that refuses to load.
    """
    init_db()
    store.remember("something from a previous schema", category="salary_expectation")

    body = client.get("/api/memory").json()

    assert body[0]["category"] == "other"
    assert body[0]["text"] == "something from a previous schema"


# ------------------------------------------------------------------- writing


def test_a_stated_fact_can_be_added_outright(client, api_settings):
    response = client.post(
        "/api/memory",
        json={"text": "wants to interview in German", "category": "language"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["origin"] == "stated"
    assert body["category"] == "language"
    assert client.get("/api/memory").json()[0]["text"] == "wants to interview in German"


def test_identifying_details_are_masked_on_the_way_in(client, api_settings):
    """The same rule the extractor follows, enforced on the other door too.

    This endpoint is the one place a user can put text straight into the
    store, so it is the one place where "the prompt says not to" is no
    protection at all.
    """
    response = client.post(
        "/api/memory",
        json={"text": "reach me at prathiba@example.com", "category": "other"},
    )

    assert response.status_code == 201
    assert "prathiba@example.com" not in response.json()["text"]
    assert "[EMAIL]" in response.json()["text"]


def test_an_unknown_category_is_refused_rather_than_stored(client, api_settings):
    response = client.post("/api/memory", json={"text": "wants a four day week", "category": "pay"})

    assert response.status_code == 422
    assert client.get("/api/memory").json() == []


def test_stating_a_fact_already_inferred_promotes_it(client, api_settings):
    init_db()
    store.remember("only wants remote roles", category="location")

    response = client.post(
        "/api/memory",
        json={"text": "Only wants remote roles.", "category": "location"},
    )

    assert response.status_code == 201
    assert response.json()["origin"] == "stated"
    # One fact, not two: case and punctuation do not make a new preference.
    assert len(client.get("/api/memory").json()) == 1


# ------------------------------------------------------------------ deleting


def test_a_fact_can_be_forgotten(client, api_settings):
    _seed(api_settings)
    facts = client.get("/api/memory").json()
    target = facts[0]

    assert client.delete(f"/api/memory/{target['id']}").status_code == 204

    remaining = client.get("/api/memory").json()
    assert target["id"] not in [fact["id"] for fact in remaining]
    assert len(remaining) == 1


def test_forgetting_something_that_is_not_there_is_a_404(client, api_settings):
    response = client.delete("/api/memory/9999")

    assert response.status_code == 404
    # The same envelope every other failure arrives in.
    assert response.json()["code"] == "not_found"


def test_everything_can_be_forgotten_at_once(client, api_settings):
    _seed(api_settings)

    response = client.delete("/api/memory")

    assert response.status_code == 200
    assert response.json() == {"removed": 2}
    assert client.get("/api/memory").json() == []


# ------------------------------------------------- what the turn writes here


def test_a_finished_turn_is_what_fills_the_store(client, api_settings, monkeypatch):
    """Extraction is the only thing that reads a conversation.

    It is called after the answer has gone out, so what this checks is that
    the route hands it the turn it just finished - both sides of it, billed
    to the same thread.
    """
    seen: dict[str, object] = {}

    def fake_remember_turn(question, answer, *, session_id=None):
        seen.update(question=question, answer=answer, session_id=session_id)
        return 1

    monkeypatch.setattr(chat_route, "remember_turn", fake_remember_turn)
    chat_route._remember("thread-9", "I only want remote roles", "Noted. [1]")

    assert seen == {
        "question": "I only want remote roles",
        "answer": "Noted. [1]",
        "session_id": "thread-9",
    }


def test_an_extractor_that_fails_never_reaches_the_user(client, api_settings, monkeypatch):
    """The turn already succeeded and the stream has closed.

    Nothing that happens after the `done` frame is allowed to surface, so the
    only correct behaviour for a failure here is a log line and silence.
    """

    def _explode(*_args, **_kwargs):
        raise RuntimeError("extractor exploded")

    monkeypatch.setattr(chat_route, "remember_turn", _explode)

    chat_route._remember("thread-9", "a question", "an answer")


# ------------------------------------------------------------------- preview
#
# The preview endpoint exists so the interface can show the prompt text instead
# of describing it. Its whole value is that it is the same string the agent
# gets, so the tests here are about identity with `recall_block`, not about
# formatting.


def test_preview_is_the_string_recall_block_returns(client, api_settings):
    """Not a reconstruction of it. A preview assembled separately would drift.

    If this is ever satisfied by a hand-built string that merely looks similar,
    the page stops being evidence of anything - it would prove the preview
    builder works, which is not the claim being made.
    """
    _seed(api_settings)

    body = client.get("/api/memory/preview").json()

    assert body["block"] == recall_block()
    assert "only wants remote or Stuttgart roles" in body["block"]


def test_preview_reports_the_caps_and_what_is_stored(client, api_settings):
    _seed(api_settings)

    body = client.get("/api/memory/preview").json()

    assert set(body) == {
        "block",
        "enabled",
        "stored",
        "maxStored",
        "maxPerCategory",
        "maxPerAnswer",
        "perCategory",
        "leastRecentlyMentioned",
    }
    assert body["stored"] == 2
    assert body["maxStored"] == store.MAX_TOTAL
    assert body["maxPerCategory"] == store.MAX_PER_CATEGORY
    # Read from the module rather than hard-coded, like the other two: the
    # claim under test is that the endpoint reports the real caps, not that the
    # caps happen to have particular values today.
    assert body["maxPerAnswer"] == MAX_PROMPT_FACTS
    assert {row["category"] for row in body["perCategory"]} == {"location", "deal_breaker"}


def test_preview_of_an_empty_store_is_an_empty_block_not_an_error(client, api_settings):
    """Nothing remembered is a state, not a failure.

    An empty block is the honest answer - it is exactly what the prompt looked
    like before this feature existed - so the endpoint returns one rather than
    404ing and leaving the page to guess.
    """
    init_db()

    body = client.get("/api/memory/preview").json()

    assert body["block"] == ""
    assert body["stored"] == 0
    assert body["perCategory"] == []
    assert body["leastRecentlyMentioned"] is None


def test_preview_names_the_fact_that_would_go_first(client, api_settings):
    """The least recently mentioned one, which is the tail of the listing."""
    _seed(api_settings)

    body = client.get("/api/memory/preview").json()
    listed = client.get("/api/memory").json()

    assert body["leastRecentlyMentioned"] == listed[-1]["text"]


def test_preview_changes_no_state(client, api_settings):
    """It is a window, not an action. Reading it must not touch a row."""
    _seed(api_settings)
    before = client.get("/api/memory").json()

    client.get("/api/memory/preview")

    assert client.get("/api/memory").json() == before


def test_no_memory_endpoint_calls_a_model(client, api_settings):
    """A guard, not a behaviour.

    The whole suite refuses at the model client, so a route that acquired an
    LLM call would raise here rather than quietly buy an answer. Listing,
    stating and forgetting are storage operations and must stay that way.
    """
    assert client.post("/api/memory", json={"text": "wants DevOps roles"}).status_code == 201
    assert client.get("/api/memory").status_code == 200
    assert client.get("/api/memory/preview").status_code == 200
    assert client.delete("/api/memory").status_code == 200
