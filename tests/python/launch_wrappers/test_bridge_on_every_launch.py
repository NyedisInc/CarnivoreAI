
from __future__ import annotations

import ast
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.config import settings
from src.core.session_agent_choice import CHOICE_ACCEPTED, validate_agent_choice
from src.core.session_restart import resume_arguments
from tests.helpers.bridge_launch import (
    UUID, argv_of, assert_bridge, capture_commands, pane, seed_row, tmux, unchecked_transcripts, use_bridge_config,
)

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture()
def bridge_config(tmp_path, monkeypatch):
    yield use_bridge_config(tmp_path, monkeypatch)
    settings._auth_config_cache = None


@pytest.mark.asyncio
async def test_create_carries_the_bridge(bridge_config, monkeypatch, tmux_test_socket):
    from src.core.session_manager import SessionManager

    seen = capture_commands(monkeypatch)
    work = bridge_config / "wd"
    work.mkdir()
    token = uuid.uuid4().hex[:8]
    mgr = SessionManager()
    session = None
    try:
        session = await mgr.create_session(
            session_id=f"ses_{token}", working_dir=str(work), auto_start_claude=True,
            agent_type="keyc", project_name=f"br{token}", agent_extra_args=resume_arguments(UUID, family="claude"),
        )
    finally:
        if session is not None:
            await mgr.destroy_session(session.id)
    assert len(seen) == 1
    assert_bridge(argv_of(seen[0][1], bridge_config))


def test_wake_and_recreate_report_the_command_with_the_bridge(bridge_config):
    choice = validate_agent_choice(settings, "keyc", extra_args=resume_arguments(UUID, family="claude"))
    assert choice.verdict == CHOICE_ACCEPTED, choice.detail
    assert_bridge(argv_of(choice.command, bridge_config))


@pytest.mark.asyncio
async def test_restart_with_a_picked_wrapper_carries_the_bridge(bridge_config, monkeypatch, tmux_test_socket):
    from unittest.mock import patch

    from src.core.session_manager import SessionManager

    name = f"brpick{uuid.uuid4().hex[:6]}"
    epoch = pane(tmux_test_socket, name, "sh -c 'sleep 0.3; exit 0'", dead=True)
    seed_row(bridge_config / "state", tmux_test_socket, name, epoch)
    unchecked_transcripts(monkeypatch)
    seen = capture_commands(monkeypatch)
    with patch.object(SessionManager, "_load_session_metadata", return_value=None):
        mgr = SessionManager()
    try:
        result = await mgr.respawn_session(name, socket_name=tmux_test_socket, agent_type="keyc")
    finally:
        tmux(tmux_test_socket, "kill-session", "-t", f"={name}")
    assert result["ok"] is True and result["chosen"] is True, result["detail"]
    assert result["killed_live_pane"] is False
    picked = [cmd for agent, cmd in seen if agent == "keyc"]
    assert picked, seen
    for command in picked:
        assert_bridge(argv_of(command, bridge_config))


@pytest.mark.asyncio
async def test_the_bridge_migration_restart_carries_the_bridge(bridge_config, monkeypatch, tmux_test_socket):
    from unittest.mock import patch

    from src.core.mcp_bridge.migration import migrator
    from src.core.session_manager import SessionManager

    name = f"brmig{uuid.uuid4().hex[:6]}"
    epoch = pane(tmux_test_socket, name, "sh -c 'sleep 30'", dead=False)
    seed_row(bridge_config / "state", tmux_test_socket, name, epoch)
    unchecked_transcripts(monkeypatch)
    seen = capture_commands(monkeypatch, run_instead=f"sh -c 'sleep 45' _ --resume {UUID}")
    with patch.object(SessionManager, "_load_session_metadata", return_value=None):
        mgr = SessionManager()

    class _OnTestSocket:

        async def respawn_session(self, target, **kwargs):
            return await mgr.respawn_session(target, socket_name=tmux_test_socket, **kwargs)

    mig = migrator.BridgeMigrator(_OnTestSocket(), enabled=lambda: True, evidence=SimpleNamespace())

    async def _no_recheck(_info):
        return None

    monkeypatch.setattr(mig, "_recheck", _no_recheck)
    entry = migrator.Entry(session_id="ses_mig", tmux_session=name)
    try:
        assert await mig._restart(SimpleNamespace(tmux_session=name), entry) == 1
    finally:
        tmux(tmux_test_socket, "kill-session", "-t", f"={name}")
    assert entry.last_outcome == "restarted", entry
    assert seen, "the migrator's restart rendered no command"
    for _agent, command in seen:
        assert_bridge(argv_of(command, bridge_config))


def _calls_outside_settings() -> list:
    hits = []
    for path in sorted((ROOT / "src").rglob("*.py")):
        if path == ROOT / "src" / "config" / "settings.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name == "get_agent_command" or any(k.arg == "pane_launch" for k in node.keywords):
                hits.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    return hits


def test_no_second_pane_launch_call_site():
    assert _calls_outside_settings() == []
    own = ast.parse((ROOT / "src" / "config" / "settings.py").read_text(encoding="utf-8"))
    assert any(isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "get_agent_command" for n in ast.walk(own))
