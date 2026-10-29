
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

os.environ.setdefault("DEFAULT_WORKING_DIR", "/tmp")

from src.api import session_sleep_routes  # noqa: E402
from src.api.auth import require_auth  # noqa: E402
from src.api.peer_auth import require_peer_sessions  # noqa: E402
from src.core.account_switch import create_account, restart_account, session_pin, store  # noqa: E402
from src.core.launch_profiles import create_seam, restart_seam  # noqa: E402
from src.core.mcp import launch_profile_tools, write_tools  # noqa: E402
from src.core.mcp.common import ToolError  # noqa: E402
from tests.python.session_account.test_session_account_pin import config  # noqa: E402,F401


def _create(tmp_path, **args):
    caller = SimpleNamespace(tmux_name="agent")
    return asyncio.run(write_tools.session_create(SimpleNamespace(), caller, {"working_dir": str(tmp_path), **args}))


def test_mcp_session_create_refuses_a_bad_account_before_the_owner_is_asked(config, tmp_path):  # noqa: F811
    with pytest.raises(ToolError, match=r"launchable account ids: .*work"):
        _create(tmp_path, agent_type="claude", account="nope")
    with pytest.raises(ToolError, match="launchable account ids"):
        _create(tmp_path, agent_type="codex", account="work")
    with pytest.raises(ToolError, match="needs account"):
        _create(tmp_path, agent_type="claude", always_use_account=True)
    with pytest.raises(ToolError, match="paired computer"):
        _create(tmp_path, agent_type="claude", account="work", peer="other")
    listed = asyncio.run(launch_profile_tools.launch_accounts_list(None, None, {}))
    assert "work" in json.dumps(listed)


def test_wake_route_forwards_the_account_and_refuses_a_box_alone_or_a_peer(config, monkeypatch):  # noqa: F811
    seen = {}

    async def fake_wake(app_state, uuid, agent_type=None, *, account_id=None, account_pinned=False, extra_env=None,
                        start_fresh=False):
        seen.update(account_id=account_id, account_pinned=account_pinned)
        return JSONResponse({"status": "refused"})

    monkeypatch.setattr(session_sleep_routes, "wake_by_uuid", fake_wake)
    app = FastAPI()
    app.include_router(session_sleep_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "t"}

    def peer_marker(request: Request):
        if request.headers.get("x-test-peer"):
            request.state.peer_grant = object()

    app.dependency_overrides[require_peer_sessions] = peer_marker
    client = TestClient(app)
    url = "/api/v1/sessions/u1/wake"
    assert client.post(url, json={"account_id": "work", "account_pinned": True}).status_code == 200
    assert seen == {"account_id": "work", "account_pinned": True}
    assert client.post(url, json={"account_pinned": True}).status_code == 400
    assert client.post(url, json={"account_id": "work"}, headers={"x-test-peer": "1"}).status_code == 400


def test_a_failed_pin_never_fails_the_create(config, monkeypatch):  # noqa: F811
    plan = restart_account.AccountPlan(account_id="work", chosen=True, pinned_box=True)

    def boom(name, socket):
        raise sqlite3.OperationalError("locked")

    manager = SimpleNamespace(tmux_socket_name=lambda: "cloude", _row_identity_for_tmux_name=boom)
    assert asyncio.run(create_account.pin_after_create(manager, "cloude_n1", plan)) is None
    manager._row_identity_for_tmux_name = lambda name, socket: {}
    assert asyncio.run(create_account.pin_after_create(manager, "cloude_n1", plan)) is None
    assert session_pin.pin_for(config, "u-x") is None


def test_restart_record_is_restamped_with_the_account_it_ran_on(config):  # noqa: F811
    store.set_active(config, "claude", "play")
    record = json.dumps({"harness": "claude", "account": {"id": "play"}})
    assert json.loads(restart_seam._with_account(record, "work"))["account"]["id"] == "work"
    assert create_seam.recorded_account_id("claude", "removed") == "play"
    assert json.loads(restart_seam._with_account(record, "removed"))["account"]["id"] == "play"


@pytest.mark.asyncio
async def test_two_ways_to_name_an_account_is_a_400_not_a_500():
    from fastapi import HTTPException

    from src.api.session_crud_routes import create_session_with_extra
    from src.models import CreateSessionRequest

    body = CreateSessionRequest(working_dir="/tmp", account_id="work")
    with pytest.raises(HTTPException) as refused:
        await create_session_with_extra(SimpleNamespace(), body, claude_account="play")
    assert refused.value.status_code == 400
