"""The application factory.

One process serves both halves: the API under `/api`, and the built React
bundle at everything else. That is a decision, not a convenience.

- **No CORS.** Same origin by construction, so there is no allowlist to widen
  by accident and no preflight to get wrong.
- **No second port.** One command starts the application; a reviewer cloning
  this repo does not have to discover that two things must be running.
- **No base URL in the client.** The frontend calls `/api`, always.

The bundle is optional. A checkout with no `frontend/dist` still serves the
API and answers the root with a note saying how to build it, because the tests
and the evaluation harness need the API and have no use for the HTML.

Client-side routing means any unknown path that is not under `/api` has to
return `index.html` rather than a 404 - React Router reads the path itself.
`_SinglePageFiles` is that rule and nothing more.

There is no module-level `app`. Building one at import time would read the
settings - and therefore fail on a missing key - before anything had asked for
a server, which is how a test suite ends up needing a `.env`. Uvicorn is
started in factory mode instead:

    uvicorn career_copilot.api.app:create_app --factory --port 8000
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import Scope

from career_copilot.api.errors import install_error_handlers
from career_copilot.api.routes import (
    chat,
    documents,
    feedback,
    health,
    interview,
    jobs,
    jobs_sync,
    memory,
    resumes,
    settings,
    usage,
)
from career_copilot.core.logging import configure_logging, get_logger
from career_copilot.rag.warmup import warm_in_background

__all__ = ["FRONTEND_DIST", "create_app", "is_api_path"]

log = get_logger(__name__)

#: Where `npm run build` puts the bundle, relative to the repository root.
FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"

_API_ROOT = "api"
_API_PREFIX = "api/"


def is_api_path(request_path: str, mounted_path: str) -> bool:
    """Whether this request belongs to the API rather than to the frontend.

    Both spellings of the path are checked, and the leading slash is ignored
    on each. The two arguments come from different places - the request as it
    arrived, and the remainder the mount handed on - and which of them carries
    a leading slash has moved between Starlette versions. Deciding on either
    one alone is a rule that works on the machine it was written on.
    """
    for candidate in (request_path, mounted_path):
        relative = candidate.lstrip("/")
        if relative == _API_ROOT or relative.startswith(_API_PREFIX):
            return True
    return False


_NO_BUNDLE = {
    "status": "ok",
    "detail": (
        "The API is running. The frontend bundle is not built - "
        "run `npm install && npm run build` in ./frontend."
    ),
}


class _SinglePageFiles(StaticFiles):
    """Static files, with unknown paths falling back to `index.html`.

    Two things it deliberately does not do.

    **It does not serve anything under `/api`.** The mount is at `/`, so every
    path the routers did not match arrives here - including a misspelt
    endpoint. Answering that with the app shell and a 200 would turn a typo
    into a page that renders perfectly and never loads, and would put it out
    of reach of the client's own error handling.

    Those paths are refused up front rather than after asking the parent
    class, because what the parent does with a missing file is its business
    and has changed between versions: with `html=True` it may raise a 404, or
    serve a `404.html`, or resolve the path somewhere unexpected on a
    different operating system. None of that should be able to decide whether
    `/api/uasge` is a 404.

    **It does not rewrite anything but a 404.** A 403 or a 405 is a real
    answer and stays one.
    """

    async def get_response(self, path: str, scope: Scope) -> Response:
        if is_api_path(str(scope.get("path", "")), path):
            raise StarletteHTTPException(status_code=404)
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404:
                raise
            return FileResponse(Path(self.directory or ".") / "index.html")


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Start loading the retrieval models, and do not wait for them.

    The embedder and the cross-encoder are otherwise loaded inside whichever
    request needs them first, which means the first question of a session pays
    for both before retrieval starts. Warming them here moves that cost to a
    moment when nobody is waiting on an answer.

    Deliberately not awaited: the server must be answering HTTP immediately,
    and a warm-up that failed must not stop it starting.
    """
    warm_in_background()
    yield


def create_app() -> FastAPI:
    """Build the application. Called by uvicorn and by the tests alike."""
    configure_logging()

    app = FastAPI(
        title="Praxa API",
        summary="Career Copilot: retrieval, tools and cost control over HTTP.",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        lifespan=_lifespan,
    )

    install_error_handlers(app)

    app.include_router(health.router, prefix="/api")
    app.include_router(usage.router, prefix="/api")
    app.include_router(settings.router, prefix="/api")
    app.include_router(chat.router, prefix="/api")
    app.include_router(jobs.router, prefix="/api")
    app.include_router(jobs_sync.router, prefix="/api")
    app.include_router(memory.router, prefix="/api")
    app.include_router(documents.router, prefix="/api")
    app.include_router(resumes.router, prefix="/api")
    app.include_router(interview.router, prefix="/api")
    app.include_router(feedback.router, prefix="/api")

    if FRONTEND_DIST.is_dir():
        app.mount("/", _SinglePageFiles(directory=FRONTEND_DIST, html=True), name="frontend")
    else:
        log.warning("no frontend bundle at %s - serving the API only", FRONTEND_DIST)

        @app.get("/", include_in_schema=False)
        def _root() -> JSONResponse:
            return JSONResponse(_NO_BUNDLE)

    return app
