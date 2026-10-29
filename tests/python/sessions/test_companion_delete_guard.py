from __future__ import annotations

from contextlib import closing
from types import SimpleNamespace

import pytest
import structlog

from src.config import settings
from src.core.companion_shell import close
from src.core.companion_shell.ddl import COMPANION_OF_COLUMN
from src.core.db import connect, db_path_for
from src.core.db_models import SESSION_ORIGIN_OBSERVED
from src.core.session_identity import record_instance
from tests.s7_helpers import migrated_connection


def _count(state, row_id: int) -> int:
    with closing(connect(db_path_for(state), create=False)) as conn:
        return conn.execute("SELECT COUNT(*) FROM sessions WHERE id = ?", (row_id,)).fetchone()[0]


def test_delete_row_keeps_a_shell_whose_agent_row_exists_and_deletes_it_once_gone(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "state_dir_override", str(tmp_path))
    with closing(migrated_connection(tmp_path)) as conn:
        ids = {role: record_instance(conn, socket="t", name=f"carnivore_g_{role}", epoch=n, origin=SESSION_ORIGIN_OBSERVED,
                                     agent_type="claude" if role == "agent" else "shell", working_dir=str(tmp_path)).session_id
               for n, role in ((1, "agent"), (2, "shell"))}
        conn.execute(f"UPDATE sessions SET {COMPANION_OF_COLUMN} = ? WHERE id = ?", (ids["agent"], ids["shell"]))
        conn.commit()
    assert close._delete_row(ids["shell"]) is False
    assert _count(tmp_path, ids["shell"]) == 1 and _count(tmp_path, ids["agent"]) == 1
    assert close._delete_row(ids["agent"]) is False and _count(tmp_path, ids["agent"]) == 1
    with closing(connect(db_path_for(tmp_path), create=False)) as conn:
        conn.execute("DELETE FROM sessions WHERE id = ?", (ids["agent"],))
        conn.commit()
    assert close._delete_row(ids["shell"]) is True and _count(tmp_path, ids["shell"]) == 0


def _world(tmp_path, monkeypatch):
    from src.core.companion_shell.index import CompanionIndex

    monkeypatch.setattr(settings, "state_dir_override", str(tmp_path))
    with closing(migrated_connection(tmp_path)) as conn:
        ids = {role: record_instance(conn, socket="t", name=f"carnivore_g_{role}", epoch=n, origin=SESSION_ORIGIN_OBSERVED,
                                     agent_type="claude" if role == "agent" else "shell", working_dir=str(tmp_path)).session_id
               for n, role in ((1, "agent"), (2, "shell"))}
        conn.execute(f"UPDATE sessions SET {COMPANION_OF_COLUMN} = ? WHERE id = ?", (ids["agent"], ids["shell"]))
        conn.commit()
    index = CompanionIndex()
    index.link(agent_row=ids["agent"], shell_row=ids["shell"], tmux_name="carnivore_g_shell")
    return ids, index


@pytest.mark.asyncio
async def test_a_refused_delete_keeps_the_index_entry_and_never_claims_a_purge(tmp_path, monkeypatch):
    ids, index = _world(tmp_path, monkeypatch)
    shell = {"id": ids["shell"], "companion_of": ids["agent"], "tmux_name": None, "tmux_socket": None}
    assert await close.purge_row(index, shell) is False
    assert index.shell_row_for(ids["agent"]) == ids["shell"] and index.is_hidden_name("carnivore_g_shell")
    assert _count(tmp_path, ids["shell"]) == 1
    with structlog.testing.capture_logs() as logs:
        assert await close.close_shell(SimpleNamespace(), index, shell, purge=True) is True
    assert index.shell_row_for(ids["agent"]) == ids["shell"] and _count(tmp_path, ids["shell"]) == 1
    closed = [e for e in logs if e["event"] == "companion_closed"]
    assert closed and closed[0]["purged"] is False
    refused = [e for e in logs if e["event"] == "companion_row_purge_refused"]
    assert refused and refused[0]["reason"] == "agent_row_exists" and refused[0]["shell_row"] == ids["shell"]


@pytest.mark.asyncio
async def test_closing_a_live_agents_shell_still_records_it_stopped_and_keeps_the_row(tmp_path, monkeypatch):
    ids, index = _world(tmp_path, monkeypatch)
    shell = {"id": ids["shell"], "companion_of": ids["agent"], "tmux_name": None, "tmux_socket": None}
    assert await close.close_shell(SimpleNamespace(), index, shell) is True
    with closing(connect(db_path_for(tmp_path), create=False)) as conn:
        row = conn.execute("SELECT lifecycle, lifecycle_source FROM sessions WHERE id = ?", (ids["shell"],)).fetchone()
    assert tuple(row) == ("stopped", "closed_with_agent")
    assert index.shell_row_for(ids["agent"]) == ids["shell"]


@pytest.mark.asyncio
async def test_a_purge_with_the_agent_row_gone_deletes_the_row_and_unlinks(tmp_path, monkeypatch):
    ids, index = _world(tmp_path, monkeypatch)
    with closing(connect(db_path_for(tmp_path), create=False)) as conn:
        conn.execute("DELETE FROM sessions WHERE id = ?", (ids["agent"],))
        conn.commit()
    shell = {"id": ids["shell"], "companion_of": ids["agent"], "tmux_name": None, "tmux_socket": None}
    assert await close.purge_row(index, shell) is True
    assert _count(tmp_path, ids["shell"]) == 0 and index.shell_row_for(ids["agent"]) is None
