"""Token and cost accounting, with a hard spend ceiling.

Records go to a JSONL file for now; a later phase moves them to SQLite behind
the same functions.

**Cost comes from the provider, not from us.** OpenRouter reports what a
generation actually cost, and ``core.llm`` asks for that figure on every
request. The static price table is a fallback for when the provider omits it,
and every record says which of the two it used - so a total is never quietly
built out of arithmetic against prices that changed months ago, and a model
missing from the table no longer records ``$0.00`` as if it were free.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from career_copilot.core.config import MODEL_PRICES_USD_PER_1K, get_settings
from career_copilot.core.errors import BudgetExceededError
from career_copilot.core.llm_types import ChatResult
from career_copilot.core.logging import get_logger

__all__ = [
    "COST_ESTIMATED",
    "COST_REPORTED",
    "COST_UNKNOWN",
    "SessionTotals",
    "UsageRecord",
    "check_budget",
    "estimate_cost_usd",
    "month_to_date_usd",
    "new_session_id",
    "record",
    "record_chat",
    "session_totals",
    "session_usd",
    "unpriced_usd",
]

log = get_logger(__name__)

# What a stored cost figure is made of.
COST_REPORTED = "openrouter"  # the real charge, as the provider reported it
COST_ESTIMATED = "estimated"  # our arithmetic against the static price table
COST_UNKNOWN = "unknown"  # neither available; the figure is 0.0 and is a lie


class UsageRecord(BaseModel):
    ts: datetime = Field(default_factory=lambda: datetime.now(UTC))
    session_id: str
    operation: str  # chat | embed | rerank | stt | tts
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    cost_source: str = COST_UNKNOWN
    latency_ms: float = 0.0
    generation_id: str | None = None


def new_session_id() -> str:
    return uuid.uuid4().hex[:12]


def _usage_path() -> Path:
    return get_settings().data_dir / "usage.jsonl"


def estimate_cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Estimate from the static price table. Unknown models cost 0.0 and warn.

    Kept as it was. `_resolve_cost` asks the price table whether it knows the
    model rather than reading 0.0 as an answer, so "free" and "we have no idea"
    stay distinguishable without changing this function's contract.
    """
    prices = MODEL_PRICES_USD_PER_1K.get(model)
    if prices is None:
        log.warning("no price entry for model - cost recorded as 0", extra={"model": model})
        return 0.0
    prompt_per_1k, completion_per_1k = prices
    return (prompt_tokens / 1000) * prompt_per_1k + (completion_tokens / 1000) * completion_per_1k


def _resolve_cost(
    *,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    reported_usd: float | None,
) -> tuple[float, str]:
    """Prefer the provider's figure, fall back to ours, and say which."""
    if reported_usd is not None:
        return reported_usd, COST_REPORTED

    if model in MODEL_PRICES_USD_PER_1K:
        return estimate_cost_usd(model, prompt_tokens, completion_tokens), COST_ESTIMATED

    log.warning(
        "no cost for this call - provider reported none and the model is not priced",
        extra={"model": model},
    )
    return 0.0, COST_UNKNOWN


def record(
    *,
    session_id: str,
    operation: str,
    model: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    latency_ms: float = 0.0,
    generation_id: str | None = None,
    reported_cost_usd: float | None = None,
) -> UsageRecord:
    """Append one usage record and return it."""
    cost_usd, cost_source = _resolve_cost(
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        reported_usd=reported_cost_usd,
    )
    entry = UsageRecord(
        session_id=session_id,
        operation=operation,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost_usd=cost_usd,
        cost_source=cost_source,
        latency_ms=latency_ms,
        generation_id=generation_id,
    )
    path = _usage_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(entry.model_dump_json() + "\n")
    return entry


def record_chat(result: ChatResult, *, session_id: str, operation: str = "chat") -> UsageRecord:
    """Convenience wrapper for the common case.

    Called by ``core.llm.chat`` on every request. Calling it again from a call
    site would double-count.
    """
    return record(
        session_id=session_id,
        operation=operation,
        model=result.model,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
        latency_ms=result.latency_ms,
        generation_id=result.generation_id,
        reported_cost_usd=result.cost_usd,
    )


