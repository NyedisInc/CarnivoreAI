
from __future__ import annotations

import subprocess
import uuid
from contextlib import closing

import pytest

from src.config import settings
from tests.helpers.bridge_launch import (
    capture_commands, pane, seed_row, tmux, unchecked_transcripts, use_bridge_config,
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


def _sessions(socket: str) -> list:
    try:
        return tmux(socket, "list-sessions", "-F", "#{session_name}").split()
    except subprocess.CalledProcessError:
        return []


@pytest.mark.asyncio
async def test_a_recreate_that_loses_the_race_is_refused_and_stops_only_its_own_pane(bridge_config, monkeypatch, tmux_test_socket):
    from unittest.mock import patch

    from src.api import recreate_action
    from src.core.db import connect, db_path_for
    from src.core.session_manager import SessionManager

    name = f"carnivore_race{uuid.uuid4().hex[:6]}"
    adopted = f"carnivore_adopted{uuid.uuid4().hex[:6]}"
    state = bridge_config / "state"
    session_uuid = seed_row(state, tmux_test_socket, name, OLD_EPOCH, lifecycle_source="closed_by_user")
    capture_commands(monkeypatch, run_instead="sh -c 'sleep 45'")
    with patch.object(SessionManager, "_load_session_metadata", return_value=None):
        mgr = SessionManager()
    cleared: list = []
    monkeypatch.setattr(recreate_action, "_clear_conversation", lambda row_id: cleared.append(row_id))
    real_create = mgr.create_session
    saved: list = []
    quiet: list = []
    monkeypatch.setattr(mgr, "_save_session_metadata", lambda session: saved.append(session))
    mgr._attention_watcher = type("W", (), {"begin_startup_quiet": lambda self, sid: quiet.append(sid)})()

    async def racing_create(**kwargs):
        epoch = pane(tmux_test_socket, adopted, "sh -c 'sleep 60'", dead=False)
        with closing(connect(db_path_for(state), create=False)) as conn:
            conn.execute("UPDATE sessions SET tmux_name = ?, tmux_created_epoch = ?, lifecycle = 'running' "
                         "WHERE session_uuid = ?", (adopted, epoch, session_uuid))
            conn.commit()
        return await real_create(**kwargs)

    monkeypatch.setattr(mgr, "create_session", racing_create)
    try:
        answer = await recreate_action.recreate_by_uuid(session_uuid, "cld", get_manager=lambda: mgr, fresh=True)
        names = _sessions(tmux_test_socket)
        owned, registered = set(mgr._owned.names), dict(mgr._registry.sessions)
        with closing(connect(db_path_for(state), create=False)) as conn:
            rows = [dict(r) for r in conn.execute("SELECT tmux_name, lifecycle FROM sessions")]
    finally:
        for target in (name, adopted, f"{name}-2"):
            if target in _sessions(tmux_test_socket):
                tmux(tmux_test_socket, "kill-session", "-t", f"={target}")
    assert answer.status == "refused", answer.detail
    assert name not in names, "the recreate's own pane was left running"
    assert adopted in names, "the adopted pane was stopped"
    assert cleared == [], "the conversation of a row the recreate does not hold was cleared"
    assert name not in owned, "the refused create left its name in the owned set"
    assert registered == {} and saved == [] and quiet == [], "a refused create left registered, saved or quiet state behind"
    assert rows == [{"tmux_name": adopted, "lifecycle": "running"}], rows
