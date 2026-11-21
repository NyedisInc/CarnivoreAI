
from __future__ import annotations

import asyncio
import uuid
from contextlib import closing
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.config import settings
from tests.helpers.bridge_launch import (
    UUID, capture_commands, pane, seed_row, tmux, unchecked_transcripts, use_bridge_config,
)

OLD_EPOCH = 1790000000


@pytest.fixture()
def bridge_config(tmp_path, monkeypatch):
    yield use_bridge_config(tmp_path, monkeypatch)
    settings._auth_config_cache = None


@pytest.fixture(autouse=True)
def _rig(monkeypatch):
    unchecked_transcripts(monkeypatch)

    async def _active(_working_dir):
        return None

    monkeypatch.setattr("src.api.recreate_action.project_home.require_active", _active)


def _manager():
    from unittest.mock import patch

    from src.core.session_manager import SessionManager

    with patch.object(SessionManager, "_load_session_metadata", return_value=None):
        return SessionManager()


def _facts(socket: str, name: str) -> tuple:
    return tuple(tmux(socket, "display-message", "-p", "-t", f"={name}:", "#{pane_pid}|#{session_created}").strip().split("|"))


def _row_of(state, session_uuid: str) -> dict:
    from src.core.db import connect, db_path_for

    with closing(connect(db_path_for(state), create=False)) as conn:
        return dict(conn.execute("SELECT * FROM sessions WHERE session_uuid = ?", (session_uuid,)).fetchone())


@pytest.mark.asyncio
async def test_recreate_lands_under_a_suffixed_name_and_spares_the_holder(bridge_config, monkeypatch, tmux_test_socket):
    from src.api.recreate_action import recreate_by_uuid

    name = f"carnivore_held{uuid.uuid4().hex[:6]}"
    holder_epoch = pane(tmux_test_socket, name, "sh -c 'sleep 60'", dead=False)
    before = _facts(tmux_test_socket, name)
    session_uuid = seed_row(bridge_config / "state", tmux_test_socket, name, OLD_EPOCH, lifecycle_source="closed_by_user")
    capture_commands(monkeypatch, run_instead="sh -c 'sleep 45'")
    mgr = _manager()
    answer = None
    try:
        answer = await recreate_by_uuid(session_uuid, "cld", get_manager=lambda: mgr)
        after = _facts(tmux_test_socket, name)
        row = _row_of(bridge_config / "state", session_uuid)
    finally:
        for target in (name, f"{name}-2"):
            tmux_ok = [t for t in tmux(tmux_test_socket, "list-sessions", "-F", "#{session_name}").split() if t == target]
            if tmux_ok:
                tmux(tmux_test_socket, "kill-session", "-t", f"={target}")
    assert answer.status == "started", answer.detail
    assert answer.tmux_session == f"{name}-2"
    assert row["tmux_name"] == f"{name}-2" and row["session_uuid"] == session_uuid
    assert after == before and int(before[1]) == holder_epoch, "the holder's pane was touched"


@pytest.mark.asyncio
async def test_interleaved_recreates_of_one_row_make_one_pane(bridge_config, monkeypatch, tmux_test_socket):
    from src.api import recreate_action

    name = f"carnivore_mid{uuid.uuid4().hex[:6]}"
    state = bridge_config / "state"
    session_uuid = seed_row(state, tmux_test_socket, name, OLD_EPOCH, lifecycle_source="closed_by_user")
    capture_commands(monkeypatch)
    mgr = _manager()
    pane_up, creates = asyncio.Event(), []

    async def slow_create(**kwargs):
        creates.append(kwargs["project_name"])
        epoch = pane(tmux_test_socket, name, "sh -c 'sleep 60'", dead=False)
        pane_up.set()
        await asyncio.sleep(1.0)
        from src.core.db import connect, db_path_for

        with closing(connect(db_path_for(state), create=False)) as conn:
            conn.execute("UPDATE sessions SET tmux_created_epoch = ?, lifecycle = 'running' WHERE session_uuid = ?",
                         (epoch, session_uuid))
            conn.commit()
        return SimpleNamespace(id="ses_a", tmux_session=name)

    monkeypatch.setattr(mgr, "create_session", slow_create)
    kwargs = {"get_manager": lambda: mgr}
    first = asyncio.create_task(recreate_action._recreate_claimed(session_uuid, "cld", **kwargs))
    try:
        await asyncio.wait_for(pane_up.wait(), 10)
        second = await recreate_action._recreate_claimed(session_uuid, "cld", **kwargs)
        assert (await first).status == "started"
        assert second.status == "refused", second.detail
        assert creates == [name], "a second create ran for the same row"
    finally:
        if name in tmux(tmux_test_socket, "list-sessions", "-F", "#{session_name}").split():
            tmux(tmux_test_socket, "kill-session", "-t", f"={name}")


@pytest.mark.asyncio
async def test_every_caller_of_recreate_by_uuid_is_claimed(bridge_config, monkeypatch, tmux_test_socket):
    from src.api.recreate_action import recreate_by_uuid
    from src.core import restart_inflight

    name = f"carnivore_claim{uuid.uuid4().hex[:6]}"
    session_uuid = seed_row(bridge_config / "state", tmux_test_socket, name, OLD_EPOCH, lifecycle_source="closed_by_user")
    mgr = _manager()
    taken, release = asyncio.Event(), asyncio.Event()

    async def hold():
        with restart_inflight.claim(session_uuid):
            taken.set()
            await release.wait()

    holder = asyncio.create_task(hold())
    await taken.wait()
    try:
        with pytest.raises(HTTPException) as caught:
            await recreate_by_uuid(session_uuid, "cld", get_manager=lambda: mgr)
        assert caught.value.status_code == 409
    finally:
        release.set()
        await holder
    with restart_inflight.claim(session_uuid):
        with restart_inflight.claim(session_uuid):
            pass
