"""Shared enums used across retrieval, tools and storage."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

__all__ = ["ApplicationStatus", "DocType", "DraftLanguage", "Profile", "ReviewVerdict"]

#: The languages a generated document can be written in.
DraftLanguage = Literal["en", "de"]

#: What the reviewing agent concluded. `unavailable` means the review did not
#: run, and is deliberately not `ok` - a draft nobody checked must not look
#: like a draft that passed.
ReviewVerdict = Literal["ok", "concerns", "unavailable"]


class Profile(StrEnum):
    AUTOMOTIVE_CYBER = "automotive_cyber"
    DEVOPS = "devops"
    AI_ENG = "ai_eng"
    #: The track for a CV that is none of the above.
    #:
    #: Deliberately last, and deliberately absent from the posting classifier's
    #: vocabulary. A posting it cannot place still resolves to None rather than
    #: landing here, because "unclassified" and "general" are different claims
    #: and a catch-all that silently swallows the first one would undo the
    #: margin rule that classifier was built around.
    #:
    #: It carries real but thin domain material, which the interface says
    #: outright. A track with less behind it is honest; a track pretending to
    #: have the same depth as the other three is not.
    GENERAL = "general"


class DocType(StrEnum):
    RESUME = "resume"
    GUIDE = "guide"
    DOMAIN = "domain"
    JD = "jd"  # job descriptions


class ApplicationStatus(StrEnum):
    """The funnel. Order matters - it is the progression shown on the dashboard."""

    INTERESTED = "interested"
    APPLIED = "applied"
    SCREENING = "screening"
    INTERVIEW = "interview"
    OFFER = "offer"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"
