
from __future__ import annotations

import uuid
from contextlib import closing
from types import SimpleNamespace

import pytest

from src.config import settings
from src.core import session_sleep
from src.core.session_pane_death import LIFECYCLE_SOURCE_PANE_DEAD
from tests.helpers.bridge_launch import (
    UUID, argv_of, assert_bridge, capture_commands, pane, seed_row, tmux, unchecked_transcripts, use_bridge_config,
)


@pytest.fixture()
def bridge_config(tmp_path, monkeypatch):
    yield use_bridge_config(tmp_path, monkeypatch)
    settings._auth_config_cache = None


@pytest.fixture(autouse=True)
def _transcript_on_disk(monkeypatch):
    monkeypatch.setattr(session_sleep, "_transcript_absent", lambda row, uuid_: False)


def _row(source: str, uuid_: str = UUID, **extra) -> dict:
    return {"lifecycle": "stopped", "lifecycle_source": source, "claude_session_uuid": uuid_,
            "archived_at": None, **extra}


def test_a_dead_pane_stop_with_a_conversation_reads_asleep():
    assert session_sleep.is_asleep(_row(LIFECYCLE_SOURCE_PANE_DEAD))
    assert session_sleep.is_dead_pane_stop(_row(LIFECYCLE_SOURCE_PANE_DEAD))
    assert not session_sleep.is_asleep(_row(LIFECYCLE_SOURCE_PANE_DEAD, uuid_=""))
    assert not session_sleep.is_asleep(_row(LIFECYCLE_SOURCE_PANE_DEAD, archived_at="2026-10-13T00:00:00Z"))
    assert not session_sleep.is_asleep({**_row(LIFECYCLE_SOURCE_PANE_DEAD), "lifecycle": "running"})
    assert session_sleep.is_asleep(_row("slept_by_user", uuid_=""))
    assert not session_sleep.is_asleep(_row("closed_by_user"))
    assert not session_sleep.is_dead_pane_stop(_row("slept_by_user"))


def test_a_sleep_still_never_writes_the_dead_pane_source():
    with pytest.raises(ValueError):
        session_sleep.mark_asleep(None, row_id=1, tmux_name="a", tmux_created_epoch=1, source=LIFECYCLE_SOURCE_PANE_DEAD)


def test_a_dead_pane_row_is_listed_asleep_for_the_sidebar_and_sessions_list(bridge_config, tmux_test_socket):
    from src.core.crosstalk import directory
    from src.core.db import connect, db_path_for

    state = bridge_config / "state"
    name = f"dp{uuid.uuid4().hex[:6]}"
    dead_uuid = seed_row(state, tmux_test_socket, name, 1790000000, lifecycle_source=LIFECYCLE_SOURCE_PANE_DEAD)
    with closing(connect(db_path_for(state), create=False)) as conn:
        assert [r["session_uuid"] for r in session_sleep.asleep_rows(conn)] == [dead_uuid]
    assert [r["session_uuid"] for r in directory._asleep_rows()] == [dead_uuid]
    assert name in session_sleep.reserved_names(set(), db_path=db_path_for(state))


def test_classify_husk_wakes_only_the_rows_own_dead_instance():
    from src.api import session_wake_in_place as w

    assert w.classify_husk("1|17|a\n", "a", 17) == w.HUSK_DEAD
    assert w.classify_husk("0|17|a", "a", 17) == w.HUSK_ALIVE
    assert w.classify_husk("1|18|a", "a", 17) == w.HUSK_OTHER
    assert w.classify_husk("1|17|a-2", "a", 17) == w.HUSK_UNKNOWN
    assert w.classify_husk("1|17|a", "a", None) == w.HUSK_UNKNOWN
    assert w.classify_husk(None, "a", 17) == w.HUSK_UNKNOWN
    assert w.classify_husk("", "a", 17) == w.HUSK_UNKNOWN


def _manager():
    from unittest.mock import patch

    from src.core.session_manager import SessionManager

    with patch.object(SessionManager, "_load_session_metadata", return_value=None):
        return SessionManager()


