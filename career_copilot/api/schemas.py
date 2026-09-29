"""Request and response shapes for /api.

These mirror `frontend/src/lib/types.ts` field for field. The TypeScript was
written first, deliberately: it settled what the client needs before the
endpoints existed, and it is the thing to change first when a shape changes.

Field names are camelCase because the consumer is a browser. Python keeps
snake_case internally and the alias generator bridges the two, so neither side
has to write the other's convention.

The agent's own vocabulary - phases, tool states, grader verdicts - is not
redefined here. It is imported from `core.events`, which owns it. A literal
copied into this file would drift the first time a phase was added.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel

from career_copilot.core.events import Phase as AgentPhase
from career_copilot.core.events import ToolState, Verdict
from career_copilot.core.types import Profile

__all__ = [
    "AgentPhase",
    "AnswerOut",
    "AnswerRequest",
    "ApplicationStatusValue",
    "ApprovalOut",
    "Camel",
    "CategoryUse",
    "ChatRequest",
    "Citation",
    "DifficultyValue",
    "DoneEvent",
    "DraftOut",
    "DraftRequest",
    "ErrorEvent",
    "FeedbackOut",
    "FeedbackSummary",
    "FitOut",
    "FunnelCounts",
    "HealthResponse",
    "InterviewOptions",
    "InterviewSessionOut",
    "JobDetail",
    "JobSummary",
    "MemoryPreview",
    "Mode",
    "ModeTallyOut",
    "MoveValue",
    "PasteJobRequest",
    "PersonaOut",
    "ProfileValue",
    "QuestionOut",
    "RateRequest",
    "RatingValue",
    "ReviewOut",
    "ScoreOut",
    "SetStatusRequest",
    "StartInterviewRequest",
    "StreamCitations",
    "TokenEvent",
    "ToolState",
    "TurnOut",
    "TurnUsage",
    "UsageSummary",
    "Verdict",
]

Mode = Literal["chat", "jobs", "interview"]

# An identifier the client mints and we key a conversation on. Deliberately
# narrow: it reaches the usage log, so it must not be free-form text.
_ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"


class Camel(BaseModel):
    """Serialises as camelCase, accepts either spelling on the way in."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class HealthResponse(Camel):
    status: Literal["ok"]
    version: str
    tracing: bool
    #: Which LangSmith project the turns land in, and the web address to read
    #: them at. Both null when tracing is off - an interface that offers a link
    #: to an empty project is worse than one that says tracing is off.
    tracing_project: str | None = None
    tracing_url: str | None = None


class Citation(Camel):
    marker: int = Field(description="1-based marker as it appears in the answer text")
    document_id: str
    document_title: str
    section: str | None = None
    snippet: str
    score: float | None = None


class TurnUsage(Camel):
    """What one turn cost. Zero calls means zero tokens, not an error."""

    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    cost_source: str = Field(description="openrouter | estimated | unknown | mixed")
    model: str
    latency_ms: float


class UsageSummary(Camel):
    session_tokens: int
    session_cost_usd: float
    session_budget_usd: float
    month_to_date_usd: float
    monthly_budget_usd: float
    budget_remaining_usd: float
    estimated_cost_per_answer_usd: float
    unpriced_calls: int = Field(
        description="Calls with no real cost figure. A total built from these understates spend."
    )


