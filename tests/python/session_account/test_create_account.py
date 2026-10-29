
from __future__ import annotations

import asyncio
import json
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

os.environ.setdefault("DEFAULT_WORKING_DIR", "/tmp")

from src.api.auth import require_auth  # noqa: E402
from src.api.peer_auth import require_peer_sessions  # noqa: E402
from src.api.restart_account_routes import router as accounts_router  # noqa: E402
from src.api.session_crud_routes import router as sessions_router  # noqa: E402
from src.core.account_switch import session_pin, store  # noqa: E402
from src.core.launch_profiles import create_seam  # noqa: E402
from src.core.launch_profiles.resolve import LaunchRequest, resolve_launch  # noqa: E402
from src.models import Session  # noqa: E402
from tests.python.session_account.test_session_account_pin import config  # noqa: E402,F401


def _peer_marker(request: Request) -> None:
    if request.headers.get("x-test-peer"):
        request.state.peer_grant = object()


def test_create_launches_on_the_chosen_account_pins_it_and_records_it(config, tmp_path):  # noqa: F811
    store.set_active(config, "claude", "play")
    manager = SimpleNamespace(
        create_session=AsyncMock(return_value=Session(id="ses_1", working_dir=str(tmp_path), tmux_session="cloude_n1")),
        tmux_socket_name=lambda: "cloude",
        _row_identity_for_tmux_name=lambda name, socket: {"session_uuid": "u-new" if name == "cloude_n1" else None},
    )
    app = FastAPI()
    app.state.session_manager = manager
    app.include_router(sessions_router, prefix="/api/v1")
    app.include_router(accounts_router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    app.dependency_overrides[require_peer_sessions] = _peer_marker
    client = TestClient(app)

    def post(**body):
        headers = {"x-test-peer": "1"} if body.pop("peer", False) else {}
        return client.post("/api/v1/sessions", json={"working_dir": str(tmp_path), "agent_type": "claude", **body},
                           headers=headers)

    assert post(account_id="work", account_pinned=True).status_code == 201
    assert manager.create_session.await_args.kwargs["claude_account"] == "work"
    assert session_pin.pin_for(config, "u-new") == "work"

    session_pin.apply_choice(config, "u-new", "work", pinned=False)
    assert post(account_id="play").status_code == 201
    assert manager.create_session.await_args.kwargs["claude_account"] == "play"
    assert session_pin.pin_for(config, "u-new") is None

    assert post().status_code == 201
    assert manager.create_session.await_args.kwargs["claude_account"] is None

    launches = manager.create_session.await_count
    assert post(account_id="cx").status_code == 400
    assert post(account_id="work", host_key="remote-1").status_code == 400
    assert post(account_pinned=True).status_code == 400
    assert post(account_id="work", auto_start_claude=False).status_code == 400
    assert post(account_id="work", peer=True).status_code == 400
    assert manager.create_session.await_count == launches

    listed = client.get("/api/v1/launch/accounts").json()
    assert {"work", "play"} <= {o["id"] for o in listed["options"]} and "cx" not in {o["id"] for o in listed["options"]}
    assert (listed["selected_id"], listed["current_id"], listed["pinned"]) == ("play", None, False)

    plan = resolve_launch(LaunchRequest(profiles=(), agent_type="claude"))
    chosen = asyncio.run(create_seam.prepare(plan, account_id="work"))
    assert json.loads(chosen.record)["account"]["id"] == "work"
    assert json.loads(asyncio.run(create_seam.prepare(plan)).record)["account"]["id"] == "play"


def test_guard_refuses_account_for_paired_host(monkeypatch):
    import json

    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient

    from src.api import peer_route_guard as guard

    async def _ok(conn, token):
        return False

    monkeypatch.setattr(guard, "create_target", lambda host_key: object())
    monkeypatch.setattr(guard, "_authenticate", _ok)
    app = FastAPI()

    @app.post("/api/v1/sessions", dependencies=[__import__("fastapi").Depends(guard.peer_route_guard)])
    async def _create():
        return {"forwarded": False}

    client = TestClient(app)
    for body in (
        {"working_dir": "/x", "host_key": "peer-1", "account_id": "work"},
        {"working_dir": "/x", "host_key": "peer-1", "account_pinned": True},
    ):
        resp = client.post("/api/v1/sessions", json=body)
        assert resp.status_code == 400, (body, resp.text)
        assert "account is chosen" in json.dumps(resp.json())
