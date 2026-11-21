
from __future__ import annotations

import asyncio
import os
import signal
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from src.api import app_update_routes, server_control_routes
from src.api.auth import require_auth
from src.core.app_update import store
from tests.python.route_tests.harness import client_for


@pytest.fixture(autouse=True)
def clean_store():
    store.reset_for_tests()
    yield
    store.reset_for_tests()


def test_report_attaches_the_app_and_is_read_back_by_the_status() -> None:
    client = client_for(app_update_routes.router)
    assert client.get("/app-update").json()["attached"] is False
    resp = client.post("/app-update/state", json={"state": "available", "current_version": "1.0.0", "latest_version": "1.1.0"})
    assert resp.status_code == 200, resp.text
    body = client.get("/app-update").json()
    assert body["attached"] is True and body["state"] == "available" and body["latest_version"] == "1.1.0"


def test_report_refuses_an_unknown_state_and_stays_unattached() -> None:
    client = client_for(app_update_routes.router)
    assert client.post("/app-update/state", json={"state": "exploding"}).status_code == 422
    assert client.get("/app-update").json()["attached"] is False


@pytest.mark.parametrize("body", [{"state": "current", "percent": 101}, {"state": "current", "surprise": 1}, {}])
def test_report_refuses_a_malformed_body(body: dict) -> None:
    assert client_for(app_update_routes.router).post("/app-update/state", json=body).status_code == 422


def test_report_needs_auth() -> None:
    resp = client_for(app_update_routes.router, signed_in=False).post("/app-update/state", json={"state": "current"})
    assert resp.status_code in (401, 403)
    assert store.status()["attached"] is False


def _shutdown_app(signed_in: bool) -> FastAPI:
    app = FastAPI()
    app.include_router(server_control_routes.router)
    if signed_in:
        app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    return app


async def _post_shutdown(app: FastAPI, wait: float) -> httpx.Response:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.post("/shutdown")
        await asyncio.sleep(wait)
        return resp


def test_shutdown_answers_at_once_then_sends_sigterm_to_its_own_pid(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[tuple[int, int]] = []
    monkeypatch.setattr(os, "kill", lambda pid, sig: sent.append((pid, sig)))
    resp = asyncio.run(_post_shutdown(_shutdown_app(True), wait=0.8))
    assert resp.status_code == 200 and resp.json()["message"] == "Server shutdown initiated"
    assert sent == [(os.getpid(), signal.SIGTERM)]


def test_shutdown_refuses_an_anonymous_caller_and_signals_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[Any] = []
    monkeypatch.setattr(os, "kill", lambda pid, sig: sent.append((pid, sig)))
    resp = asyncio.run(_post_shutdown(_shutdown_app(False), wait=0.8))
    assert resp.status_code in (401, 403)
    assert sent == []
