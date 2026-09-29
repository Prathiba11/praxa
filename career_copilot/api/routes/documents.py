"""Generating a document, and the person who has to agree to it.

Every other control in this application is a restriction the system applies to
itself: the posting is delimited, the mode owns a narrow tool set, generation is
told to invent nothing, the grader judges the evidence. All of them are
automatic, and an automatic control is a system checking its own work.

This router is the one place a human is in the loop on purpose. A tailored CV is
the only thing here that leaves the machine with the candidate's name on it and
goes to a stranger; an agent turn is reversible, a document sent to an employer
is not. So the two halves of `tools.documents` are exposed separately:

    POST /api/documents/draft          generate, write nothing
    POST /api/documents/{id}/approve   write the files
    DELETE /api/documents/{id}         throw it away

Between those calls the draft sits in memory and a person reads it - in
particular the "Gaps against this posting" section, which is the model saying
out loud what the CV cannot support. Approving is a deliberate act, and until it
happens nothing exists on disk.

**The agent's own tools are unchanged.** `tailor_cv` mid-turn still writes
immediately, because a model part-way through a turn has nobody to ask and a
tool that answered "waiting for a human" would leave it holding a promise it
cannot keep. The gate is on the path a person drives, which is the path that
matters: a document the user asked for by clicking a button.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from career_copilot.agent.reviewer import review_document
from career_copilot.api.schemas import ApprovalOut, DraftOut, DraftRequest, ReviewOut
from career_copilot.core.errors import CopilotError
from career_copilot.core.logging import get_logger
from career_copilot.core.session import use_session
from career_copilot.core.types import Profile
from career_copilot.core.usage import new_session_id
from career_copilot.documents.drafts import Draft, drafts
from career_copilot.tools._shared import load_resume
from career_copilot.tools.documents import (
    TailorCvArgs,
    WriteCoverLetterArgs,
    draft_cv,
    draft_letter,
    persist_cv,
    persist_letter,
)

__all__ = ["router"]

log = get_logger(__name__)

router = APIRouter(tags=["documents"], prefix="/documents")


def _out(draft: Draft) -> DraftOut:
    return DraftOut(
        draft_id=draft.draft_id,
        kind=draft.kind,
        profile=draft.profile,
        language=draft.language,
        job_label=draft.job_label,
        job_id=draft.job_id,
        body=draft.body,
        gaps=draft.gaps,
        review=ReviewOut(
            verdict=draft.review_verdict,
            invented=draft.review_invented,
            notes=draft.review_notes,
        ),
        created_at=draft.created_at,
    )


@router.get("/drafts", response_model=list[DraftOut])
def list_drafts() -> list[DraftOut]:
    """Everything generated and not yet accepted or thrown away."""
    return [_out(draft) for draft in drafts.list()]


@router.post("/draft", response_model=DraftOut, status_code=201)
def create_draft(payload: DraftRequest) -> DraftOut:
    """Generate a CV or a cover letter. Nothing reaches the disk here.

    The model call is billed to its own session, like every other call in the
    application - a document is not free, and an unattributed call is the hole
    `core.session` exists to close.
    """
    profile = Profile(payload.profile)
    try:
        with use_session(new_session_id()):
            if payload.kind == "cv":
                body, job = draft_cv(
                    TailorCvArgs(profile=profile, job_id=payload.job_id, job_text=payload.job_text)
                )
            else:
                body, job = draft_letter(
                    WriteCoverLetterArgs(
                        profile=profile,
                        job_id=payload.job_id,
                        job_text=payload.job_text,
                        language=payload.language,
                    )
                )
    except CopilotError as exc:
        # A bad job id, an empty paste, a budget ceiling. The user gets the
        # readable half and the log keeps the correlation id.
        log.warning(
            "draft generation failed",
            extra={
                "kind": payload.kind,
                "detail": exc.detail,
                "correlation_id": exc.correlation_id,
            },
        )
        raise HTTPException(status_code=400, detail=exc.user_message) from exc

    if not body.strip():
        # Nothing to approve, and an empty draft in the list would be a trap:
        # a person clicking Approve on it would write an empty CV.
        raise HTTPException(
            status_code=502, detail="The model returned an empty document. Nothing was saved."
        )

    # The second agent. It reads the finished draft against the CV it was built
    # from and reports what the CV does not support - it cannot change anything,
    # which is why it is a separate agent rather than one more rule in the
    # writer's prompt. Its own session, like every other model call here.
    with use_session(new_session_id()):
        review = review_document(source_cv=load_resume(profile), posting=job.text, draft=body)

    draft = drafts.put(
        kind=payload.kind,
        profile=profile,
        language=payload.language,
        job_label=job.label,
        job_id=job.job_id,
        job_slug=job.slug,
        body=body,
        review_verdict=review.outcome,
        review_invented=review.invented,
        review_notes=review.notes,
    )
    log.info(
        "draft generated, awaiting approval",
        extra={
            "draft_id": draft.draft_id,
            "kind": draft.kind,
            "job_id": draft.job_id,
            "review_verdict": draft.review_verdict,
        },
    )
    return _out(draft)


@router.post("/{draft_id}/approve", response_model=ApprovalOut)
def approve_draft(draft_id: str) -> ApprovalOut:
    """The human decision. This is the only call that writes a document.

    The draft is read, written, and only then taken out of the store. It used
    to be popped first, which meant a write that failed - a full disk, a
    permission error, a path the OS refused - destroyed the draft on its way
    out. The user would have approved a document, received an error, and found
    the thing they approved gone, with another model call the only way back.
    Removing it last makes a failed approval a retryable one.
    """
    draft = drafts.get(draft_id)
    if draft is None:
        raise HTTPException(
            status_code=404, detail="That draft is no longer waiting for a decision."
        )

    if draft.kind == "cv":
        paths = persist_cv(draft.profile, draft.job_slug, draft.job_label, draft.body)
    else:
        paths = persist_letter(
            draft.profile, draft.job_slug, draft.job_label, draft.language, draft.body
        )

    # Written. Now it is resolved.
    drafts.pop(draft_id)

    names = [path.name for path in paths]
    log.info("draft approved and written", extra={"draft_id": draft_id, "files": names})
    return ApprovalOut(
        draft_id=draft_id,
        files=names,
        message=f"Saved to data/output/ as {' and '.join(names)}.",
    )


@router.delete("/{draft_id}", status_code=204)
def discard_draft(draft_id: str) -> None:
    """Rejecting is as much a decision as approving, and leaves no file."""
    if drafts.pop(draft_id) is None:
        raise HTTPException(
            status_code=404, detail="That draft is no longer waiting for a decision."
        )
    log.info("draft discarded", extra={"draft_id": draft_id})
