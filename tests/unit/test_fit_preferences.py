"""What the candidate said they want, reaching the fit scorer - and stopping there.

Memory used to touch one thing: the agent's system prompt. So a preference like
"will not take roles with on-call" changed how the assistant *talked* about a
job and had no effect on the number printed on it, which is the sort of
inconsistency a reader notices before the author does.

It now reaches fit scoring too, under one rule that these tests exist to hold:
**preferences never move `score`.** That number is stored on the job row and
compared between jobs. Folding a refusal into it would mean two postings with
the same score no longer mean the same thing, and every score already in the
database would silently change meaning. A contradicted preference lands in
`conflicts` instead.

The other property worth pinning is the empty case. With nothing remembered,
the prompt must be exactly what it was before this feature existed - a model
asked to find conflicts against a list it was never given is a model invited to
invent one.

No model is called here. What is under test is what reaches the prompt and what
survives the parse.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from career_copilot.core.errors import ConfigError
from career_copilot.core.types import Profile
from career_copilot.memory import recall
from career_copilot.storage import db as db_module
from career_copilot.storage import jobs as repo
from career_copilot.tools import _shared as shared
from career_copilot.tools import fit

_SCORED = {
    "score": 0.88,
    "matched": ["Kubernetes - operated clusters at Bosch"],
    "missing": [],
    "blockers": [],
    "conflicts": ["will not take roles with on-call - posting requires a weekly on-call rota"],
    "verdict": "Strong on evidence, but it carries on-call, which you have ruled out.",
}


class _FakeSettings:
    def __init__(self, db_path):
        self.db_path = db_path


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    db_module.reset_engine()
    monkeypatch.setattr(db_module, "get_settings", lambda: _FakeSettings(tmp_path / "t.db"))
    db_module.init_db()
    yield
    db_module.reset_engine()


@pytest.fixture()
def fake_repo(tmp_path, monkeypatch):
    resumes = tmp_path / "data" / "kb" / "resumes"
    resumes.mkdir(parents=True)
    (resumes / "devops.md").write_text("# CV\n\n## Experience\n- Kubernetes at Bosch\n", "utf-8")
    monkeypatch.setattr(shared, "repo_root", lambda: tmp_path)
    return tmp_path


@pytest.fixture()
def sent(monkeypatch):
    """Capture the messages the tool would have sent to the model."""
    captured: dict[str, object] = {}

    def _chat(messages, **_kwargs):
        captured["system"] = messages[0]["content"]
        captured["user"] = messages[1]["content"]
        return SimpleNamespace(content=json.dumps(_SCORED))

    monkeypatch.setattr(fit, "chat", _chat)
    return captured


def _job():
    return repo.upsert_job(
        source="test",
        title="Platform Engineer",
        company="Bosch",
        location="Stuttgart",
        description="Kubernetes, Terraform, and a weekly on-call rota.",
        profile=Profile.DEVOPS,
    )


def _remember(monkeypatch, *lines: str) -> None:
    monkeypatch.setattr(fit, "preference_lines", lambda: list(lines))


# --------------------------------------------------------- the empty case


def test_with_nothing_remembered_the_prompt_is_what_it_always_was(
    temp_db, fake_repo, sent, monkeypatch
):
    _remember(monkeypatch)

    fit.score_job_fit.run({"profile": "devops", "job_id": _job().id})

    assert sent["system"] == fit.SYSTEM_PROMPT
    assert "STANDING PREFERENCES" not in str(sent["user"])


def test_conflicts_are_discarded_when_no_preferences_were_supplied(
    temp_db, fake_repo, sent, monkeypatch
):
    """The stub returns conflicts regardless. Without preferences they are not ours.

    A model that volunteers "will not take roles with on-call" when it was never
    told that would be putting words in the candidate's mouth, and those words
    would then be rendered back to them as their own.

    What is asserted is the `conflicts` list, not the absence of the words. The
    verdict is free prose that the model has always been allowed to write about
    whatever it read in the posting, and the posting here does mention on-call -
    so a blunt "on-call not in output" would fail on text that is working
    correctly. The conflict entry's own wording is the discriminator: nothing
    but `conflicts` puts "weekly on-call rota" into the rendered report.
    """
    _remember(monkeypatch)

    output = fit.score_job_fit.run({"profile": "devops", "job_id": _job().id})

    assert "Against what you said you want" not in output
    assert "weekly on-call rota" not in output


# ------------------------------------------------------ preferences present


def test_preferences_reach_the_prompt_labelled_as_the_candidates_own_words(
    temp_db, fake_repo, sent, monkeypatch
):
    """Delimited like the posting, but not marked untrusted - the posting came
    from the internet, these came from the user."""
    _remember(monkeypatch, "[deal_breaker] will not take roles with on-call")

    fit.score_job_fit.run({"profile": "devops", "job_id": _job().id})

    user = str(sent["user"])
    assert "<<<BEGIN STANDING PREFERENCES - the candidate's own words>>>" in user
    assert "will not take roles with on-call" in user
    assert "conflicts" in str(sent["system"])


def test_a_contradicted_preference_is_reported(temp_db, fake_repo, sent, monkeypatch):
    _remember(monkeypatch, "[deal_breaker] will not take roles with on-call")

    output = fit.score_job_fit.run({"profile": "devops", "job_id": _job().id})

    assert "Against what you said you want" in output
    assert "weekly on-call rota" in output


def test_a_conflict_does_not_move_the_stored_score(temp_db, fake_repo, sent, monkeypatch):
    """The whole point. A job the candidate would refuse can still be a 0.88.

    `fit_score` answers "does the resume evidence what this posting asks for?"
    and is ranked on across jobs. If a refusal dragged it down, two jobs showing
    the same number would no longer mean the same thing, and every score already
    written would change meaning without being recomputed.
    """
    job = _job()
    _remember(monkeypatch, "[deal_breaker] will not take roles with on-call")

    fit.score_job_fit.run({"profile": "devops", "job_id": job.id})

    stored = repo.get_job(job.id)
    assert stored is not None
    assert stored.fit_score == pytest.approx(0.88)


# ------------------------------------------------------------- failing open
#
# Tested where the handling actually lives. `preference_lines` swallows a
# storage failure and returns nothing, so fit scoring never sees one - which is
# why there is no try/except in `fit._run` to test. Asserting the behaviour
# against the real function rather than a stub is the difference between pinning
# the contract and pinning my own mock of it.


def test_unreadable_memory_yields_no_preferences_rather_than_an_error(monkeypatch):
    """A storage failure degrades to the behaviour from before memory existed."""

    def _boom(*_args, **_kwargs):
        raise ConfigError("memory store unavailable")

    monkeypatch.setattr(recall, "get_settings", lambda: SimpleNamespace(memory_enabled=True))
    monkeypatch.setattr(recall.store, "list_facts", _boom)

    assert recall.preference_lines() == []


def test_memory_switched_off_yields_no_preferences(monkeypatch):
    monkeypatch.setattr(recall, "get_settings", lambda: SimpleNamespace(memory_enabled=False))
    monkeypatch.setattr(
        recall.store,
        "list_facts",
        lambda *_a, **_k: pytest.fail("the store must not be read when memory is off"),
    )

    assert recall.preference_lines() == []


def test_scoring_runs_normally_when_memory_yields_nothing(temp_db, fake_repo, sent, monkeypatch):
    """The end of that chain: no preferences, and the tool is unaffected."""
    monkeypatch.setattr(recall, "get_settings", lambda: SimpleNamespace(memory_enabled=False))

    output = fit.score_job_fit.run({"profile": "devops", "job_id": _job().id})

    assert "0.88" in output
    assert sent["system"] == fit.SYSTEM_PROMPT
