
from __future__ import annotations

import asyncio
import shutil
import subprocess
import time
import uuid
from contextlib import asynccontextmanager, closing
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.config import settings
from src.core.companion_shell import ensure
from src.core.companion_shell import index as companion_index
from src.core.db import connect, db_path_for
from src.core.db_models import SESSION_ORIGIN_OBSERVED
from src.core.session_identity import record_instance
from src.core.session_manager import SessionManager
from src.core.tmux_backend import TmuxBackend
from src.models import Session, SessionStatus
from tests.python.beast_mode.grid import arm as arm_beast  # noqa: E402
from tests.s7_helpers import migrated_connection
from tests.socket_guard import TEST_SOCKET_NAME

requires_tmux = pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux not on PATH")

AGENT_ID = "ses_f2b_agent"


def _tmux(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["tmux", "-L", TEST_SOCKET_NAME, *args], capture_output=True, text=True, check=False)


def _sessions() -> dict:
    out = _tmux("list-sessions", "-F", "#{session_name}\t#{session_path}")
    return dict(line.split("\t", 1) for line in out.stdout.splitlines()) if out.returncode == 0 else {}


def _rows(state, where: str = "1=1") -> list:
    with closing(connect(db_path_for(state), create=False)) as conn:
        return [dict(r) for r in conn.execute(f"SELECT * FROM sessions WHERE {where}")]


@pytest.fixture
def world(tmp_path, monkeypatch):
    state, logs = tmp_path / "state", tmp_path / "logs"
    state.mkdir()
    logs.mkdir()
    monkeypatch.setattr(settings, "log_directory", str(logs))
    monkeypatch.setattr(settings, "state_dir_override", str(state))
    real = tmp_path / "real folder"
    real.mkdir()
    link = tmp_path / "linked"
    link.symlink_to(real)
    name = f"carnivore_f2b_a_{uuid.uuid4().hex[:6]}"
    manager = SessionManager()
    try:
        made = _tmux("new-session", "-d", "-s", name, "-c", str(link), "-x", "132", "-y", "40")
        assert made.returncode == 0, made.stderr
        epoch = int(_tmux("display-message", "-p", "-t", f"={name}:", "#{session_created}").stdout.strip())
        with closing(migrated_connection(state)) as conn:
            agent_row = record_instance(conn, socket=TEST_SOCKET_NAME, name=name, epoch=epoch,
                                        origin=SESSION_ORIGIN_OBSERVED, agent_type="claude",
                                        working_dir=str(link)).session_id
        manager._registry.backends[AGENT_ID] = TmuxBackend(
            session_id=AGENT_ID, working_dir=link, on_output=None, socket_name=TEST_SOCKET_NAME, session_name=name)
        manager._registry.register(
            Session(id=AGENT_ID, status=SessionStatus.RUNNING, working_dir=str(link),
                    created_at=datetime.utcnow(), tmux_session=name), manager._registry.backends[AGENT_ID])
        index = companion_index.install(manager._registry, state)
        app = SimpleNamespace(state=SimpleNamespace(session_manager=manager, companion_index=index))
        request = SimpleNamespace(app=app, scope={}, headers={}, query_params={})
        yield SimpleNamespace(manager=manager, state=state, request=request, index=index, agent_row=agent_row,
                              link=str(link), agent_name=name)
    finally:
        _tmux("kill-server")


@requires_tmux
@pytest.mark.asyncio
async def test_ensure_creates_reuses_and_two_concurrent_ensures_make_one(world, monkeypatch):
    argvs: list = []
    stdins: list = []
    real_exec, real_run = asyncio.create_subprocess_exec, subprocess.run

    async def spy_exec(*argv, **kw):
        argvs.append([str(a) for a in argv])
        return await real_exec(*argv, **kw)

    def spy_run(argv, *a, **kw):
        argvs.append([str(x) for x in argv])
        stdins.append(str(kw.get("input") or ""))
        return real_run(argv, *a, **kw)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spy_exec)
    monkeypatch.setattr(subprocess, "run", spy_run)
    first, second = await asyncio.gather(ensure.ensure(world.request, AGENT_ID), ensure.ensure(world.request, AGENT_ID))
    assert sorted([first.state, second.state]) == ["created", "existing"]
    assert first.session_id == second.session_id and first.session_row_id == second.session_row_id

    shells = _rows(world.state, f"companion_of = {world.agent_row}")
    assert [r["id"] for r in shells] == [first.session_row_id]
    assert first.agent_row_id == world.agent_row and first.working_dir == world.link
    prefixed = {n: p for n, p in _sessions().items() if n.startswith("carnivore_sh-")}
    assert list(prefixed) == [first.tmux_session] and prefixed[first.tmux_session] == world.link
    assert first.session is not None and first.session.id == first.session_id and first.pane == "live"

    assert {i.session.id for i in await world.manager.list_session_infos()} == {AGENT_ID}
    assert first.session_id in world.manager._registry.sessions

    token = world.manager.hook_tokens.get(first.session_id)
    assert token and not any(token in part for argv in argvs for part in argv)
    assert any(token in script for script in stdins)

    third = await ensure.ensure(world.request, AGENT_ID)
    assert third.state == "existing" and third.session_id == first.session_id
    got = await ensure.read(world.request.app, AGENT_ID)
    assert got.session_id == first.session_id and got.pane == "live"


