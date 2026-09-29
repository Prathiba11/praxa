"""Which model answers, and what it costs.

This is the developer half of the application, deliberately kept out of the way
of the working half. The principle is simple:
the settings where you pick a model belong somewhere separate, because the
person using a career assistant is not necessarily someone who knows what a
temperature is.

**The model list is closed, and that is a scar rather than a preference.** An
earlier version of this project let `CC_GRADER_MODEL` be any string. It was set
to an id the account could not reach, every grading call returned 404, and
because grading fails open the application went on answering perfectly while
retrieval grading and memory extraction were dead. Nobody noticed for days. A
free-text box here would be the same bug with a nicer interface, so the choice
is a list of ids known to work, and `scripts/check_models.py` remains the way to
prove any of them still does.

**Changes are process-wide and do not survive a restart.** Setting a model here
writes the environment variable the rest of the application reads and clears the
settings cache, which is the same mechanism `.env` uses - so the effect is
immediate and complete, and it is gone when the server stops. That is the right
scope for a single-user desktop application and the wrong one for anything with
two users, which is why it says so in the response rather than pretending the
choice is saved somewhere.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException
from pydantic import Field

from career_copilot.api.schemas import Camel
from career_copilot.core.config import get_settings
from career_copilot.core.logging import get_logger
from career_copilot.core.tracing import tracing_active

__all__ = ["router"]

log = get_logger(__name__)

router = APIRouter(tags=["settings"], prefix="/settings")


class ModelOption(Camel):
    id: str
    label: str
    provider: str
    #: USD per million tokens, which is the unit people compare in. The config
    #: stores per-thousand because that is what the provider quotes.
    input_per_mtok: float
    output_per_mtok: float
    note: str
    #: What this one is good at and what to watch for, in this application's
    #: terms rather than in benchmark scores. These are working notes, not
    #: measurements - the only measured comparison in this project is the
    #: retrieval evaluation, and it compares settings rather than models.
    strengths: list[str]
    caution: str


#: Four models across four providers, all reachable through OpenRouter with one
#: key. Prices are estimates and the README says so - OpenRouter reports the
#: real cost per generation, which is what the usage ledger records.
_CATALOGUE: tuple[ModelOption, ...] = (
    ModelOption(
        id="openai/gpt-4o-mini",
        label="GPT-4o mini",
        provider="OpenAI",
        input_per_mtok=0.15,
        output_per_mtok=0.60,
        note="The default. Fast, cheap, reliable at tool calling.",
        strengths=[
            "Follows the tool schemas without drifting",
            "Returns the strict JSON the grader parses",
            "Cheap enough to run on every turn",
        ],
        caution="Weakest of the four on long documents - a two-page CV plus a long posting is near the edge of where it stays sharp.",
    ),
    ModelOption(
        id="google/gemini-2.0-flash-001",
        label="Gemini 2.0 Flash",
        provider="Google",
        input_per_mtok=0.10,
        output_per_mtok=0.40,
        note="Cheapest here. Check it with scripts/check_models.py first.",
        strengths=[
            "Lowest cost per turn of the four",
            "Large context, so long postings fit comfortably",
            "Fast first token",
        ],
        caution="This is the id that returned 404 for this account and silently disabled grading for days. Run scripts/check_models.py before trusting it.",
    ),
    ModelOption(
        id="anthropic/claude-3.5-haiku",
        label="Claude 3.5 Haiku",
        provider="Anthropic",
        input_per_mtok=0.80,
        output_per_mtok=4.00,
        note="Stronger on long documents; noticeably more expensive.",
        strengths=[
            "Best of the four at long CVs and postings",
            "Careful about not inventing facts, which is what tailoring needs",
            "Writes cover letters that need less editing",
        ],
        caution="Output is about seven times the price of the default. On a $1 session ceiling that is roughly 190 turns instead of 1,100.",
    ),
    ModelOption(
        id="meta-llama/llama-3.3-70b-instruct",
        label="Llama 3.3 70B",
        provider="Meta",
        input_per_mtok=0.12,
        output_per_mtok=0.30,
        note="Open weights. Weaker at strict JSON, which the grader needs.",
        strengths=[
            "Open weights, so it could be self-hosted later",
            "Cheap output - a third of the default's",
            "Reasonable at straightforward question answering",
        ],
        caution="Least reliable of the four at strict JSON and at tool calling, which is most of what this application asks a model to do.",
    ),
)

_BY_ID = {option.id: option for option in _CATALOGUE}


class SettingsOut(Camel):
    chat_model: str
    grader_model: str
    temperature: float
    max_tokens: int
    session_budget_usd: float
    monthly_budget_usd: float
    tracing: bool
    models: list[ModelOption]
    #: True when the configured model is not one of the four offered - set in
    #: `.env` by hand. The interface shows it rather than silently selecting
    #: something else.
    custom_model: bool


class SettingsUpdate(Camel):
    chat_model: str | None = None
    grader_model: str | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    #: Bounded at both ends rather than left open. Below a few hundred tokens a
    #: tailored CV is cut off mid-sentence and looks like a bug rather than a
    #: setting; above a few thousand a single turn can eat a meaningful share of
    #: the session budget. The ceiling is a guard on the bill, not on the model.
    max_tokens: int | None = Field(default=None, ge=256, le=8_000)


def _current() -> SettingsOut:
    settings = get_settings()
    return SettingsOut(
        chat_model=settings.chat_model,
        grader_model=settings.grader_model,
        temperature=settings.temperature,
        max_tokens=settings.max_tokens,
        session_budget_usd=settings.session_budget_usd,
        monthly_budget_usd=settings.monthly_budget_usd,
        tracing=tracing_active(),
        models=list(_CATALOGUE),
        custom_model=settings.chat_model not in _BY_ID,
    )


@router.get("", response_model=SettingsOut)
def read_settings() -> SettingsOut:
    """What the application is running with right now."""
    return _current()


@router.post("", response_model=SettingsOut)
def update_settings(payload: SettingsUpdate) -> SettingsOut:
    """Change the model, the temperature or the answer length for this server."""
    changes: dict[str, str] = {}

    for field, variable in (("chat_model", "CC_MODEL"), ("grader_model", "CC_GRADER_MODEL")):
        chosen = getattr(payload, field)
        if chosen is None:
            continue
        if chosen not in _BY_ID:
            raise HTTPException(
                status_code=400,
                detail=f"'{chosen}' is not one of the models this build offers.",
            )
        changes[variable] = chosen

    if payload.temperature is not None:
        changes["CC_TEMPERATURE"] = str(payload.temperature)

    if payload.max_tokens is not None:
        changes["CC_MAX_TOKENS"] = str(payload.max_tokens)

    if not changes:
        return _current()

    os.environ.update(changes)
    # Settings are cached for the life of the process, so the change only takes
    # effect once that cache is dropped - the same reason the Streamlit version
    # of this screen cleared it.
    get_settings.cache_clear()

    log.info("settings changed", extra={"changed": sorted(changes)})
    return _current()
