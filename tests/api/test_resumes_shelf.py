"""The General shelf: many CVs under one profile, and one of them in use.

The three tracked profiles are slots - one CV each, and an upload replaces it.
General is different, because it exists for careers the tracked profiles do not
cover and there is no single document that represents "everything else". So it
holds several, each named after its own first heading.

That difference creates exactly one question the system has to answer without
asking: *which* General CV does a tailoring read? The rule is the most recently
updated, and these tests pin it, because a tool that silently picks one of the
user's documents is the kind of thing nobody notices until it has written the
wrong CV.
"""

from __future__ import annotations

import pytest

from career_copilot.storage.db import init_db


@pytest.fixture(autouse=True)
def _fast_embedder(fake_embedder):
    """Every test here uploads, and every upload indexes.

    `fake_embedder` is opt-in rather than autouse, and without it these tests
    load the real 1 GB transformer - roughly 150 seconds for the first one, which
    reads as a hang rather than a slow test. A deterministic hashing embedder
    runs the same code path in milliseconds, and nothing here is testing
    embedding quality: what is under test is which files land where and which
    row is marked in use.
    """
    return fake_embedder


def _dir(api_settings):
    from career_copilot.api.routes.resumes import _general_dir

    init_db()
    return _general_dir()


def _cv(name: str, note: str = "") -> str:
    """A document long enough to be accepted.

    `ResumeUpload.content` has a 200-character floor, which is a real guard: a
    forty-character file is a mis-click, not a CV. The tests have to send
    something plausible rather than work around the rule.
    """
    body = (
        f"# {name}\n\n"
        "Stuttgart, Germany\n\n"
        "## Summary\n\n"
        f"{note}Engineer with nine years of experience across test automation, "
        "measurement systems and supplier quality. Comfortable owning a "
        "specification end to end and unpicking why a result that held in the "
        "lab does not hold on the line.\n\n"
        "## Skills\n\n"
        "Test specification, Python, statistical process control, root-cause "
        "analysis, audit preparation.\n"
    )
    assert len(body) >= 200
    return body


def _upload(client, content: str, profile: str = "general"):
    """Upload, and fail here rather than three assertions later.

    A helper that returns a 500 silently turns every test downstream of it into
    "the list was empty", which says nothing about why.
    """
    response = client.post(
        "/api/resumes",
        json={"profile": profile, "filename": "cv.md", "content": content},
    )
    assert response.status_code == 201, f"upload failed: {response.status_code} {response.text}"
    return response


# ------------------------------------------------------------------ listing


def test_tracked_profiles_are_listed_even_with_no_cv(client, api_settings):
    body = client.get("/api/resumes").json()

    tracked = [row for row in body if row["profile"] != "general"]
    assert {row["profile"] for row in tracked} == {"automotive_cyber", "devops", "ai_eng"}
    assert all(row["isYours"] is False for row in tracked)
    # An empty shelf contributes no rows at all - there is nothing to stand in
    # for, because General has no single identity to be missing.
    assert [row for row in body if row["profile"] == "general"] == []


def test_a_row_is_named_after_the_documents_first_heading(client, api_settings):
    _upload(client, _cv("Ines Faller"))

    shelf = [row for row in client.get("/api/resumes").json() if row["profile"] == "general"]

    assert len(shelf) == 1
    assert shelf[0]["label"] == "Ines Faller"


def test_a_document_with_no_heading_falls_back_to_its_file_name(client, api_settings):
    _upload(client, _cv("x").split("\n", 1)[1].lstrip())

    shelf = [row for row in client.get("/api/resumes").json() if row["profile"] == "general"]

    assert len(shelf) == 1
    assert shelf[0]["label"]


# -------------------------------------------------------------- the shelf


def test_uploading_twice_adds_rather_than_replaces(client, api_settings):
    """The whole point of the shelf. A tracked profile would have overwritten."""
    _upload(client, _cv("Ines Faller"))
    _upload(client, _cv("Marek Duvall"))

    shelf = [row for row in client.get("/api/resumes").json() if row["profile"] == "general"]

    assert {row["label"] for row in shelf} == {"Ines Faller", "Marek Duvall"}


