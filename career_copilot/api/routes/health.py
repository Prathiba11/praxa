"""Is the server up, and what is it running.

Deliberately cheap: no model call, no database, no retrieval. A health check
that can fail for an interesting reason is a health check that will, and the
question it answers is only "did the process start and is it serving".

`tracing` is here because it is the one setting whose effect is invisible from
the outside. Everything else about a misconfiguration shows up as an error;
tracing being off shows up as an empty LangSmith project an hour later.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from fastapi import APIRouter

from career_copilot.api.schemas import HealthResponse
from career_copilot.core.config import get_settings
from career_copilot.core.tracing import tracing_active

__all__ = ["router"]

router = APIRouter(tags=["health"])


def _version() -> str:
    """The installed version, or a marker that says it is not installed."""
    try:
        return version("career-copilot")
    except PackageNotFoundError:
        return "0.0.0+source"


def _trace_url(endpoint: str) -> str:
    """Turn the LangSmith API host into the one a person can open.

    The API lives at `eu.api.smith.langchain.com`; the interface is the same
    host without the `api.` part. Getting this wrong is the single most common
    LangSmith misconfiguration, which is why the value is computed here rather
    than left for someone to type into a link.
    """
    default = "https://smith.langchain.com"
    if not endpoint:
        return default
    host = endpoint.replace("https://", "").replace("http://", "").strip("/")
    if not host.endswith("smith.langchain.com"):
        return default
    return f"https://{host.replace('api.', '', 1)}"


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    active = tracing_active()
    settings = get_settings()
    return HealthResponse(
        status="ok",
        version=_version(),
        tracing=active,
        tracing_project=settings.langsmith_project if active else None,
        tracing_url=_trace_url(settings.langsmith_endpoint) if active else None,
    )
