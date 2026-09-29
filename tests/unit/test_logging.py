import io
import json
import logging
from collections.abc import Callable

from career_copilot.core.logging import JsonFormatter, PiiRedactionFilter


def _capture(emit: Callable[[logging.Logger], None]) -> str:
    """Log through an isolated logger and return the raw formatted output."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(PiiRedactionFilter())

    logger = logging.getLogger("career_copilot.test.isolated")
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False  # keep it out of the root logger and pytest's capture

    emit(logger)
    handler.flush()
    return stream.getvalue()


def test_output_is_valid_json():
    payload = json.loads(_capture(lambda log: log.info("hello")))
    assert payload["level"] == "INFO"
    assert payload["message"] == "hello"
    assert "ts" in payload


def test_extra_fields_become_top_level_keys():
    out = _capture(lambda log: log.error("failed", extra={"cid": "abc12345"}))
    assert json.loads(out)["cid"] == "abc12345"


def test_email_is_redacted_from_logs():
    out = _capture(lambda log: log.info("contact me at prathiba@example.com"))
    assert "prathiba@example.com" not in out
    assert "[EMAIL]" in json.loads(out)["message"]


def test_pii_in_format_args_is_also_redacted():
    """Masking must happen AFTER %s interpolation, or arguments slip through."""
    out = _capture(lambda log: log.info("user said: %s", "call me on +49 170 1234567"))
    assert "1234567" not in out


def test_exception_info_is_included():
    def emit(log: logging.Logger) -> None:
        try:
            raise ValueError("boom")
        except ValueError:
            log.exception("something broke")

    payload = json.loads(_capture(emit))
    assert "ValueError" in payload["exception"]
