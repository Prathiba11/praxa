"""Who is doing the interviewing, and how hard they are.

Three personas rather than one, because the same answer earns different
reactions from different rooms and practising against only the friendly version
is how people get surprised. Each persona carries a `probe_threshold`: the score
below which it refuses to move on and asks a follow-up instead. That number is
the persona - a friendly screener accepts a 2.5 and continues, a principal
engineer does not.

Difficulty is a separate axis and shifts the threshold rather than replacing it,
so "hard" means the same interviewer being less easily satisfied, not a different
person. Both are clamped so no combination can demand a perfect answer forever.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from career_copilot.interview.rubric import MAX_SCORE

__all__ = [
    "DEFAULT_PERSONA",
    "PERSONAS",
    "Difficulty",
    "Persona",
    "get_persona",
    "persona_keys",
    "probe_threshold",
]

_MAX_THRESHOLD = 4.0


class Difficulty(StrEnum):
    WARMUP = "warmup"
    STANDARD = "standard"
    HARD = "hard"


_DIFFICULTY_SHIFT: dict[Difficulty, float] = {
    Difficulty.WARMUP: -0.5,
    Difficulty.STANDARD: 0.0,
    Difficulty.HARD: +0.75,
}

DIFFICULTY_GUIDANCE: dict[Difficulty, str] = {
    Difficulty.WARMUP: (
        "Ask a broad, welcoming question about experience the candidate is "
        "likely to have. No trick framing."
    ),
    Difficulty.STANDARD: (
        "Ask what a competent interviewer would ask at this level: a specific "
        "scenario that requires a concrete story to answer well."
    ),
    Difficulty.HARD: (
        "Ask about a failure, a trade-off with no clean answer, or a decision "
        "the candidate would have to defend. Make it hard to answer vaguely."
    ),
}


@dataclass(frozen=True)
class Persona:
    key: str
    name: str
    style: str
    opening: str
    base_threshold: float


PERSONAS: dict[str, Persona] = {
    "recruiter": Persona(
        key="recruiter",
        name="Friendly recruiter",
        style=(
            "a warm first-round recruiter. You are checking for a coherent story "
            "and clear communication, not deep technical depth. You are "
            "encouraging, and you rephrase rather than pounce when an answer "
            "wanders."
        ),
        opening="Thanks for making the time. Let's start easy.",
        base_threshold=2.0,
    ),
    "tech_lead": Persona(
        key="tech_lead",
        name="Technical lead",
        style=(
            "the engineering lead this person would report to. You care how "
            "something was built and why that way. You ask for the specific "
            "tool, the specific number, the specific trade-off, and you notice "
            "when a story has no measurable outcome."
        ),
        opening="I'd like to get into how you actually work.",
        base_threshold=3.0,
    ),
    "principal": Persona(
        key="principal",
        name="Skeptical principal",
        style=(
            "a principal engineer who has heard every rehearsed answer. You are "
            "civil but unimpressed by fluency. You test claims, ask what went "
            "wrong, and follow up on anything stated without evidence. You do "
            "not accept 'we' as an answer to 'what did you do'."
        ),
        opening="I'll push on the details. That's not hostility, it's the job.",
        base_threshold=3.5,
    ),
}

DEFAULT_PERSONA = "tech_lead"


def persona_keys() -> list[str]:
    return list(PERSONAS)


def get_persona(key: str) -> Persona:
    """Unknown keys fall back rather than raise.

    A persona is a presentation choice. Refusing to start an interview because
    a stored session names a persona a later version renamed would be a bad
    trade for the strictness it buys.
    """
    return PERSONAS.get(key, PERSONAS[DEFAULT_PERSONA])


def probe_threshold(persona: Persona, difficulty: Difficulty) -> float:
    """The score below which this interviewer follows up instead of moving on.

    Clamped below MAX_SCORE so that no persona-difficulty pair can insist on a
    perfect answer - that would probe forever, which the step cap would catch
    but which would still be the wrong behaviour to build in.
    """
    shifted = persona.base_threshold + _DIFFICULTY_SHIFT[difficulty]
    return max(0.0, min(_MAX_THRESHOLD, min(shifted, MAX_SCORE - 1.0)))
