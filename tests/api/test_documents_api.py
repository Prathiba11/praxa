"""The approval gate: what exists on disk, and when.

One property holds this router together and every test below is an angle on it:
**generating a document must not create a file, and only a human decision may.**

That is worth testing rather than trusting, because the failure is silent and
expensive. A gate that generates and writes in the same call still *looks* like
a gate - a draft appears, Approve and Discard are there, the panel behaves - and
a user who clicks Discard would believe nothing was written while a tailored CV
with their name on it sat in the output directory. So the assertions here are
mostly about the output directory being empty, which is the only evidence that
distinguishes a real gate from a convincing one.

The model is stubbed throughout. What is under test is the decision procedure,
not the quality of a CV.
"""

from __future__ import annotations

import pytest

from career_copilot.agent.reviewer import DocumentReview
from career_copilot.documents.drafts import DraftStore, drafts
from career_copilot.tools import _shared

_CV_BODY = """# Jane Engineer — Platform Engineer

Ran Kubernetes across three regions.

## Gaps against this posting
- No Terraform on the CV. The posting asks for it.
"""

_POSTING = "Platform engineer, Stuttgart. Kubernetes, CI/CD, on-call rotation."


@pytest.fixture(autouse=True)
def _no_leftover_drafts():
    """Each test starts with an empty gate and leaves one behind."""
    drafts.clear()
    yield
    drafts.clear()


@pytest.fixture()
def stub_model(monkeypatch):
    """A generated document, without a model call.

    Patched at `_generate` rather than at `chat`, so the prompt assembly above
    it still runs - that is where the posting gets delimited, and a stub placed
    higher would skip it.
    """
    from career_copilot.tools import documents as documents_module

    calls: list[str] = []

    def _fake(system_prompt: str, resume: str, job, *, extra: str = "") -> str:
        calls.append(system_prompt)
        return _CV_BODY

    monkeypatch.setattr(documents_module, "_generate", _fake)

    # The reviewing agent is a second model call. Stubbed by default so the
    # tests about the gate are about the gate; the review tests below replace
    # this with whatever verdict they are checking.
    from career_copilot.api.routes import documents as route_module

    monkeypatch.setattr(
        route_module,
        "review_document",
        lambda **_kwargs: DocumentReview(
            verdict="ok", invented=[], notes="Everything traces to the CV."
        ),
    )
    return calls


@pytest.fixture()
def output_dir(api_settings, tmp_path, monkeypatch):
    """A throwaway repository root, so no test writes into the real one.

    `output_dir()` resolves against `repo_root()` rather than `CC_DATA_DIR`,
    because the document tools are called from pytest, from scripts and from a
    Streamlit process that each run in a different working directory. That is a
    deliberate choice and it is documented where it is made - but it does mean
    setting `CC_DATA_DIR` is not enough to isolate a test that writes a file.

    The first version of this fixture missed that, and the approval test wrote a
    real CV into `data/output/` in the repository. Harmless - the directory is
    gitignored - but it is exactly the kind of test that passes while quietly
    touching something it should not. Patching `repo_root` is how the existing
    document tests isolate; this now does the same.
    """
    resumes = tmp_path / "data" / "kb" / "resumes"
    resumes.mkdir(parents=True)
    (resumes / "devops.md").write_text("# CV\n\n## Experience\n- Kubernetes at Bosch\n", "utf-8")
    monkeypatch.setattr(_shared, "repo_root", lambda: tmp_path)
    return _shared.output_dir()


def _draft(client, **overrides):
    payload = {"profile": "devops", "kind": "cv", "jobText": _POSTING}
    payload.update(overrides)
    return client.post("/api/documents/draft", json=payload)


# ------------------------------------------------------- generating a draft


def test_a_draft_is_generated_and_nothing_is_written(client, api_settings, stub_model, output_dir):
    """The whole point of the gate, stated as one assertion about the disk."""
    response = _draft(client)

    assert response.status_code == 201
    assert response.json()["body"].startswith("# Jane Engineer")
    assert list(output_dir.glob("*")) == []


def test_the_draft_carries_what_a_person_needs_to_decide(
    client, api_settings, stub_model, output_dir
):
    body = _draft(client).json()

    assert set(body) == {
        "draftId",
        "kind",
        "profile",
        "language",
        "jobLabel",
        "jobId",
        "body",
        "gaps",
        "review",
        "createdAt",
    }
    assert body["kind"] == "cv"
    assert body["profile"] == "devops"


