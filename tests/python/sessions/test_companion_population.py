
from __future__ import annotations

import shutil
import subprocess
import uuid
from contextlib import closing
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.config import settings
from src.core import session_store
from src.core.companion_shell import index as companion_index
from src.core.db import connect, db_path_for
from src.core.db_models import SESSION_LIFECYCLE_STOPPED, SESSION_ORIGIN_OBSERVED
from src.core.hosts import store as hosts_store
from src.core.session_identity import record_instance
from src.core.session_journal_measure import read_rows
from src.core.session_manager import SessionManager
from src.core.session_sleep import asleep_rows
from src.core.tmux_backend import TmuxBackend
from src.models import Session, SessionStatus
from tests.s7_helpers import migrated_connection
from tests.socket_guard import TEST_SOCKET_NAME

requires_tmux = pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux not on PATH")

AGENT_ID, COMPANION_ID = "ses_f2a_agent", "ses_f2a_shell"


def _tmux(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["tmux", "-L", TEST_SOCKET_NAME, *args], capture_output=True, text=True, check=False)


def _epoch(name: str) -> int:
    out = _tmux("list-sessions", "-F", "#{session_name} #{session_created}")
    assert out.returncode == 0, out.stderr
    return int(dict(line.rsplit(" ", 1) for line in out.stdout.splitlines())[name])


@pytest.fixture
def world(tmp_path, monkeypatch):
    state = tmp_path / "state"
    logs = tmp_path / "logs"
    state.mkdir()
    logs.mkdir()
    monkeypatch.setattr(settings, "log_directory", str(logs))
    monkeypatch.setattr(settings, "state_dir_override", str(state))
    names = {"agent": f"carnivore_f2a_a_{uuid.uuid4().hex[:6]}", "shell": f"carnivore_sh-f2a_{uuid.uuid4().hex[:6]}"}
    manager = SessionManager()
    try:
        for name in names.values():
            made = _tmux("new-session", "-d", "-s", name, "-c", str(tmp_path), "-x", "132", "-y", "40")
            assert made.returncode == 0, made.stderr
        with closing(migrated_connection(state)) as conn:
            rows = {}
            for role, name in names.items():
                rows[role] = record_instance(
                    conn, socket=TEST_SOCKET_NAME, name=name, epoch=_epoch(name),
                    origin=SESSION_ORIGIN_OBSERVED, agent_type="claude" if role == "agent" else "shell",
                    working_dir=str(tmp_path),
                ).session_id
            for role, name, epoch in (("agent_b", "carnivore_f2a_b", 4001), ("shell_b", "carnivore_sh-f2a_b", 4002)):
                rows[role] = record_instance(
                    conn, socket=TEST_SOCKET_NAME, name=name, epoch=epoch, origin=SESSION_ORIGIN_OBSERVED,
                    lifecycle=SESSION_LIFECYCLE_STOPPED, lifecycle_source="slept_by_user",
                    now="2026-10-11T00:00:00Z", working_dir=str(tmp_path),
                ).session_id
            conn.execute("UPDATE sessions SET companion_of = ? WHERE id = ?", (rows["agent"], rows["shell"]))
            conn.execute("UPDATE sessions SET companion_of = ? WHERE id = ?", (rows["agent_b"], rows["shell_b"]))
            conn.commit()
        for sid, name in ((AGENT_ID, names["agent"]), (COMPANION_ID, names["shell"])):
            manager._registry.backends[sid] = TmuxBackend(
                session_id=sid, working_dir=tmp_path, on_output=None,
                socket_name=TEST_SOCKET_NAME, session_name=name)
        for sid, name in ((AGENT_ID, names["agent"]), (COMPANION_ID, names["shell"])):
            session = Session(id=sid, status=SessionStatus.RUNNING, working_dir=str(tmp_path),
                              created_at=datetime.utcnow(), tmux_session=name)
            manager._registry.register(session, manager._registry.backends[sid])
        yield SimpleNamespace(manager=manager, state=state, names=names, rows=rows)
    finally:
        _tmux("kill-server")


def _ids(rows) -> set:
    return {int(r["id"]) for r in rows}


@requires_tmux
@pytest.mark.asyncio
async def test_companion_is_absent_from_every_reader_and_the_agent_is_present(world, monkeypatch):
    manager, rows = world.manager, world.rows

    assert {i.session.id for i in await manager.list_session_infos()} == {AGENT_ID, COMPANION_ID}

    index = companion_index.install(manager._registry, world.state)
    assert index.shell_row_for(rows["agent"]) == rows["shell"]

    infos = await manager.list_session_infos()
    assert {i.session.id for i in infos} == {AGENT_ID}
    from src.api.session_crud_routes import build_owner_listing

    owner = await build_owner_listing(SimpleNamespace(session_manager=manager))
    assert {i.session.id for i in owner} == {AGENT_ID}
    from src.core.mcp import common

    assert {i.session.id for i in await common._local_infos(manager)} == {AGENT_ID}

    from src.core.attention_wiring import build_attention_watcher

    watcher = build_attention_watcher(manager, app_state=None)
    assert {t.session_id for t in watcher._list_targets()} == {AGENT_ID}

    registry = manager._registry
    assert registry.listable_ids() == [AGENT_ID] and COMPANION_ID in registry.sessions
    assert registry.current_session().id == AGENT_ID
    registry.last_session_id = AGENT_ID
    registry.register(registry.sessions[COMPANION_ID], registry.backends[COMPANION_ID])
    assert registry.last_session_id == AGENT_ID
    assert registry.find_hidden_id(world.names["shell"]) == COMPANION_ID

    with closing(connect(db_path_for(world.state), create=False)) as conn:
        assert {rows["agent"], rows["shell"]} <= _ids(session_store.list_sessions(conn, include_companions=True))
        listed = _ids(session_store.list_sessions(conn))
        assert rows["agent"] in listed and rows["agent_b"] in listed and rows["shell"] not in listed and rows["shell_b"] not in listed
        asleep = _ids(asleep_rows(conn))
        assert rows["agent_b"] in asleep and rows["shell_b"] not in asleep
        from src.core.descriptions.roster import read_context

        roster = _ids(read_context(conn).rows)
        assert rows["agent"] in roster and rows["shell"] not in roster
        conn.execute("UPDATE sessions SET lifecycle = 'unknown' WHERE id IN (?, ?)", (rows["agent_b"], rows["shell_b"]))
        conn.commit()
        needing = _ids(session_store.needs_attention(conn))
        assert rows["agent_b"] in needing and rows["shell_b"] not in needing
        counts = hosts_store.session_counts(conn)
        assert counts["local"] == 2
    journal_rows = read_rows(db_path_for(world.state))[1]
    assert {r["id"] for r in journal_rows} >= {rows["agent"]} and rows["shell"] not in {r["id"] for r in journal_rows}

    from src.core.mcp.protocol import BatchView
    from src.core.mcp.common import ToolError
    from src.core.mcp import session_target

    view = BatchView(manager, app=None)
    with pytest.raises(ToolError, match="companion shell"):
        await session_target.resolve_target(view, {"target": COMPANION_ID}, tool="session_stop")
    reached = await session_target.resolve_target(view, {"target": COMPANION_ID}, tool="session_read_output")
    assert reached.info.session.id == COMPANION_ID
    assert (await session_target.resolve_target(view, {"target": AGENT_ID}, tool="session_stop")).info.session.id == AGENT_ID
