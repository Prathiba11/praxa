"""The spending ceiling and the usage record now live inside `chat`.

The review found that the ceiling only applied where a caller remembered to ask
for it. Of eleven `chat()` call sites in the package, one checked the budget and
two recorded nothing at all, so fit scoring, CV tailoring and cover-letter
generation spent money that no limit covered and no total ever saw.

These tests pin the new guarantee: one code path, checked before the request,
recorded after it, and impossible to call without a session.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from career_copilot.core.config import get_settings
from career_copilot.core.errors import BudgetExceededError, ConfigError
from career_copilot.core.llm import chat
from career_copilot.core.session import use_session
from career_copilot.core.usage import (
    COST_ESTIMATED,
    COST_REPORTED,
    COST_UNKNOWN,
    new_session_id,
    session_usd,
)

FAKE_KEY = "sk-or-v1-SUPERSECRET"
PRICED_MODEL = "openai/gpt-4o-mini"  # present in MODEL_PRICES_USD_PER_1K
UNPRICED_MODEL = "some-vendor/brand-new-model"

PROMPT = [{"role": "user", "content": "hello"}]


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENROUTER_API_KEY", FAKE_KEY)
    monkeypatch.setenv("CC_MODEL", PRICED_MODEL)
    monkeypatch.setenv("CC_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CC_SESSION_BUDGET_USD", "1.0")
    monkeypatch.setenv("CC_MONTHLY_BUDGET_USD", "10.0")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _client(*, model: str = PRICED_MODEL, cost: float | None = None) -> MagicMock:
    """A client whose response carries whatever usage shape we want to test."""
    usage_fields: dict[str, object] = {"prompt_tokens": 1000, "completion_tokens": 1000}
    if cost is not None:
        usage_fields["cost"] = cost
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="ok", tool_calls=None), finish_reason="stop"
            )
        ],
        model=model,
        usage=SimpleNamespace(**usage_fields),
        id="gen-abc123",
    )
    client = MagicMock()
    client.chat.completions.create.return_value = response
    return client


def _usage_lines(tmp_path) -> list[dict]:
    path = tmp_path / "usage.jsonl"
    if not path.exists():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


# --------------------------------------------------------------------------
# The hole the review found
# --------------------------------------------------------------------------


def test_budget_is_checked_before_the_request_goes_out(tmp_path):
    """A refused turn must cost nothing, so the check precedes the call."""
    session_id = new_session_id()
    client = _client(cost=5.00)  # one expensive call blows the $1 session ceiling

    with patch("career_copilot.core.llm.get_client", return_value=client):
        chat(PROMPT, session_id=session_id, operation="first")

        with pytest.raises(BudgetExceededError):
            chat(PROMPT, session_id=session_id, operation="second")

    # Exactly one request reached the provider: the second never went out.
    assert client.chat.completions.create.call_count == 1


def test_a_call_with_no_explicit_session_is_still_budgeted(tmp_path):
    """This is the tool case.

    A tool's signature is fixed by the schema the model sees, so it cannot be
    handed a session id. It inherits the ambient one instead - and is therefore
    subject to the same ceiling as everything else in the turn.
    """
    session_id = new_session_id()
    client = _client(cost=5.00)

    with patch("career_copilot.core.llm.get_client", return_value=client), use_session(session_id):
        chat(PROMPT, operation="agent_turn")

        with pytest.raises(BudgetExceededError):
            chat(PROMPT, operation="score_job_fit")  # what a tool call looks like

    assert client.chat.completions.create.call_count == 1


def test_usage_is_recorded_without_the_caller_asking(tmp_path):
    session_id = new_session_id()

    with patch("career_copilot.core.llm.get_client", return_value=_client(cost=0.02)):
        chat(PROMPT, session_id=session_id, operation="score_job_fit")

    records = _usage_lines(tmp_path)
    assert len(records) == 1
    assert records[0]["operation"] == "score_job_fit"
    assert records[0]["session_id"] == session_id
    assert session_usd(session_id) == pytest.approx(0.02)


def test_usage_is_recorded_exactly_once_per_call(tmp_path):
    """Call sites used to record for themselves; doing both would double-count."""
    session_id = new_session_id()

    with patch("career_copilot.core.llm.get_client", return_value=_client(cost=0.01)):
        chat(PROMPT, session_id=session_id, operation="one")
        chat(PROMPT, session_id=session_id, operation="two")

    assert len(_usage_lines(tmp_path)) == 2


def test_a_call_with_no_session_at_all_is_refused(tmp_path):
    """Unattributed spending is the bug, so it is an error rather than a default."""
    with (
        patch("career_copilot.core.llm.get_client", return_value=_client()),
        pytest.raises(ConfigError),
    ):
        chat(PROMPT, operation="orphan")


# --------------------------------------------------------------------------
# Where the cost figure comes from
# --------------------------------------------------------------------------


def test_reported_cost_beats_the_price_table(tmp_path):
    """2000 tokens of gpt-4o-mini estimates well under a dollar.

    Recording $0.75 proves the provider's own figure was used rather than ours.
    """
    session_id = new_session_id()

    with patch("career_copilot.core.llm.get_client", return_value=_client(cost=0.75)):
        chat(PROMPT, session_id=session_id, operation="priced")

    record = _usage_lines(tmp_path)[0]
    assert record["cost_source"] == COST_REPORTED
    assert record["cost_usd"] == pytest.approx(0.75)


def test_price_table_is_the_fallback_when_the_provider_reports_nothing(tmp_path):
    session_id = new_session_id()

    with patch("career_copilot.core.llm.get_client", return_value=_client(cost=None)):
        chat(PROMPT, session_id=session_id, operation="unreported")

    record = _usage_lines(tmp_path)[0]
    assert record["cost_source"] == COST_ESTIMATED
    assert record["cost_usd"] > 0.0


def test_an_unpriced_model_is_marked_unknown_rather_than_free(tmp_path):
    """The review's point: Claude Haiku and Llama were recording $0.00.

    Zero is still recorded - there is nothing better to record - but the source
    says so, which is what stops a total being read as complete.
    """
    session_id = new_session_id()
    client = _client(model=UNPRICED_MODEL, cost=None)

    with patch("career_copilot.core.llm.get_client", return_value=client):
        chat(PROMPT, session_id=session_id, operation="unpriced")

    record = _usage_lines(tmp_path)[0]
    assert record["cost_source"] == COST_UNKNOWN
    assert record["cost_usd"] == 0.0


def test_the_real_cost_is_asked_for_on_every_request(tmp_path):
    """Without this in the request body OpenRouter does not return a cost."""
    client = _client(cost=0.01)

    with patch("career_copilot.core.llm.get_client", return_value=client):
        chat(PROMPT, session_id=new_session_id(), operation="ask")

    sent = client.chat.completions.create.call_args.kwargs
    assert sent["extra_body"] == {"usage": {"include": True}}


def test_a_fresh_session_does_not_reset_the_ceiling(tmp_path):
    """The per-session limit is not the only limit, and it must not be.

    A session id arrives from the client. Anyone minting a new one per turn -
    a buggy frontend as easily as a hostile one - would reset the session
    ceiling on every request and spend without bound. The monthly ceiling is
    the one that does not care which thread asked.
    """
    monthly_ceiling_blower = _client(cost=11.00)  # over the $10 month, under no session

    with patch("career_copilot.core.llm.get_client", return_value=monthly_ceiling_blower):
        chat(PROMPT, session_id=new_session_id(), operation="first")

        with pytest.raises(BudgetExceededError) as raised:
            # A different session every time, which defeats the session ceiling
            # and nothing else.
            chat(PROMPT, session_id=new_session_id(), operation="second")

    assert "month-to-date" in raised.value.detail
    assert monthly_ceiling_blower.chat.completions.create.call_count == 1
