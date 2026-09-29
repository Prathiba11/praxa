"""Normalisation: HTML, language, profile classification.

All three run on every posting of every sync, so all three are cheap, pure
functions - and cheap pure functions are exactly what unit tests are for.
"""

from __future__ import annotations

import pytest

from career_copilot.core.types import Profile
from career_copilot.jobs.base import classify_profile, detect_language, html_to_text

# ------------------------------------------------------------------ html


def test_tags_are_stripped():
    assert html_to_text("<p>Hello <b>world</b></p>") == "Hello world"


def test_paragraph_breaks_survive():
    text = html_to_text("<p>First paragraph</p><p>Second paragraph</p>")
    assert "First paragraph" in text
    assert "Second paragraph" in text
    assert "\n" in text


def test_list_items_are_separated():
    text = html_to_text("<ul><li>Kubernetes</li><li>Terraform</li></ul>")
    assert "Kubernetes" in text
    assert "Terraform" in text
    assert "KubernetesTerraform" not in text


def test_scripts_and_styles_are_dropped():
    text = html_to_text("<p>Real text</p><script>alert('x')</script><style>p{color:red}</style>")
    assert "Real text" in text
    assert "alert" not in text
    assert "color" not in text


def test_entities_are_decoded():
    assert "R&D" in html_to_text("<p>R&amp;D team</p>")


def test_runs_of_blank_lines_are_collapsed():
    assert "\n\n\n" not in html_to_text("<p>a</p><br><br><br><p>b</p>")


def test_empty_input_is_empty_output():
    assert html_to_text("") == ""


def test_plain_text_passes_through():
    assert html_to_text("no markup here") == "no markup here"


# ------------------------------------------------------------------ language


def test_german_posting_is_detected():
    text = (
        "Wir suchen eine Entwicklerin für unser Team in Stuttgart. Du arbeitest mit "
        "modernen Technologien und bringst Erfahrung mit. Deine Aufgaben sind "
        "vielfältig und du hast die Möglichkeit, dich weiterzuentwickeln. Wir bieten "
        "flexible Arbeitszeiten und ein gutes Gehalt."
    )
    assert detect_language(text) == "de"


def test_english_posting_is_detected():
    text = (
        "We are looking for a platform engineer to join our team in Stuttgart. You "
        "will work with modern infrastructure tooling and have the opportunity to "
        "grow. We offer flexible hours and a competitive salary package for the role."
    )
    assert detect_language(text) == "en"


def test_short_text_defaults_to_english_rather_than_guessing():
    assert detect_language("Kubernetes") == "en"


def test_german_technical_words_in_english_prose_do_not_flip_it():
    """Content words are not evidence; function words are. An English posting
    from a German company mentions Entwicklung without being German."""
    text = (
        "You will join the Entwicklung department and work on Steuergerät software "
        "for a major automotive supplier. We are looking for someone with strong "
        "embedded experience and an interest in security engineering practices here."
    )
    assert detect_language(text) == "en"


# ------------------------------------------------------------------ profile


def test_devops_posting_is_classified():
    assert (
        classify_profile(
            "Platform Engineer",
            "You will run Kubernetes clusters, write Terraform, and maintain GitLab CI.",
        )
        == Profile.DEVOPS
    )


def test_automotive_posting_is_classified():
    assert (
        classify_profile(
            "Automotive Security Engineer",
            "TARA per ISO/SAE 21434, UNECE R155 compliance and ECU penetration testing.",
        )
        == Profile.AUTOMOTIVE_CYBER
    )


def test_ai_posting_is_classified():
    assert (
        classify_profile(
            "Machine Learning Engineer",
            "Build RAG pipelines with LangChain, embeddings and a vector database.",
        )
        == Profile.AI_ENG
    )


