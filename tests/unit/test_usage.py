import pytest

from career_copilot.core.config import get_settings
from career_copilot.core.errors import BudgetExceededError
from career_copilot.core.usage import (
    check_budget,
    estimate_cost_usd,
    month_to_date_usd,
    new_session_id,
    record,
    session_usd,
)


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("CC_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-fake")
    monkeypatch.setenv("CC_MODEL", "openai/gpt-4o-mini")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_cost_matches_price_table():
    # gpt-4o-mini: 0.00015/1k prompt, 0.0006/1k completion
    # 1000 prompt + 500 completion = 0.00015 + 0.00030 = 0.00045
    assert estimate_cost_usd("openai/gpt-4o-mini", 1000, 500) == pytest.approx(0.00045)


def test_unknown_model_costs_zero_and_does_not_raise():
    assert estimate_cost_usd("acme/mystery-model", 1000, 1000) == 0.0


def test_record_persists_and_reads_back():
    sid = new_session_id()
    entry = record(
        session_id=sid,
        operation="chat",
        model="openai/gpt-4o-mini",
        prompt_tokens=1000,
        completion_tokens=500,
        latency_ms=123.4,
    )
    assert entry.cost_usd == pytest.approx(0.00045)
    assert session_usd(sid) == pytest.approx(0.00045)


def test_session_usd_ignores_other_sessions():
    mine, theirs = new_session_id(), new_session_id()
    record(session_id=mine, operation="chat", model="openai/gpt-4o-mini", prompt_tokens=1000)
    record(session_id=theirs, operation="chat", model="openai/gpt-4o-mini", prompt_tokens=8000)
    assert session_usd(mine) == pytest.approx(0.00015)


def test_month_to_date_sums_everything_this_month():
    record(
        session_id=new_session_id(),
        operation="chat",
        model="openai/gpt-4o-mini",
        prompt_tokens=1000,
        completion_tokens=1000,
    )
    assert month_to_date_usd() == pytest.approx(0.00075)


def test_check_budget_passes_when_nothing_spent():
    check_budget(new_session_id())


def test_check_budget_raises_when_session_limit_reached(monkeypatch):
    monkeypatch.setenv("CC_SESSION_BUDGET_USD", "0.0001")
    get_settings.cache_clear()

    sid = new_session_id()
    record(
        session_id=sid,
        operation="chat",
        model="openai/gpt-4o-mini",
        prompt_tokens=10_000,
        completion_tokens=10_000,
    )
    with pytest.raises(BudgetExceededError):
        check_budget(sid)


def test_corrupt_line_is_skipped_not_fatal():
    """An interrupted write leaves a half-line. It must not break cost reporting."""
    sid = new_session_id()
    record(session_id=sid, operation="chat", model="openai/gpt-4o-mini", prompt_tokens=1000)

    path = get_settings().data_dir / "usage.jsonl"
    with path.open("a", encoding="utf-8") as fh:
        fh.write('{"partial": ')

    assert session_usd(sid) == pytest.approx(0.00015)
