import pytest

from career_copilot.core.errors import SecurityError, ValidationError
from career_copilot.core.security import mask_pii, validate_url, validate_user_input

# ---------------------------------------------------------------- masking

MUST_MASK = [
    ("linkedin.com/in/prathiba", "linkedin"),  # no scheme - an earlier review finding
    ("https://www.linkedin.com/in/prathiba-p-123", "linkedin"),
    ("prathiba@example.com", "email"),
    ("+49 170 1234567", "phone_de"),
    ("0170 1234567", "phone_de"),
    ("Hauptstraße 12", "street_de"),
    ("Bahnhofstr. 7a", "street_de"),
    ("123 Main Street", "street_en"),
    ("10115 Berlin", "plz_city"),
    ("DE89370400440532013000", "iban"),
    ("15.03.1990", "dob"),
]


@pytest.mark.parametrize(("text", "category"), MUST_MASK)
def test_pii_is_masked(text: str, category: str):
    result = mask_pii(text)
    assert category in result.found, f"{text!r} was not detected as {category}"
    assert text not in result.text, f"{text!r} survived masking"


MUST_NOT_MASK = [
    "Python 3.11",
    "ISO 21434",
    "24/7 monitoring",
    "Robert Bosch GmbH",
    "Kubernetes v1.29",
]


@pytest.mark.parametrize("text", MUST_NOT_MASK)
def test_ordinary_text_is_untouched(text: str):
    result = mask_pii(text)
    assert result.text == text, f"{text!r} was masked as {result.found}"
    assert result.found == {}


def test_names_are_deliberately_not_masked():
    """Documented limitation: regex cannot detect names. NER is a later phase."""
    result = mask_pii("My name is Prathiba Prabhakaran")
    assert "Prathiba" in result.text


def test_counts_are_reported():
    result = mask_pii("a@b.com and c@d.com")
    assert result.found["email"] == 2


def test_empty_input_rejected():
    with pytest.raises(ValidationError):
        validate_user_input("   ")


# ---------------------------------------------------------------- validation


def test_input_over_limit_rejected():
    with pytest.raises(ValidationError):
        validate_user_input("x" * 100, max_chars=50)


def test_valid_input_is_stripped():
    assert validate_user_input("  hello  ") == "hello"


BAD_URLS = [
    "http://example.com",  # not https
    "https://localhost/jobs",
    "https://127.0.0.1/jobs",
    "https://192.168.1.10/jobs",
    "file:///etc/passwd",
    "https://",  # no hostname
]


@pytest.mark.parametrize("url", BAD_URLS)
def test_bad_urls_rejected(url: str):
    with pytest.raises(SecurityError):
        validate_url(url)


def test_good_url_accepted():
    url = "https://www.linkedin.com/jobs/view/123456"
    assert validate_url(url) == url