def _pane_facts(socket: str, name: str) -> tuple:
    return tuple(tmux(socket, "display-message", "-p", "-t", f"={name}:",
                      "#{pane_id}|#{session_created}|#{pane_dead}").strip().split("|"))


@pytest.mark.asyncio
async def test_wake_on_a_dead_husk_resumes_in_place_without_a_kill(bridge_config, monkeypatch, tmux_test_socket):
    from src.api.session_sleep_routes import wake_by_uuid

    name = f"carnivore_dpwake{uuid.uuid4().hex[:6]}"
    epoch = pane(tmux_test_socket, name, "sh -c 'sleep 0.3; exit 0'", dead=True)
    session_uuid = seed_row(bridge_config / "state", tmux_test_socket, name, epoch,
                            lifecycle_source=LIFECYCLE_SOURCE_PANE_DEAD)
    pane_id, created, dead = _pane_facts(tmux_test_socket, name)
    assert dead == "1", "setup: the pane did not die"
    unchecked_transcripts(monkeypatch)
    seen = capture_commands(monkeypatch, run_instead=f"sh -c 'sleep 45' _ --resume {UUID}")
    try:
        answer = await wake_by_uuid(SimpleNamespace(session_manager=_manager()), session_uuid)
        after = _pane_facts(tmux_test_socket, name)
    finally:
        tmux(tmux_test_socket, "kill-session", "-t", f"={name}")
    assert answer.status == "started", answer.detail
    assert answer.presence == "present" and answer.conversation == "resumed"
    assert after == (pane_id, created, "0"), "the wake did not respawn the same pane of the same instance"
    assert seen, "the wake rendered no launch command"
    for _agent, command in seen:
        assert_bridge(argv_of(command, bridge_config))


@pytest.mark.asyncio
async def test_wake_refuses_a_live_pane_and_touches_nothing(bridge_config, monkeypatch, tmux_test_socket):
    from src.api.session_sleep_routes import wake_by_uuid

    name = f"carnivore_dplive{uuid.uuid4().hex[:6]}"
    epoch = pane(tmux_test_socket, name, "sh -c 'sleep 30'", dead=False)
    session_uuid = seed_row(bridge_config / "state", tmux_test_socket, name, epoch,
                            lifecycle_source=LIFECYCLE_SOURCE_PANE_DEAD)
    before = _pane_facts(tmux_test_socket, name)
    pid = tmux(tmux_test_socket, "display-message", "-p", "-t", f"={name}:", "#{pane_pid}").strip()
    seen = capture_commands(monkeypatch)
    try:
        answer = await wake_by_uuid(SimpleNamespace(session_manager=_manager()), session_uuid)
        after = _pane_facts(tmux_test_socket, name)
        pid_after = tmux(tmux_test_socket, "display-message", "-p", "-t", f"={name}:", "#{pane_pid}").strip()
    finally:
        tmux(tmux_test_socket, "kill-session", "-t", f"={name}")
    assert answer.status == "refused" and "running again" in answer.detail
    assert (after, pid_after) == (before, pid) and seen == []


@pytest.mark.asyncio
async def test_session_restart_reaches_a_dead_pane_row_through_the_wake(bridge_config, monkeypatch, tmux_test_socket):
    from src.core.mcp import session_control_tools, write_tools

    name = f"dprst{uuid.uuid4().hex[:6]}"
    dead_uuid = seed_row(bridge_config / "state", tmux_test_socket, name, 1790000001,
                         lifecycle_source=LIFECYCLE_SOURCE_PANE_DEAD)
    calls = []

    async def fake_wake(manager, caller, args):
        calls.append(args)
        return {"status": "started"}

    row = session_control_tools.WRITE_TOOLS["session_wake"]
    monkeypatch.setitem(session_control_tools.WRITE_TOOLS, "session_wake", (*row[:3], fake_wake))

    class _NoLive:
        async def list_session_infos(self):
            return []

        async def list_peer_infos(self):
            return []

    answer = await write_tools.session_restart(_NoLive(), SimpleNamespace(), {"target": name})
    assert answer == {"status": "started"} and calls == [{"target": dead_uuid}]
