"""Documents that have been written but not yet accepted.

The gap this closes is the one the threat analysis keeps coming back to. A job
posting is text a stranger wrote, fetched automatically, and handed to a model
along with the candidate's CV. Every control around that is a *restriction* -
the posting is delimited, the mode owns a narrow tool set, generation is told to
invent nothing. All of them are automatic, and all of them are the system
judging its own output.

A draft is the other kind of control: a person reads the thing before it becomes
a file. Generation and persistence used to be one step, so the only way to find
out what a tailored CV said was to open the file that had already been written.
Now generation produces a draft, a human reads it, and approval is what writes
it to disk.

**Why this lives in memory rather than the database.** A draft is deliberately
short-lived: it exists between "show me" and "yes" or "no", which is one person
reading for a minute. Giving it a table would mean a migration, a retention
policy and a cleanup job for state whose whole purpose is to be resolved and
thrown away. The cost is real and stated in the README: drafts do not survive a
restart of the server, and a second server process would not see them. For a
single-user desktop application that is the right trade; the moment there are
two processes it is not.

Bounded, because an unbounded store of generated documents in a long-running
process is a slow memory leak with the user's CV in it.
"""

from __future__ import annotations

import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from career_copilot.core.types import DraftLanguage, Profile, ReviewVerdict

__all__ = ["MAX_PENDING_DRAFTS", "Draft", "DraftKind", "DraftStore", "drafts"]

DraftKind = Literal["cv", "letter"]

#: How many unresolved drafts are kept. Reaching this means the user has
#: generated twenty documents without accepting or rejecting any of them, which
#: is not a workflow to support - the oldest is dropped.
MAX_PENDING_DRAFTS = 20


@dataclass(frozen=True)
class Draft:
    """One generated document, waiting for a person to say yes or no."""

    draft_id: str
    kind: DraftKind
    profile: Profile
    language: DraftLanguage
    job_label: str
    job_id: str | None
    job_slug: str
    body: str
    created_at: datetime
    #: What the reviewing agent found. `unavailable` means the review did not
    #: run - deliberately not the same value as `ok`, because a draft nobody
    #: checked must not look like a draft that passed.
    review_verdict: ReviewVerdict = "unavailable"
    review_invented: list[str] = field(default_factory=list)
    review_notes: str = ""

    @property
    def gaps(self) -> str:
        """The "Gaps against this posting" section, if the model wrote one.

        Pulled out so the review panel can show it separately. It is the part a
        person most needs to read before approving: everything the posting asked
        for that the CV cannot honestly support. Buried at the bottom of a long
        document it gets scrolled past.
        """
        marker = "## Gaps against this posting"
        index = self.body.find(marker)
        if index == -1:
            return ""
        return self.body[index + len(marker) :].strip()


class DraftStore:
    """A bounded, in-process store of pending drafts, oldest evicted first."""

    def __init__(self, limit: int = MAX_PENDING_DRAFTS) -> None:
        self._limit = limit
        self._items: OrderedDict[str, Draft] = OrderedDict()

    def put(
        self,
        *,
        kind: DraftKind,
        profile: Profile,
        language: DraftLanguage,
        job_label: str,
        job_id: str | None,
        job_slug: str,
        body: str,
        review_verdict: ReviewVerdict = "unavailable",
        review_invented: list[str] | None = None,
        review_notes: str = "",
    ) -> Draft:
        draft = Draft(
            draft_id=uuid.uuid4().hex[:12],
            kind=kind,
            profile=profile,
            language=language,
            job_label=job_label,
            job_id=job_id,
            job_slug=job_slug,
            body=body,
            created_at=datetime.now(UTC),
            review_verdict=review_verdict,
            review_invented=list(review_invented or []),
            review_notes=review_notes,
        )
        self._items[draft.draft_id] = draft
        while len(self._items) > self._limit:
            self._items.popitem(last=False)
        return draft

    def get(self, draft_id: str) -> Draft | None:
        return self._items.get(draft_id)

    def pop(self, draft_id: str) -> Draft | None:
        """Take a draft out. Approving and discarding both resolve it."""
        return self._items.pop(draft_id, None)

    def list(self) -> list[Draft]:
        """Newest first - the one just generated is the one being read."""
        return list(reversed(self._items.values()))

    def clear(self) -> None:
        self._items.clear()


#: The process-wide store. One per server, like the rest of the application's
#: state; tests use `drafts.clear()` rather than building their own.
drafts = DraftStore()