def test_the_same_document_twice_overwrites_instead_of_accumulating(client, api_settings):
    """File names come from the heading, so a re-upload lands on the same file.

    Without this, uploading a corrected CV would leave the old one on the shelf
    beside it, and `load_resume` would have two near-identical documents to pick
    between on modification time alone.
    """
    _upload(client, _cv("Ines Faller", "First version. "))
    _upload(client, _cv("Ines Faller", "Second version. "))

    shelf = [row for row in client.get("/api/resumes").json() if row["profile"] == "general"]

    assert len(shelf) == 1
    assert "Second version." in (_dir(api_settings) / f"{shelf[0]['id']}.md").read_text("utf-8")


def test_exactly_one_row_is_marked_in_use(client, api_settings):
    _upload(client, _cv("Ines Faller"))
    _upload(client, _cv("Marek Duvall"))

    shelf = [row for row in client.get("/api/resumes").json() if row["profile"] == "general"]

    assert sum(1 for row in shelf if row["inUse"]) == 1


# ------------------------------------------------------------------ delete


def test_one_cv_can_be_removed_without_touching_the_others(client, api_settings):
    _upload(client, _cv("Ines Faller"))
    _upload(client, _cv("Marek Duvall"))
    shelf = [row for row in client.get("/api/resumes").json() if row["profile"] == "general"]
    victim = next(row for row in shelf if row["label"] == "Ines Faller")

    assert client.delete(f"/api/resumes/general/{victim['id']}").status_code == 200

    left = [row for row in client.get("/api/resumes").json() if row["profile"] == "general"]
    assert [row["label"] for row in left] == ["Marek Duvall"]


def test_a_path_traversal_id_cannot_delete_a_tracked_cv(client, api_settings):
    """`..%2Fdevops` must not escape the shelf.

    The id is a path segment arriving from the network. Rebuilding the path and
    comparing its parent is the check; without it, a delete on the General shelf
    could remove the DevOps CV.
    """
    _upload(client, _cv("Marek Duvall"), profile="devops")

    response = client.delete("/api/resumes/general/..%2Fdevops")

    assert response.status_code == 404
    assert any(
        row["profile"] == "devops" and row["isYours"] for row in client.get("/api/resumes").json()
    )


def test_removing_an_unknown_id_is_a_404_not_a_crash(client, api_settings):
    assert client.delete("/api/resumes/general/nothing-here").status_code == 404


# ------------------------------------------------- one document, not all
#
# Uploading a CV used to rebuild the whole index: every document re-chunked and
# re-embedded to save one file. With a real embedder that is minutes of work per
# upload, which is what made the page feel broken. It now replaces one
# document's chunks and leaves the rest alone, and this is the test that would
# fail if it went back.


def test_a_second_upload_leaves_the_first_ones_passages_in_place(client, api_settings):
    """A rebuild would discard and recreate everything; a replace does not."""
    from career_copilot.rag.store import VectorStore

    _upload(client, _cv("Ines Faller"))
    after_first = VectorStore().count()
    assert after_first > 0

    _upload(client, _cv("Marek Duvall"))

    # Strictly more: the first CV's passages survived the second upload.
    assert VectorStore().count() > after_first


def test_removing_one_cv_leaves_the_others_indexed(client, api_settings):
    _upload(client, _cv("Ines Faller"))
    _upload(client, _cv("Marek Duvall"))
    from career_copilot.rag.store import VectorStore

    before = VectorStore().count()
    shelf = [row for row in client.get("/api/resumes").json() if row["profile"] == "general"]
    victim = next(row for row in shelf if row["label"] == "Ines Faller")

    client.delete(f"/api/resumes/general/{victim['id']}")

    after = VectorStore().count()
    assert 0 < after < before
