"""Regression tests for SPA history-fallback serving (invite-link 404).

After the ``/app`` -> site-root move, the SPA is mounted at ``/`` via
``create_frontend_router``. ``StaticFiles(html=True)`` alone serves only real
files, so a fresh navigation / reload / invite link to a client-side route such
as ``/teacher/activate`` or ``/join`` returned ``{"detail":"Not Found"}``. The
``SPAStaticFiles`` subclass serves ``index.html`` for those paths so the React
router can take over, while genuine ``/api`` 404s stay JSON.
"""

from __future__ import annotations

import pathlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shared.app import create_frontend_router


@pytest.fixture()
def spa_client(tmp_path: pathlib.Path) -> TestClient:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>ADAM SPA</title>")
    assets = dist / "assets"
    assets.mkdir()
    (assets / "app.js").write_text("console.log('app')")

    app = FastAPI()

    @app.get("/api/ping")
    def _ping() -> dict[str, bool]:
        return {"pong": True}

    # Absolute build_dir overrides create_frontend_router's relative resolution.
    app.mount("/", create_frontend_router(str(dist)), name="frontend")
    return TestClient(app)


def test_root_serves_index(spa_client: TestClient) -> None:
    response = spa_client.get("/")
    assert response.status_code == 200
    assert "ADAM SPA" in response.text


def test_real_asset_is_served(spa_client: TestClient) -> None:
    response = spa_client.get("/assets/app.js")
    assert response.status_code == 200
    assert "console.log" in response.text


@pytest.mark.parametrize(
    "path",
    ["/teacher/activate", "/join", "/teacher/dashboard", "/student/dashboard"],
)
def test_deep_client_routes_fall_back_to_index(spa_client: TestClient, path: str) -> None:
    # Invite links / reloads land directly on a deep route; the server must serve
    # the SPA shell so the client router can read the route + #hash token.
    response = spa_client.get(path)
    assert response.status_code == 200, (path, response.status_code, response.text)
    assert "ADAM SPA" in response.text


def test_registered_api_route_takes_precedence(spa_client: TestClient) -> None:
    response = spa_client.get("/api/ping")
    assert response.status_code == 200
    assert response.json() == {"pong": True}


def test_unknown_api_path_stays_json_404(spa_client: TestClient) -> None:
    # Genuine API 404s must NOT be masked by the SPA shell.
    response = spa_client.get("/api/does-not-exist")
    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}
