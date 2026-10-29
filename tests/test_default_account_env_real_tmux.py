
from __future__ import annotations

import asyncio
import subprocess
import time
import uuid
from pathlib import Path

import pytest

from src.core.tmux_backend import TmuxBackend
from src.core.tmux_command_batch import environment_commands
from tests.socket_guard import TEST_SOCKET_NAME

VAR = "CLAUDE_CONFIG_DIR"
BOGUS = "/nonexistent/stale-profile"


def _tmux(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["tmux", "-L", TEST_SOCKET_NAME, *args], capture_output=True, text=True)


def _wait_for(path: Path) -> str:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if path.exists() and path.stat().st_size:
            time.sleep(0.1)
            return path.read_text()
        time.sleep(0.05)
    return ""


@pytest.fixture()
def stale_server():
    keeper = f"acsw_keep_{uuid.uuid4().hex[:6]}"
    assert _tmux("new-session", "-d", "-s", keeper, "sleep 120").returncode == 0
    assert _tmux("set-environment", "-g", VAR, BOGUS).returncode == 0
    assert BOGUS in _tmux("show-environment", "-g", VAR).stdout
    yield
    _tmux("kill-session", "-t", f"={keeper}")


def _backend(tmp_path: Path) -> TmuxBackend:
    return TmuxBackend(
        session_id="acsw",
        working_dir=tmp_path,
        on_output=None,
        socket_name=TEST_SOCKET_NAME,
        session_name=f"acsw_{uuid.uuid4().hex[:6]}",
    )


def test_a_new_default_pane_does_not_see_the_stale_global_value(stale_server, tmp_path):
    out = tmp_path / "env.txt"
    backend = _backend(tmp_path)
    try:
        asyncio.run(backend.start(command=f"env > {out}; sleep 30", env={VAR: None}))
        body = _wait_for(out)
        assert "PATH=" in body, "the pane wrote nothing, so this proved nothing"
        assert VAR not in body
    finally:
        _tmux("kill-session", "-t", f"={backend.tmux_session}")


def test_a_managed_pane_still_gets_its_profile(stale_server, tmp_path):
    out = tmp_path / "env.txt"
    backend = _backend(tmp_path)
    try:
        asyncio.run(backend.start(command=f"env > {out}; sleep 30", env={VAR: "/p/work"}))
        assert f"{VAR}=/p/work" in _wait_for(out)
    finally:
        _tmux("kill-session", "-t", f"={backend.tmux_session}")


def test_a_restart_onto_the_default_does_not_see_the_stale_global_value(stale_server, tmp_path):
    name = f"acsw_{uuid.uuid4().hex[:6]}"
    out = tmp_path / "env.txt"
    assert _tmux("new-session", "-d", "-s", name, "-e", f"{VAR}=/p/work", "sleep 60").returncode == 0
    try:
        for command in environment_commands(f"={name}", {VAR: None}):
            assert _tmux(*command).returncode == 0
        _tmux("respawn-pane", "-k", "-t", f"={name}:", f"env > {out}; sleep 30")
        body = _wait_for(out)
        assert "PATH=" in body, "the pane wrote nothing, so this proved nothing"
        assert VAR not in body
    finally:
        _tmux("kill-session", "-t", f"={name}")
