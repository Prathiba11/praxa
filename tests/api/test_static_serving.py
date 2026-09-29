"""One process serves the API and the React bundle. These are the seams.

Every test here builds the app with a *bundle present*, which the other API
tests do not. That distinction matters: with no `frontend/dist` the static
mount does not exist at all, so a fallback rule that swallows API paths passes
every test in this suite and then fails the first time anybody builds the
frontend. It was found exactly that way.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from career_copilot.api import app as app_module
from career_copilot.api.app import create_app, is_api_path

INDEX = "<!doctype html><html><body><div id=root></div></body></html>"


# ------------------------------------------------------- the rule, on its own
#
# Tested directly as well as through a request. Whether the mount hands on
# "api/x" or "/api/x" has moved between Starlette versions, and a rule checked
# only end-to-end is a rule verified against one version on one machine.


@pytest.mark.parametrize(
    ("request_path", "mounted_path"),
    [
        ("/api/uasge", "api/uasge"),  # Starlette strips the leading slash
        ("/api/uasge", "/api/uasge"),  # ...or does not
        ("/api", "api"),
        ("/api/", "api/"),
        ("/api/chat/stream", "api/chat/stream"),
    ],
)
def test_anything_under_api_belongs_to_the_api(request_path, mounted_path):
    assert is_api_path(request_path, mounted_path) is True


@pytest.mark.parametrize(
    ("request_path", "mounted_path"),
    [
        ("/", ""),
        ("/jobs", "jobs"),
        ("/assets/index-abc123.js", "assets/index-abc123.js"),
        ("/apiary", "apiary"),  # starts with "api" but is not under it
        ("/apidocs/index.html", "apidocs/index.html"),
    ],
)
def test_everything_else_belongs_to_the_frontend(request_path, mounted_path):
    assert is_api_path(request_path, mounted_path) is False


@pytest.fixture()
def bundled_client(api_settings, tmp_path, monkeypatch):
    """The app as a user gets it: API plus a built frontend."""
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(INDEX, encoding="utf-8")
    (dist / "assets" / "index-abc123.js").write_text("export const praxa = 1\n", encoding="utf-8")

    monkeypatch.setattr(app_module, "FRONTEND_DIST", dist)
    with TestClient(create_app()) as client:
        yield client


def test_the_root_serves_the_app_shell(bundled_client):
    response = bundled_client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


def test_a_client_side_route_serves_the_shell_rather_than_a_404(bundled_client):
    """React Router reads the path itself, so the server must hand it over."""
    response = bundled_client.get("/jobs/bosch-cyber-engineer")

    assert response.status_code == 200
    assert "<div id=root>" in response.text


def test_a_real_asset_is_served_as_itself(bundled_client):
    response = bundled_client.get("/assets/index-abc123.js")

    assert response.status_code == 200
    assert "praxa" in response.text


def test_a_misspelt_api_path_is_a_404_not_the_app_shell(bundled_client):
    """The bug this file exists for.

    The mount is at `/`, so an unmatched `/api/...` reaches the static files.
    Answering it with the shell and a 200 turns a typo into a page that
    renders and does nothing, and hides it from the client's error handling.
    """
    response = bundled_client.get("/api/uasge")

    assert response.status_code == 404
    assert "<div id=root>" not in response.text


def test_a_404_under_api_uses_the_same_error_envelope(bundled_client):
    body = bundled_client.get("/api/uasge").json()

    assert body["code"] == "not_found"


def test_the_api_still_answers_with_the_bundle_mounted(bundled_client):
    assert bundled_client.get("/api/health").json()["status"] == "ok"


@pytest.fixture()
def unbuilt_client(api_settings, tmp_path, monkeypatch):
    """The app in a checkout where `npm run build` has never been run.

    Pointed at a path that does not exist rather than at whatever happens to
    be in the working tree, so the test says the same thing on a machine that
    has built the frontend and one that has not.
    """
    monkeypatch.setattr(app_module, "FRONTEND_DIST", tmp_path / "never-built")
    with TestClient(create_app()) as client:
        yield client


def test_without_a_bundle_the_api_still_runs(unbuilt_client):
    """A clone that has not run `npm install` must still serve the API."""
    client = unbuilt_client
    response = client.get("/")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert client.get("/api/health").status_code == 200