def test_the_gaps_section_is_pulled_out_of_the_document(
    client, api_settings, stub_model, output_dir
):
    """The section that decides approval, lifted out of the bottom of the page.

    A reviewer who has to scroll a two-page CV to find what it cannot support
    will approve without reading it, which makes the gate decorative.
    """
    body = _draft(client).json()

    assert "Terraform" in body["gaps"]
    assert body["gaps"].startswith("- No Terraform")


def test_a_letter_asks_for_a_letter(client, api_settings, stub_model, output_dir):
    _draft(client, kind="letter", language="de")

    assert any("cover letter" in prompt.lower() for prompt in stub_model)


def test_a_missing_job_is_refused_before_the_model_is_called(
    client, api_settings, stub_model, output_dir
):
    response = client.post("/api/documents/draft", json={"profile": "devops", "kind": "cv"})

    assert response.status_code == 400
    assert stub_model == []


def test_an_empty_document_is_not_offered_for_approval(
    client, api_settings, monkeypatch, output_dir
):
    """An empty draft in the list is a trap: Approve would write an empty CV."""
    from career_copilot.tools import documents as documents_module

    monkeypatch.setattr(documents_module, "_generate", lambda *a, **k: "   ")

    response = _draft(client)

    assert response.status_code == 502
    assert client.get("/api/documents/drafts").json() == []


# ------------------------------------------------------------------ approving


def test_approving_is_the_only_thing_that_writes(client, api_settings, stub_model, output_dir):
    draft_id = _draft(client).json()["draftId"]
    assert list(output_dir.glob("*")) == []

    response = client.post(f"/api/documents/{draft_id}/approve")

    assert response.status_code == 200
    written = {path.name for path in output_dir.glob("*")}
    assert set(response.json()["files"]) == written
    assert any(name.endswith(".md") for name in written)
    assert any(name.endswith(".docx") for name in written)


def test_an_approved_draft_cannot_be_approved_twice(client, api_settings, stub_model, output_dir):
    """Resolving a draft consumes it, so a double-click writes one pair of files."""
    draft_id = _draft(client).json()["draftId"]
    client.post(f"/api/documents/{draft_id}/approve")

    again = client.post(f"/api/documents/{draft_id}/approve")

    assert again.status_code == 404


def test_approving_something_that_was_never_drafted_is_a_404(client, api_settings):
    assert client.post("/api/documents/nosuchdraft/approve").status_code == 404


def test_a_failed_write_does_not_destroy_the_draft(client, api_settings, stub_model, output_dir):
    """Regression: approving popped the draft before writing it.

    A write that failed - a full disk, a permission error, a path the OS
    refused - took the draft with it. The user had approved a document, been
    shown an error, and found the thing they approved gone, with another model
    call the only way back. Approval must be retryable.
    """
    from career_copilot.api.routes import documents as route

    draft_id = _draft(client).json()["draftId"]

    def explode(*args, **kwargs):
        raise OSError("No space left on device")

    # A context of its own, NOT the `monkeypatch` fixture. That fixture is
    # function-scoped and shared: `api_settings` and `output_dir` hold the very
    # same instance, so calling `monkeypatch.undo()` here to lift the fault
    # would also lift their isolation - and the retry below then wrote a real
    # file into the repository's own data/output/. Which is precisely what the
    # `output_dir` docstring warns about, three fixtures up.
    with pytest.MonkeyPatch.context() as faulty_disk:
        faulty_disk.setattr(route, "persist_cv", explode)
        faulty_disk.setattr(route, "persist_letter", explode)

        with pytest.raises(OSError, match="No space left"):
            client.post(f"/api/documents/{draft_id}/approve")

        # Still there, and still approvable once the disk problem is fixed.
        listed = client.get("/api/documents/drafts").json()
        assert any(item["draftId"] == draft_id for item in listed)

    retried = client.post(f"/api/documents/{draft_id}/approve")
    assert retried.status_code == 200
    assert list(output_dir.glob("*")), "the retry must write into the throwaway directory"


# ----------------------------------------------------------------- discarding


def test_discarding_leaves_no_file_behind(client, api_settings, stub_model, output_dir):
    draft_id = _draft(client).json()["draftId"]

    response = client.delete(f"/api/documents/{draft_id}")

    assert response.status_code == 204
    assert list(output_dir.glob("*")) == []
    assert client.get("/api/documents/drafts").json() == []


