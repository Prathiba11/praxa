"""Long-term memory: the store, the extractor, and the recall block.

Three separate obligations are being held here, and they fail in different
directions.

**The store must stay small and stay correct.** A fact restated on five turns
is one row, not five; a fact the user stated outright is never quietly
downgraded to an inference; and neither cap may be exceeded, because an
unbounded store is how a prompt grows until something breaks.

**The extractor must never cost a turn.** It runs after the answer has been
delivered. Every failure path it has - memory switched off, the model
unreachable, prose where JSON was asked for - has to end in "no facts" rather
than in an exception that reaches a user who already has their answer.

**Recall must never be load-bearing.** An empty store, a disabled feature or an
unreadable database all have to produce the prompt the application had before
this feature existed, which is the one with no memory section at all.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from career_copilot.core.config import get_settings
from career_copilot.core.errors import LLMError
from career_copilot.memory import extract as extract_module
from career_copilot.memory import recall as recall_module
from career_copilot.memory.extract import extract_facts, remember_turn
from career_copilot.memory.recall import MAX_PROMPT_FACTS, recall_block, recall_message
from career_copilot.storage import db as db_module
from career_copilot.storage import memory as store
from career_copilot.storage.db import StorageError
from career_copilot.storage.memory import MAX_PER_CATEGORY, MAX_TOTAL
from career_copilot.storage.models import MemoryFact, fact_fingerprint


@pytest.fixture(autouse=True)
def _settings(tmp_path, monkeypatch):
    """A throwaway database and a memory feature that is switched on.

    Every one of these is *set*, never deleted. Removing an environment
    variable does not unset a pydantic setting - it falls through to `.env`,
    so a developer whose own `.env` switches memory off would otherwise see
    half this file fail for a reason that has nothing to do with the code.
    """
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-test-not-a-real-key")
    monkeypatch.setenv("CC_MODEL", "openai/gpt-4o-mini")
    monkeypatch.setenv("CC_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CC_DB_PATH", str(tmp_path / "copilot.db"))
    monkeypatch.setenv("CC_MEMORY_ENABLED", "true")
    monkeypatch.setenv("CC_GRADER_MODEL", "openai/gpt-4o-mini")

    get_settings.cache_clear()
    db_module.reset_engine()
    db_module.init_db()
    yield
    get_settings.cache_clear()
    db_module.reset_engine()


def _touch(text: str, *, when: datetime) -> None:
    """Set a fact's `last_seen_at` outright.

    Eviction is decided by recency, and rows written in a loop are written
    microseconds apart. Rather than sleep - or trust a clock's resolution to
    order them - the tests that care about the order state it.
    """
    with db_module.session_scope() as session:
        fact = session.scalar(
            select(MemoryFact).where(MemoryFact.fingerprint == fact_fingerprint(text))
        )
        assert fact is not None
        fact.last_seen_at = when


def _texts() -> list[str]:
    return [fact.text for fact in store.list_facts()]


# -------------------------------------------------------------------- storing


def test_a_fact_is_stored_and_comes_back():
    fact = store.remember("wants remote or Stuttgart roles", category="location")

    assert fact is not None
    assert fact.category == "location"
    assert fact.origin == "extracted"
    assert _texts() == ["wants remote or Stuttgart roles"]


def test_empty_text_is_not_a_fact():
    assert store.remember("   ", category="other") is None
    assert store.count() == 0


def test_restating_a_fact_stores_it_once_and_marks_it_recent():
    first = store.remember("will not take on-call roles", category="deal_breaker")
    assert first is not None
    _touch("will not take on-call roles", when=datetime(2026, 1, 1, tzinfo=UTC))

    again = store.remember("Will not take on-call roles.", category="deal_breaker")

    # Case and punctuation carry no meaning: a model asked the same question on
    # two days will phrase it both ways, and both are the same preference.
    assert again is not None
    assert again.id == first.id
    assert store.count() == 1
    assert again.last_seen_at > datetime(2026, 1, 1, tzinfo=UTC)


def test_stating_a_fact_promotes_one_that_was_merely_inferred():
    store.remember("wants to work in German", category="language")

    promoted = store.remember("wants to work in German", category="language", origin="stated")

    assert promoted is not None
    assert promoted.origin == "stated"
    assert store.list_facts()[0].origin == "stated"


def test_inferring_a_stated_fact_again_never_downgrades_it():
    """The promotion is one-way, and that is the point of the field.

    The page tells the user which facts they said outright. If a later turn
    could quietly relabel one as an inference, that column would be telling
    them something untrue about their own data.
    """
    store.remember("will not relocate", category="deal_breaker", origin="stated")

    store.remember("will not relocate", category="deal_breaker", origin="extracted")

    assert store.list_facts()[0].origin == "stated"


# ------------------------------------------------------------------- the caps


def test_a_category_keeps_only_its_most_recent_facts():
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for index in range(MAX_PER_CATEGORY + 2):
        store.remember(f"must have benefit number {index}", category="must_have")
        _touch(f"must have benefit number {index}", when=base + timedelta(days=index))

    store.remember("must have a final thing", category="must_have")

    kept = _texts()
    assert len(kept) == MAX_PER_CATEGORY
    # Nine facts were written into a category that holds six, so the three
    # least recently mentioned went - in the order they stopped being recent.
    assert "must have benefit number 0" not in kept
    assert "must have benefit number 1" not in kept
    assert "must have benefit number 2" not in kept
    assert "must have benefit number 3" in kept
    assert "must have a final thing" in kept


def test_one_category_filling_up_does_not_evict_another():
    store.remember("looking for DevOps roles", category="role")
    base = datetime(2026, 1, 1, tzinfo=UTC)
    _touch("looking for DevOps roles", when=base)

    for index in range(MAX_PER_CATEGORY + 3):
        store.remember(f"must have benefit number {index}", category="must_have")
        _touch(f"must have benefit number {index}", when=base + timedelta(days=index + 1))

    assert "looking for DevOps roles" in _texts()


def test_the_store_has_a_ceiling_across_every_category():
    """Per-category caps alone do not bound the store - a new category would.

    Seven categories at six facts each is forty-two, and the prompt would grow
    with every category anyone added later. The overall cap is what makes the
    size of this feature a decision rather than an accident.
    """
    categories = ("role", "location", "language", "must_have", "deal_breaker", "application")
    base = datetime(2026, 1, 1, tzinfo=UTC)
    written = 0
    for category in categories:
        for index in range(MAX_PER_CATEGORY):
            text = f"{category} fact number {index}"
            store.remember(text, category=category)
            _touch(text, when=base + timedelta(minutes=written))
            written += 1

    assert written > MAX_TOTAL
    store.remember("one more, over the ceiling", category="other")

    assert store.count() == MAX_TOTAL
    assert "one more, over the ceiling" in _texts()
    assert "role fact number 0" not in _texts()


# ------------------------------------------------------------------ forgetting


def test_forgetting_removes_the_row_and_says_whether_there_was_one():
    fact = store.remember("applied to the Bosch platform role", category="application")
    assert fact is not None

    assert store.forget(fact.id) is True
    assert store.count() == 0
    # Deleting it twice is not an error the user should ever see, but the
    # caller has to be able to tell a 404 from a 204.
    assert store.forget(fact.id) is False


def test_clearing_reports_how_many_went():
    store.remember("fact one", category="other")
    store.remember("fact two", category="other")

    assert store.clear() == 2
    assert store.count() == 0
    assert store.clear() == 0


def test_facts_come_back_most_recently_mentioned_first():
    base = datetime(2026, 1, 1, tzinfo=UTC)
    store.remember("mentioned in April", category="other")
    _touch("mentioned in April", when=base)
    store.remember("mentioned this morning", category="other")
    _touch("mentioned this morning", when=base + timedelta(days=90))

    assert _texts() == ["mentioned this morning", "mentioned in April"]


# ----------------------------------------------------------------- extracting


def _reply(content: str):
    """A stand-in `chat` returning one fixed body."""

    class _Result:
        def __init__(self) -> None:
            self.content = content

    def fake_chat(*_args, **_kwargs):
        return _Result()

    return fake_chat


def test_a_turn_with_a_durable_fact_yields_it(monkeypatch):
    monkeypatch.setattr(
        extract_module,
        "chat",
        _reply('[{"category": "location", "text": "only wants remote or Stuttgart roles"}]'),
    )

    facts = extract_facts("I only want remote or Stuttgart roles", "Noted.")

    assert len(facts) == 1
    assert facts[0].category == "location"


def test_an_empty_array_is_a_correct_answer(monkeypatch):
    """Most turns contain nothing durable, and that must stay cheap.

    The alternative - a model that feels obliged to return something - is how
    a store fills with restated questions.
    """
    monkeypatch.setattr(extract_module, "chat", _reply("[]"))

    assert extract_facts("what is TARA?", "It is a threat analysis method.") == []


def test_a_reply_wrapped_in_prose_is_still_read(monkeypatch):
    monkeypatch.setattr(
        extract_module,
        "chat",
        _reply(
            'Sure! Here you go:\n```json\n[{"category": "role", "text": "wants DevOps roles"}]\n```'
        ),
    )

    facts = extract_facts("I'm after DevOps roles", "Understood.")

    assert [fact.text for fact in facts] == ["wants DevOps roles"]


def test_an_unknown_category_becomes_other(monkeypatch):
    """The set is closed because the recall block groups by it.

    An open one would let the model invent a heading per turn, and the prompt
    would stop being something anyone could read.
    """
    monkeypatch.setattr(
        extract_module,
        "chat",
        _reply('[{"category": "salary_expectation", "text": "wants a four day week"}]'),
    )

    assert extract_facts("...", "...")[0].category == "other"


def test_a_turn_may_only_contribute_a_few_facts(monkeypatch):
    payload = ", ".join(
        f'{{"category": "other", "text": "fact number {index}"}}' for index in range(9)
    )
    monkeypatch.setattr(extract_module, "chat", _reply(f"[{payload}]"))

    facts = extract_facts("...", "...")

    assert len(facts) == extract_module._MAX_PER_TURN


def test_a_model_failure_remembers_nothing_and_raises_nothing(monkeypatch):
    """The turn already succeeded. Nothing here may change that."""

    def _explode(*_args, **_kwargs):
        raise LLMError("provider unreachable")

    monkeypatch.setattr(extract_module, "chat", _explode)

    assert extract_facts("I only want remote roles", "Noted.") == []


def test_prose_where_json_was_asked_for_remembers_nothing(monkeypatch):
    monkeypatch.setattr(extract_module, "chat", _reply("I'm sorry, I can't help with that."))

    assert extract_facts("...", "...") == []


def test_memory_switched_off_does_not_call_the_model(monkeypatch):
    monkeypatch.setenv("CC_MEMORY_ENABLED", "false")
    get_settings.cache_clear()

    def _never(*_args, **_kwargs):
        raise AssertionError("the model was called with memory disabled")

    monkeypatch.setattr(extract_module, "chat", _never)

    assert extract_facts("I only want remote roles", "Noted.") == []


def test_the_extractor_is_billed_to_the_turn_that_produced_it(monkeypatch):
    seen: dict[str, object] = {}

    def fake_chat(*_args, **kwargs):
        seen.update(kwargs)

        class _Result:
            content = "[]"

        return _Result()

    monkeypatch.setattr(extract_module, "chat", fake_chat)
    extract_facts("...", "...", session_id="thread-7")

    assert seen["session_id"] == "thread-7"
    assert seen["operation"] == "extract_memory"
    # The grader's model, not the chat model. This runs on every turn, and
    # paying writing rates for a classification job would double what the
    # feature costs for no gain in quality.
    assert seen["model"] == get_settings().grader_model


# ------------------------------------------------------- extracting and storing


def test_a_remembered_turn_lands_in_the_store(monkeypatch):
    monkeypatch.setattr(
        extract_module,
        "chat",
        _reply('[{"category": "deal_breaker", "text": "will not take on-call roles"}]'),
    )

    assert remember_turn("I won't do on-call", "Noted.") == 1
    assert _texts() == ["will not take on-call roles"]


def test_identifying_details_are_masked_before_they_are_stored(monkeypatch):
    """The prompt tells the extractor not to keep these. A prompt is a request.

    The store is a file on disk that outlives the conversation, so the rule is
    enforced here as well - with the same masking the logs use.
    """
    monkeypatch.setattr(
        extract_module,
        "chat",
        _reply('[{"category": "other", "text": "reachable at prathiba@example.com"}]'),
    )

    remember_turn("mail me at prathiba@example.com", "Noted.")

    stored = _texts()[0]
    assert "prathiba@example.com" not in stored
    assert "[EMAIL]" in stored


def test_a_turn_with_nothing_durable_writes_nothing(monkeypatch):
    monkeypatch.setattr(extract_module, "chat", _reply("[]"))

    assert remember_turn("what is TARA?", "A threat analysis method.") == 0
    assert store.count() == 0


# -------------------------------------------------------------------- recalling


def test_an_empty_store_adds_nothing_to_the_prompt():
    """The empty string is the prompt this application had before memory.

    Every failure in recall degrades to exactly that, rather than to a broken
    turn or an empty heading the model has to interpret.
    """
    assert recall_block() == ""


def test_remembered_facts_appear_with_their_category():
    store.remember("only wants remote or Stuttgart roles", category="location")

    block = recall_block()

    assert "[location] only wants remote or Stuttgart roles" in block


def test_the_block_is_tagged_and_says_where_it_came_from():
    """The block carries provenance; the rules about it live elsewhere.

    This used to assert the block contained its own instructions - "never cite
    it", "the passage wins". Those sentences were correct and in the wrong
    place: they sat in the system message alongside the facts they governed.
    The rules moved to the system prompt, the facts moved out of it, and what
    stays here is the tag and the statement of where the text came from.
    """
    store.remember("only wants remote roles", category="location")

    block = recall_block()

    assert block.startswith("<remembered_preferences>")
    assert block.endswith("</remembered_preferences>")
    assert "Lower trust than anything in the system message" in block
    assert "not evidence" in block


def test_the_facts_travel_as_a_user_turn():
    """Not a system turn. The system message is the application's own voice.

    These lines were written by an extractor reading an earlier conversation.
    They are the user's, and they belong on the user's side of the boundary -
    which is the whole point of the change.
    """
    store.remember("only wants remote roles", category="location")

    message = recall_message()

    assert message is not None
    assert message["role"] == "user"
    assert message["content"] == recall_block()


def test_nothing_remembered_means_no_turn_at_all():
    """None rather than an empty message.

    An empty turn is not free, and a turn announcing that nothing is remembered
    invites the model to remark on it.
    """
    assert recall_message() is None


def test_fewer_facts_are_injected_than_are_stored():
    """Two limits answering two different questions.

    What is worth keeping is not what is worth spending context on this turn,
    and collapsing them into one number is how a prompt grows until something
    breaks.
    """
    assert MAX_PROMPT_FACTS < MAX_TOTAL
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for index in range(MAX_PROMPT_FACTS + 4):
        text = f"fact number {index}"
        store.remember(text, category="other" if index % 2 else "role")
        _touch(text, when=base + timedelta(minutes=index))

    block = recall_block()

    assert block.count("\n- ") == MAX_PROMPT_FACTS


def test_memory_switched_off_adds_nothing(monkeypatch):
    store.remember("only wants remote roles", category="location")
    monkeypatch.setenv("CC_MEMORY_ENABLED", "false")
    get_settings.cache_clear()

    assert recall_block() == ""


def test_an_unreadable_store_answers_without_memory(monkeypatch):
    """A database problem is not a reason to refuse to answer a question."""

    def _explode(*_args, **_kwargs):
        raise StorageError("database is locked")

    monkeypatch.setattr(recall_module.store, "list_facts", _explode)

    assert recall_block() == ""