def _read_all() -> list[UsageRecord]:
    """Linear scan. Fine at this scale; SQLite takes over later."""
    path = _usage_path()
    if not path.exists():
        return []
    records: list[UsageRecord] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            records.append(UsageRecord.model_validate_json(line))
        except ValueError:  # a truncated final line from an interrupted write
            log.warning("skipping unparseable usage line")
    return records


def session_usd(session_id: str) -> float:
    return sum(r.cost_usd for r in _read_all() if r.session_id == session_id)


class SessionTotals(BaseModel):
    """Everything one session has spent, in one pass over the log.

    The API needs tokens, money and honesty about the money in the same
    response; three separate helpers would mean three scans and three chances
    for the numbers to disagree with each other.
    """

    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    reported_calls: int = 0
    estimated_calls: int = 0
    unpriced_calls: int = 0

    @property
    def cost_source(self) -> str:
        """One label for a figure assembled from several kinds of call.

        ``mixed`` is not a fudge - it is the accurate answer when part of a
        total is a real charge and part is arithmetic, and collapsing it to
        either of those would overstate what is known.
        """
        kinds = {
            COST_REPORTED if self.reported_calls else "",
            COST_ESTIMATED if self.estimated_calls else "",
            COST_UNKNOWN if self.unpriced_calls else "",
        } - {""}
        if not kinds:
            return COST_UNKNOWN
        if len(kinds) == 1:
            return kinds.pop()
        return "mixed"

    def since(self, earlier: SessionTotals) -> SessionTotals:
        """This total minus an earlier one - the usage of whatever ran between.

        How a single turn is measured: snapshot before, snapshot after. It is
        only correct while one session runs one turn at a time, which is what
        the API guarantees by serialising turns per thread.
        """
        return SessionTotals(
            calls=self.calls - earlier.calls,
            prompt_tokens=self.prompt_tokens - earlier.prompt_tokens,
            completion_tokens=self.completion_tokens - earlier.completion_tokens,
            cost_usd=self.cost_usd - earlier.cost_usd,
            reported_calls=self.reported_calls - earlier.reported_calls,
            estimated_calls=self.estimated_calls - earlier.estimated_calls,
            unpriced_calls=self.unpriced_calls - earlier.unpriced_calls,
        )


def session_totals(session_id: str) -> SessionTotals:
    records = [r for r in _read_all() if r.session_id == session_id]
    return SessionTotals(
        calls=len(records),
        prompt_tokens=sum(r.prompt_tokens for r in records),
        completion_tokens=sum(r.completion_tokens for r in records),
        cost_usd=sum(r.cost_usd for r in records),
        reported_calls=sum(1 for r in records if r.cost_source == COST_REPORTED),
        estimated_calls=sum(1 for r in records if r.cost_source == COST_ESTIMATED),
        unpriced_calls=sum(1 for r in records if r.cost_source == COST_UNKNOWN),
    )


def month_to_date_usd() -> float:
    now = datetime.now(UTC)
    return sum(r.cost_usd for r in _read_all() if r.ts.year == now.year and r.ts.month == now.month)


def unpriced_usd(session_id: str | None = None) -> int:
    """How many calls carry no real cost figure at all.

    Surfaced in the UI next to the spend: a total assembled from records whose
    source is ``unknown`` understates what was actually spent, and the honest
    thing is to show that rather than a confident wrong number.
    """
    records = _read_all()
    if session_id is not None:
        records = [r for r in records if r.session_id == session_id]
    return sum(1 for r in records if r.cost_source == COST_UNKNOWN)


def check_budget(session_id: str) -> None:
    """Call BEFORE spending money.

    Raises:
        BudgetExceededError: the session or monthly ceiling is already reached.
    """
    settings = get_settings()

    spent_session = session_usd(session_id)
    if spent_session >= settings.session_budget_usd:
        raise BudgetExceededError(
            f"session spend ${spent_session:.4f} >= limit ${settings.session_budget_usd:.2f}"
        )

    spent_month = month_to_date_usd()
    if spent_month >= settings.monthly_budget_usd:
        raise BudgetExceededError(
            f"month-to-date ${spent_month:.4f} >= limit ${settings.monthly_budget_usd:.2f}"
        )