def test_discarding_twice_is_a_404(client, api_settings, stub_model, output_dir):
    draft_id = _draft(client).json()["draftId"]
    client.delete(f"/api/documents/{draft_id}")

    assert client.delete(f"/api/documents/{draft_id}").status_code == 404


# -------------------------------------------------------------- pending list


def test_pending_drafts_are_listed_newest_first(client, api_settings, stub_model, output_dir):
    first = _draft(client).json()["draftId"]
    second = _draft(client, kind="letter").json()["draftId"]

    listed = [item["draftId"] for item in client.get("/api/documents/drafts").json()]

    assert listed == [second, first]


# ------------------------------------------------------------------ the store


def test_the_store_drops_the_oldest_rather_than_growing_forever():
    """An unbounded store of generated CVs is a memory leak holding personal data."""
    store = DraftStore(limit=2)
    kept = [
        store.put(
            kind="cv",
            profile="devops",
            language="en",
            job_label=f"job {index}",
            job_id=None,
            job_slug=f"slug{index}",
            body="body",
        )
        for index in range(3)
    ]

    assert store.get(kept[0].draft_id) is None
    assert store.get(kept[1].draft_id) is not None
    assert store.get(kept[2].draft_id) is not None


def test_a_document_with_no_gaps_section_reports_no_gaps():
    store = DraftStore()
    draft = store.put(
        kind="letter",
        profile="devops",
        language="en",
        job_label="job",
        job_id=None,
        job_slug="slug",
        body="A letter with nothing missing.",
    )

    assert draft.gaps == ""


# ------------------------------------------------------------- the reviewer


def _review(monkeypatch, review):
    from career_copilot.api.routes import documents as route_module

    monkeypatch.setattr(route_module, "review_document", lambda **_kwargs: review)


def test_the_draft_carries_the_second_agents_verdict(client, api_settings, stub_model, output_dir):
    body = _draft(client).json()

    assert body["review"] == {
        "verdict": "ok",
        "invented": [],
        "notes": "Everything traces to the CV.",
    }


def test_an_unsupported_claim_reaches_the_person_deciding(
    client, api_settings, stub_model, output_dir, monkeypatch
):
    """The reviewer's whole purpose: say what the CV does not support, in words."""
    _review(
        monkeypatch,
        DocumentReview(
            verdict="concerns",
            invented=["Five years of Terraform"],
            notes="The CV does not mention Terraform.",
        ),
    )

    body = _draft(client).json()

    assert body["review"]["verdict"] == "concerns"
    assert body["review"]["invented"] == ["Five years of Terraform"]


def test_a_draft_with_concerns_can_still_be_approved(
    client, api_settings, stub_model, output_dir, monkeypatch
):
    """The reviewer advises; the human decides.

    Blocking approval on the reviewer would make it a gate of its own, and a
    second model would then be deciding what the user may send. It reports.
    """
    _review(
        monkeypatch,
        DocumentReview(
            verdict="concerns", invented=["Five years of Terraform"], notes="Check this."
        ),
    )
    draft_id = _draft(client).json()["draftId"]

    assert client.post(f"/api/documents/{draft_id}/approve").status_code == 200


def test_a_review_that_did_not_run_is_not_reported_as_passing(
    client, api_settings, stub_model, output_dir, monkeypatch
):
    """`unavailable` is a third value on purpose.

    Collapsing it into `ok` would let a draft nobody checked look exactly like a
    draft that passed - which is the fail-open mistake this project has already
    made once, with the retrieval grader.
    """
    _review(monkeypatch, DocumentReview(notes="The review could not be run for this draft."))

    assert _draft(client).json()["review"]["verdict"] == "unavailable"


def test_the_reviewer_never_returns_ok_while_listing_inventions():
    """A contradiction is resolved toward the finding, not the label."""
    from career_copilot.agent.reviewer import _parse

    review = _parse('{"verdict": "ok", "invented": ["Five years of Rust"], "notes": "n"}')

    assert review is not None
    assert review.verdict == "concerns"


def test_an_unreadable_review_is_unavailable_rather_than_a_crash():
    from career_copilot.agent.reviewer import _parse

    assert _parse("the model said something conversational") is None
