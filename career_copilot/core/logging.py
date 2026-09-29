"""Structured JSON logging with PII redaction.

Logs are the sneakiest PII leak: you log a user's question while debugging and
forget it contained a phone number. The filter below masks every record before
it is emitted, so nothing sensitive reaches a log file or a hosted trace.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

from career_copilot.core.config import get_settings
from career_copilot.core.security import mask_pii

__all__ = ["JsonFormatter", "PiiRedactionFilter", "configure_logging", "get_logger"]

# Attributes LogRecord always carries; anything else came from extra={...}
_RESERVED = frozenset(vars(logging.makeLogRecord({}))) | {"message", "asctime"}


class PiiRedactionFilter(logging.Filter):
    """Mask PII in the formatted message before anything is written."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = mask_pii(record.getMessage()).text
        record.args = ()  # getMessage() already applied them
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line - greppable, and parseable by log tooling."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging(*, level: str | None = None, as_json: bool | None = None) -> None:
    """Install handlers on the root logger. Call once at startup."""
    settings = get_settings()
    resolved_level = (level or settings.log_level).upper()
    use_json = settings.log_json if as_json is None else as_json

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        JsonFormatter()
        if use_json
        else logging.Formatter("%(asctime)s %(levelname)-8s %(name)s  %(message)s")
    )
    handler.addFilter(PiiRedactionFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(resolved_level)

    # httpx logs every request URL at INFO - noisy, and a leak risk.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