def test_title_terms_weigh_more_than_body_terms():
    """One mention of Kubernetes in a perks list should not outvote the title."""
    assert (
        classify_profile(
            "Machine Learning Engineer",
            "Our platform happens to run on Kubernetes. You will build LLM features, "
            "work on RAG retrieval and fine-tuning, and own the MLOps pipeline.",
        )
        == Profile.AI_ENG
    )


def test_a_vague_posting_is_left_unclassified():
    """None is a real answer. A wrong profile becomes a retrieval filter and
    hides the job from the search that would have found it."""
    assert (
        classify_profile("Software Engineer", "You will write code and work in an agile team.")
        is None
    )


def test_an_evenly_split_posting_is_left_unclassified():
    assert (
        classify_profile(
            "Engineer",
            "Kubernetes, Terraform, GitOps alongside machine learning, LLM and RAG work.",
        )
        is None
    )


def test_a_single_keyword_is_not_enough():
    assert classify_profile("Engineer", "Some Docker experience would be nice.") is None


def test_agency_boilerplate_does_not_make_a_designer_an_engineer():
    """From a live run: a Senior Graphic Designer was labelled ai_eng because
    the agency's description listed every technology it had ever touched.
    Boilerplate scores every profile, so the margin rule rejects it."""
    boilerplate = (
        "We are a talent marketplace. Our clients work with Kubernetes, Docker, "
        "Terraform, machine learning, PyTorch, LLM tooling, embedding search and "
        "automotive systems. Apply to join our network of vetted professionals."
    )
    assert classify_profile("Senior Graphic Designer", boilerplate) is None


def test_a_body_only_match_needs_to_be_strong():
    """No title evidence means the posting never says what it is. One or two
    passing mentions are not enough to file it under a CV."""
    weak = "The team uses Kubernetes and Terraform somewhere in the stack."
    assert classify_profile("Product Manager", weak) is None


def test_a_body_only_match_is_accepted_when_overwhelming():
    strong = (
        "You will operate Kubernetes clusters, write Terraform and Helm charts, "
        "run GitLab CI pipelines, manage ArgoCD GitOps deployments, and own "
        "Prometheus and Grafana observability for the platform."
    )
    assert classify_profile("Infrastructure Specialist", strong) == Profile.DEVOPS


def test_the_title_alone_can_carry_a_thin_description():
    assert (
        classify_profile("Site Reliability Engineer (SRE)", "Join our growing team.")
        == Profile.DEVOPS
    )


#: Every profile the classifier is allowed to assign. `Profile.GENERAL` is the
#: catch-all for a CV the specialised tracks do not cover, and it is excluded
#: here on purpose - see the two tests below, which pin both halves of that.
CLASSIFIABLE = tuple(p for p in Profile if p is not Profile.GENERAL)


@pytest.mark.parametrize("profile", CLASSIFIABLE)
def test_every_classifiable_profile_is_reachable(profile):
    """A profile with vocabulary but no way to win would silently never be assigned."""
    from career_copilot.jobs.base import _PROFILE_TERMS

    assert _PROFILE_TERMS[profile]


def test_general_has_no_vocabulary_and_that_is_deliberate():
    """The catch-all must not be reachable by keyword.

    This test used to be `every profile is reachable`, and it failed the moment
    `Profile.GENERAL` was added - correctly, because at that point the rule had
    changed and nothing said so. The rule now: a track a posting can be *assigned
    to* needs vocabulary; the track that exists for CVs the others do not cover
    must not have any.

    If it did, it would win exactly the postings the margin rule was built to
    reject - the ones whose boilerplate mentions a little of everything. Those
    must stay unassigned, because a wrongly labelled job is worse than an
    unlabelled one: the profile becomes a retrieval filter and hides the job
    from the search that would have found it.
    """
    from career_copilot.jobs.base import _PROFILE_TERMS

    assert Profile.GENERAL not in _PROFILE_TERMS


def test_a_posting_the_classifier_cannot_place_stays_unassigned():
    """Not swept into the catch-all."""
    assert classify_profile("Senior Graphic Designer", "Branding, layout, print.") is None