class ChatRequest(Camel):
    thread_id: str = Field(pattern=_ID_PATTERN)
    mode: Mode = "chat"
    message: str = Field(min_length=1)

    @field_validator("message")
    @classmethod
    def _not_only_whitespace(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("message is empty")
        return stripped


# ------------------------------------------------------------------ streaming
#
# The frames on the SSE stream. `core.events` supplies status, tool and
# retrieval; these three complete the set and exist only at this layer,
# because only this layer has an answer, a bill and an HTTP error to report.


class TokenEvent(Camel):
    type: Literal["token"] = "token"
    text: str


class StreamCitations(Camel):
    type: Literal["citations"] = "citations"
    citations: list[Citation]


class DoneEvent(Camel):
    type: Literal["done"] = "done"
    message_id: str
    usage: TurnUsage


class ErrorEvent(Camel):
    """A failure after the response has already begun.

    The status line is long gone by then - it said 200 before the first token
    was written - so the only way to report a failure mid-stream is in the
    stream. The code matches the one an ordinary error response would carry.
    """

    type: Literal["error"] = "error"
    code: str
    message: str
    correlation_id: str | None = None


# ---------------------------------------------------------------------- jobs
#
# The page owns the data; the agent owns the tools. Scoring fit, tailoring a CV
# and writing a cover letter are all agent tools already, reachable from chat in
# `jobs` mode - so they are deliberately not endpoints here. Re-exposing them
# would mean two implementations of every action, and the second one would be
# the one that drifted.

ProfileValue = Literal["automotive_cyber", "devops", "ai_eng", "general"]

ApplicationStatusValue = Literal[
    "interested", "applied", "screening", "interview", "offer", "rejected", "withdrawn"
]


class JobSummary(Camel):
    """One row in the list. Enough to decide whether to open it."""

    id: str
    title: str
    company: str
    location: str | None = None
    url: str | None = None
    source: str
    profile: ProfileValue | None = None
    fit_score: float | None = None
    status: ApplicationStatusValue | None = None
    posted_at: datetime | None = None
    first_seen_at: datetime


class FitOut(Camel):
    """What scoring one posting against one CV produced.

    Mirrors `tools.fit.FitReport` rather than wrapping it, so the page shows the
    same four lists the agent sees. `score` is evidence only: it answers "does
    the CV evidence what this posting asks for", and never moves because of a
    stated preference - those land in `conflicts`.
    """

    profile: ProfileValue
    score: float
    matched: list[str] = []
    missing: list[str] = []
    blockers: list[str] = []
    conflicts: list[str] = []
    verdict: str = ""


class JobDetail(JobSummary):
    """Everything, including the posting text.

    The description is sent whole rather than truncated: it is what a fit score
    was computed from, and a user checking that score needs to read the same
    thing the model did.
    """

    description: str
    language: str | None = None
    note: str | None = None
    cv_path: str | None = None
    letter_path: str | None = None


class FunnelCounts(Camel):
    """How many applications sit at each stage, plus everything untriaged."""

    counts: dict[str, int]
    total_jobs: int


class SetStatusRequest(Camel):
    status: ApplicationStatusValue
    note: str | None = Field(default=None, max_length=2000)


class PasteJobRequest(Camel):
    """A posting copied out of a browser.

    `source` is fixed rather than accepted from the client: attribution is a
    licence condition on the job boards this application reads, and "where did
    this come from" is not a field a caller should be able to make up.

    Only `description` is required. Asking for a title and a company before
    anything could be saved made the quickest path - copy the whole posting,
    paste it - the most tedious one. Both are read out of the pasted text when
    they are not given, and fall back to a placeholder the user can correct;
    an invented company name would change the deduplication fingerprint and
    store the same job twice, so a placeholder is safer than a guess.
    """

    description: str = Field(min_length=20, max_length=40000)
    title: str | None = Field(default=None, max_length=300)
    company: str | None = Field(default=None, max_length=200)
    location: str | None = Field(default=None, max_length=200)
    url: str | None = Field(default=None, max_length=1000)
    profile: ProfileValue | None = None


# -------------------------------------------------------------------- memory

MemoryCategoryValue = Literal[
    "role", "location", "language", "must_have", "deal_breaker", "application", "other"
]


MemoryOrigin = Literal["extracted", "stated"]


class MemoryFactOut(Camel):
    """One remembered fact, as the page shows it.

    `origin` is not decoration. A user reviewing this needs to know which of
    these they said outright and which the extractor inferred from a turn -
    those warrant different amounts of trust, and the second kind is what they
    are most likely to want to delete.
    """

    id: int
    category: MemoryCategoryValue
    text: str
    origin: MemoryOrigin
    created_at: datetime
    last_seen_at: datetime


class CategoryUse(Camel):
    category: MemoryCategoryValue
    count: int


class MemoryPreview(Camel):
    """What memory will actually contribute to the next answer.

    The interface used to describe this in prose - "at most eight of these
    reach any one answer" - which asks the reader to trust a sentence about
    code. `block` is the string itself, taken from the same function the agent
    calls, so the page shows the feature rather than a description of it.
    """

    #: Exactly what `memory.recall.recall_block()` returns, empty string
    #: included. An empty block is the honest answer when memory is off or
    #: nothing is stored, and the page says so rather than hiding the panel.
    block: str
    enabled: bool
    stored: int
    max_stored: int
    max_per_category: int
    max_per_answer: int
    per_category: list[CategoryUse]
    #: The fact that has gone longest without being mentioned, and so the first
    #: to be dropped when its category fills. None when nothing is stored.
    least_recently_mentioned: str | None = None


class RememberRequest(Camel):
    text: str = Field(min_length=3, max_length=300)
    category: MemoryCategoryValue = "other"


# ------------------------------------------------------------------ feedback
# A rating is the user's opinion of one answer. The client sends the turn's
# text with it because nothing else stores that text - see
# `storage.models.ResponseFeedback` for why there is no transcript to join to.


RatingValue = Literal["up", "down"]


class RateRequest(Camel):
    message_id: str = Field(pattern=r"^[A-Za-z0-9]{1,32}$")
    thread_id: str = Field(pattern=_ID_PATTERN)
    rating: RatingValue
    mode: Mode = "chat"
    model: str = Field(min_length=1, max_length=120)
    question: str = Field(min_length=1)
    answer: str = Field(min_length=1)


class FeedbackOut(Camel):
    id: int
    message_id: str
    rating: RatingValue
    mode: Mode
    model: str
    question: str
    answer: str
    created_at: datetime


class ModeTallyOut(Camel):
    mode: Mode
    up: int
    down: int


class FeedbackSummary(Camel):
    up: int
    down: int
    total: int
    #: Share of rated answers that were rated up, or None when nothing is rated
    #: yet. None rather than 0.0, because "no ratings" and "every rating was
    #: negative" are opposite readings of the same number.
    approval: float | None
    max_stored: int
    by_mode: list[ModeTallyOut]
    recent: list[FeedbackOut]


# ----------------------------------------------------------------- documents
# A generated CV or letter is the one thing here that leaves the machine and
# goes to a stranger with the candidate's name on it. Everything else the agent
# does is reversible; a document sent to an employer is not. So the HTTP layer
# splits what the tool does in one step: generate, then approve.


DraftKindValue = Literal["cv", "letter"]
LanguageValue = Literal["en", "de"]


class DraftRequest(Camel):
    """Ask for a document, to be read before it is written anywhere."""

    profile: ProfileValue
    kind: DraftKindValue
    job_id: str | None = None
    job_text: str | None = Field(default=None, max_length=20000)
    language: LanguageValue = "en"


class ReviewOut(Camel):
    """What the reviewing agent said about a draft.

    `verdict` has three values, not two. `unavailable` means the review did not
    run, and collapsing that into `ok` would let a draft nobody checked look
    like a draft that passed - which is the one mistake this field exists to
    prevent.
    """

    verdict: Literal["ok", "concerns", "unavailable"]
    invented: list[str]
    notes: str


class DraftOut(Camel):
    """A document waiting on a person.

    `gaps` repeats the part of `body` that lists what the posting asked for and
    the CV cannot support. It is separated because it is the section that most
    decides whether to approve, and at the bottom of a two-page CV it is the
    section most likely to be scrolled past.
    """

    draft_id: str
    kind: DraftKindValue
    profile: Profile
    language: LanguageValue
    job_label: str
    job_id: str | None
    body: str
    gaps: str
    review: ReviewOut
    created_at: datetime


class ApprovalOut(Camel):
    """What approving wrote, named so the user can go and find it."""

    draft_id: str
    files: list[str]
    message: str


# ----------------------------------------------------------------- interview

DifficultyValue = Literal["warmup", "standard", "hard"]

#: What happens after an answer is scored: a follow-up on the same question,
#: a fresh one, or the end of the session.
MoveValue = Literal["probe", "next", "finish"]


class PersonaOut(Camel):
    """One interviewer the session can be run as."""

    key: str
    name: str
    #: The first thing they say. Shown so the choice is concrete rather than a
    #: label - "Friendly recruiter" means little until you read their opener.
    opening: str


class InterviewOptions(Camel):
    """Everything the start form needs, so the page hard-codes nothing."""

    personas: list[PersonaOut]
    difficulties: list[DifficultyValue]
    default_persona: str
    default_questions: int


class StartInterviewRequest(Camel):
    profile: ProfileValue
    persona: str
    difficulty: DifficultyValue = "standard"
    questions: int = Field(default=5, ge=1, le=12)
    #: Interview against one saved posting rather than the profile in general.
    job_id: str | None = None


class QuestionOut(Camel):
    text: str
    #: Where the question came from. Shown, because a question grounded in the
    #: candidate's own material and one invented from the profile name are not
    #: the same thing and the difference should not be invisible.
    grounding: str
    focus: str = ""


class ScoreOut(Camel):
    """One answer, graded on five dimensions out of five."""

    structure: float
    specificity: float
    ownership: float
    impact: float
    relevance: float
    overall: float
    feedback: str = ""
    improved_answer: str = ""


class TurnOut(Camel):
    question: str
    answer: str
    score: ScoreOut
    is_probe: bool = False


class AnswerRequest(Camel):
    question: str
    answer: str = Field(min_length=1, max_length=20000)
    is_probe: bool = False
    #: "typed" or "spoken". Stored, so a later look at the transcript can tell
    #: a written answer from a transcribed one.
    captured_as: str = "typed"
    duration_seconds: float | None = None


class AnswerOut(Camel):
    """What one submitted answer produced.

    `move` is `probe` when the next thing is a follow-up on the same question,
    `next` for a fresh one, and `finish` when the session is over. `probe` and
    `summary` are populated to match.
    """

    score: ScoreOut
    move: MoveValue
    probe: QuestionOut | None = None
    summary: str | None = None


class InterviewSessionOut(Camel):
    session_id: str
    profile: ProfileValue
    persona: PersonaOut
    difficulty: DifficultyValue
    planned_questions: int
    job_id: str | None = None
    turns: list[TurnOut] = Field(default_factory=list)
    #: Only on a fresh start: the opening question. A restore does not carry one
    #: because an unanswered question was never stored - the page asks for a new
    #: one, which is honest: nothing the candidate produced is lost.
    question: QuestionOut | None = None
