"""Mock interviews: personas, a fixed rubric, and a deterministic state machine.

The model writes the questions and grades the answers. It does not decide what
happens next - see `engine` for why that line is drawn where it is.
"""

from career_copilot.interview.engine import (
    DEFAULT_QUESTIONS,
    InterviewError,
    Move,
    Plan,
    decide_next,
    probe_question,
    write_summary,
)
from career_copilot.interview.personas import (
    DEFAULT_PERSONA,
    PERSONAS,
    Difficulty,
    Persona,
    get_persona,
    persona_keys,
    probe_threshold,
)
from career_copilot.interview.questions import Question, next_question
from career_copilot.interview.rubric import (
    DIMENSIONS,
    MAX_SCORE,
    Dimension,
    RubricScore,
    dimension_keys,
    score_answer,
)

__all__ = [
    "DEFAULT_PERSONA",
    "DEFAULT_QUESTIONS",
    "DIMENSIONS",
    "MAX_SCORE",
    "PERSONAS",
    "Difficulty",
    "Dimension",
    "InterviewError",
    "Move",
    "Persona",
    "Plan",
    "Question",
    "RubricScore",
    "decide_next",
    "dimension_keys",
    "get_persona",
    "next_question",
    "persona_keys",
    "probe_question",
    "probe_threshold",
    "score_answer",
    "write_summary",
]