@requires_tmux
@pytest.mark.asyncio
async def test_a_closed_shell_comes_back_on_the_same_row_and_a_husk_is_respawned(world, monkeypatch):
    from src.api import recreate_routes
    from src.core import session_sleep
    from src.core.session_agent_choice import CHOICE_ACCEPTED, AgentChoice

    monkeypatch.setattr(recreate_routes, "validate_agent_choice",
                        lambda _s, agent_type, **_k: AgentChoice(verdict=CHOICE_ACCEPTED, agent_type=agent_type, command="/bin/sh"))

    from src.core.account_switch import restart_account

    async def no_account(*_a, **_k):
        return SimpleNamespace(account_id=None)

    async def keep_nothing(*_a, **_k):
        return None

    monkeypatch.setattr(restart_account, "family_of", lambda _t: "shell")
    monkeypatch.setattr(restart_account, "resolve", no_account)
    monkeypatch.setattr(restart_account, "persist", keep_nothing)
    from src.core.launch_profiles import create_seam

    monkeypatch.setattr(create_seam, "known_pick_ids", lambda _s: ["shell-default"])

    created = await ensure.ensure(world.request, AGENT_ID)
    await session_sleep.close_for_sleep(world.manager, name=created.tmux_session, socket=TEST_SOCKET_NAME)
    ensure._mark_closed(created.session_row_id)
    assert created.tmux_session not in _sessions()
    with pytest.raises(HTTPException) as gone:
        await ensure.read(world.request.app, AGENT_ID)
    assert gone.value.status_code == 404 and gone.value.detail["code"] == "none"

    again = await ensure.ensure(world.request, AGENT_ID)
    assert again.state == "restarted" and again.session_row_id == created.session_row_id
    assert len(_rows(world.state, f"companion_of = {world.agent_row}")) == 1
    assert {i.session.id for i in await world.manager.list_session_infos()} == {AGENT_ID}

    for _ in range(80):
        _tmux("send-keys", "-t", f"={again.tmux_session}:", "exit", "Enter")
        if (await ensure.read(world.request.app, AGENT_ID)).pane == "dead":
            break
        await asyncio.sleep(0.25)
    else:
        pytest.fail("the shell's pane never read dead")
    husk = await ensure.ensure(world.request, AGENT_ID)
    assert husk.state == "restarted" and husk.session_row_id == created.session_row_id and husk.pane == "live"


@requires_tmux
@pytest.mark.asyncio
async def test_refusals_answer_their_machine_words(world):
    async def code(agent_id: str) -> tuple:
        with pytest.raises(HTTPException) as err:
            await ensure.ensure(world.request, agent_id)
        return err.value.status_code, err.value.detail["code"]

    assert await code("remote:peer-abc:ses_x") == (409, "remote_agent")
    assert await code("ses_not_registered") == (409, "agent_not_running")
    assert await code("carnivore_a_tmux_name") == (404, "unknown_session")
    shell = await ensure.ensure(world.request, AGENT_ID)
    assert await code(shell.session_id) == (409, "is_a_shell")

    with closing(connect(db_path_for(world.state), create=False)) as conn:
        conn.execute("UPDATE sessions SET working_dir = '/nonexistent/f2b' WHERE id = ?", (world.agent_row,))
        conn.commit()
    assert await code(AGENT_ID) == (409, "folder_missing")


def test_route_and_mcp_adapters_are_registered():
    from fastapi import FastAPI

    from src.api import routes
    from src.core.mcp import tools

    app = FastAPI()
    app.include_router(routes.router)
    served = {m for path, ops in app.openapi()["paths"].items() if path == "/sessions/{session_id}/shell" for m in ops}
    assert served == {"post", "get"}, served
    assert "session_shell_open" in tools.WRITE_TOOLS and "session_shell_get" in tools._TOOLS
    assert "session_shell_get" not in tools.WRITE_TOOLS


def test_a_peer_style_bearer_token_is_refused_on_both_routes():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.api import companion_shell_routes

    app = FastAPI()
    app.include_router(companion_shell_routes.router)
    with TestClient(app) as client:
        for headers in ({}, {"Authorization": "Bearer peer_tok_not_a_jwt"}):
            assert client.post("/sessions/ses_x/shell", headers=headers).status_code == 401
            assert client.get("/sessions/ses_x/shell", headers=headers).status_code == 401


@requires_tmux
@pytest.mark.asyncio
async def test_the_mcp_tool_session_shell_open_runs_end_to_end(world, monkeypatch):
    import json

    from src.core.mcp import beast_mode, tools
    from src.core.mcp.caller import AgentCaller

    arm_beast(monkeypatch, lambda: True)

    class View:
        gate_waited = False
        app = world.request.app

        async def list_session_infos(self):
            return await world.manager.list_session_infos()

        async def list_peer_infos(self):
            return []

        def fresh(self):
            return self

    caller = AgentCaller("mcp-token:1", "mcp-token:1", "mcp-token:1", token_name="laptop")
    answer = await tools.call_tool(View(), caller, "session_shell_open", {"target": AGENT_ID})
    assert not answer.get("isError"), answer
    shell = json.loads(answer["content"][0]["text"])
    assert shell["state"] == "created" and shell["agent_session_id"] == AGENT_ID
