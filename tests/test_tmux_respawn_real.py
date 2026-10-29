
from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

import pytest

from src.core.session_respawn import (
    RESPAWN_AGENT,
    RESPAWN_CANNOT_DETERMINE,
    RESPAWN_NOT_DEAD,
    RESPAWN_SHELL,
    resolve_respawn_plan,
)
from tests.socket_guard import derive_test_socket

pytestmark = pytest.mark.skipif(
    shutil.which("tmux") is None, reason="real tmux binary not available"
)

PANE_FMT = "#{pane_dead}|#{pane_dead_status}|#{pane_id}|#{pane_start_command}"


def _tmux(socket: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["tmux", "-L", socket, *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )


def _pane_fields(socket: str, name: str):
    proc = _tmux(socket, "list-panes", "-t", name, "-F", PANE_FMT)
    if proc.returncode != 0 or not proc.stdout.strip():
        return False, ("", "", "", "")
    parts = proc.stdout.splitlines()[0].split("|")
    while len(parts) < 4:
        parts.append("")
    return True, tuple(parts[:4])


def _session_created(socket: str, name: str) -> str:
    proc = _tmux(
        socket, "display-message", "-p", "-t", name, "#{session_created}|#{session_id}"
    )
    return proc.stdout.strip()


def _wait_dead(socket: str, name: str, timeout: float = 6.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        ok, fields = _pane_fields(socket, name)
        if ok and fields[0] == "1":
            return True
        time.sleep(0.1)
    return False


@pytest.fixture()
def socket(request) -> str:
    name = derive_test_socket(f"respawn_{request.node.name[:20]}")
    _tmux(name, "new-session", "-d", "-s", "keeper", "-x", "80", "-y", "24")
    _tmux(name, "set-option", "-wg", "remain-on-exit", "on")
    yield name
    subprocess.run(
        ["tmux", "-L", name, "kill-server"], capture_output=True, check=False
    )




@pytest.mark.parametrize(
    "label,inner",
    [
        ("clean_exit", 'sh -c "echo ran_clean; exit 0"'),
        ("crash", 'sh -c "echo ran_crash; exit 42"'),
    ],
)
def test_clean_exit_and_crash_both_land_in_the_same_dead_state(socket, label, inner):
    _tmux(socket, "new-session", "-d", "-s", label, "-x", "80", "-y", "24", inner)
    _tmux(socket, "set-option", "-t", label, "remain-on-exit", "on")
    assert _wait_dead(socket, label), f"{label} pane never reported dead"

    ok, (dead, status, _pane, start) = _pane_fields(socket, label)
    assert ok
    assert dead == "1"
    assert start.strip(), "tmux must record the start command for a dead pane"
    if label == "crash":
        assert status == "42"


def test_double_ctrl_c_lands_in_the_same_dead_state(socket):
    _tmux(
        socket,
        "new-session", "-d", "-s", "ctrlc", "-x", "80", "-y", "24",
        'sh -c "echo ran_sigint; sleep 300"',
    )
    _tmux(socket, "set-option", "-t", "ctrlc", "remain-on-exit", "on")
    time.sleep(0.6)
    _tmux(socket, "send-keys", "-t", "ctrlc", "C-c")
    time.sleep(0.3)
    _tmux(socket, "send-keys", "-t", "ctrlc", "C-c")

    assert _wait_dead(socket, "ctrlc"), "double Ctrl-C did not leave a dead pane"
    ok, (dead, _status, _pane, start) = _pane_fields(socket, "ctrlc")
    assert ok and dead == "1"
    assert start.strip()

    plan = resolve_respawn_plan(
        probe_ok=True, pane_dead=dead, pane_start_command=start, agent_command=None
    )
    assert plan.actionable is True




def test_respawn_revives_the_corpse_and_keeps_the_session_identity(socket, tmp_path):
    name = "revive"
    _tmux(
        socket,
        "new-session", "-d", "-s", name, "-c", str(tmp_path), "-x", "80", "-y", "24",
        'sh -c "echo MARKER_BEFORE_DEATH; exit 7"',
    )
    _tmux(socket, "set-option", "-t", name, "remain-on-exit", "on")
    assert _wait_dead(socket, name)

    identity_before = _session_created(socket, name)
    ok, (dead, _status, pane_before, start) = _pane_fields(socket, name)
    assert ok and dead == "1"

    plan = resolve_respawn_plan(
        probe_ok=True,
        pane_dead=dead,
        pane_start_command=start,
        agent_command='sh -c "echo MARKER_AFTER_RESPAWN; sleep 60"',
    )
    assert plan.kind == RESPAWN_AGENT

    proc = _tmux(socket, "respawn-pane", "-t", name, plan.command)
    assert proc.returncode == 0, proc.stderr

    deadline = time.monotonic() + 6
    fields = None
    while time.monotonic() < deadline:
        ok, fields = _pane_fields(socket, name)
        if ok and fields[0] == "0":
            break
        time.sleep(0.1)
    assert fields is not None and fields[0] == "0", "pane did not come back to life"

    assert _session_created(socket, name) == identity_before
    assert fields[2] == pane_before, "pane id changed; this would not be the same pane"

    cap = _tmux(socket, "capture-pane", "-t", name, "-p", "-S", "-50").stdout
    assert "MARKER_BEFORE_DEATH" in cap
    assert "MARKER_AFTER_RESPAWN" in cap


def test_respawn_without_dash_k_refuses_to_kill_a_live_agent(socket, tmp_path):
    name = "alive"
    _tmux(
        socket,
        "new-session", "-d", "-s", name, "-c", str(tmp_path), "-x", "80", "-y", "24",
        'sh -c "echo STILL_RUNNING; sleep 120"',
    )
    _tmux(socket, "set-option", "-t", name, "remain-on-exit", "on")
    time.sleep(0.8)

    ok, (dead, _s, _p, start) = _pane_fields(socket, name)
    assert ok and dead == "0"

    plan = resolve_respawn_plan(
        probe_ok=True, pane_dead=dead, pane_start_command=start, agent_command="x"
    )
    assert plan.kind == RESPAWN_NOT_DEAD

    proc = _tmux(socket, "respawn-pane", "-t", name)
    assert proc.returncode != 0
    assert "active" in (proc.stderr + proc.stdout).lower()

    ok, (dead_after, _s2, _p2, _c2) = _pane_fields(socket, name)
    assert ok and dead_after == "0", "a live pane must survive a stray respawn"


@pytest.mark.asyncio
async def test_pipe_pane_streaming_survives_a_respawn(socket, tmp_path, monkeypatch):
    from src.config import settings
    from src.core.tmux_backend import TmuxBackend

    monkeypatch.setattr(settings, "log_directory", str(tmp_path))
    name = "piped"
    _tmux(
        socket,
        "new-session", "-d", "-s", name, "-c", str(tmp_path), "-x", "80", "-y", "24",
        'sh -c "echo BEFORE; sleep 1; exit 1"',
    )
    _tmux(socket, "set-option", "-t", name, "remain-on-exit", "on")
    backend = TmuxBackend.for_external(
        session_name=name, working_dir=tmp_path, on_output=None, socket_name=socket)
    await backend.ensure_pipe_pane()
    assert _wait_dead(socket, name)

    result = await backend.respawn(agent_command='sh -c "echo AFTER_PIPE; sleep 30"')
    assert result.ok, result.detail

    log = Path(backend._pipe_write_path())
    deadline = time.monotonic() + 6
    while time.monotonic() < deadline:
        if "AFTER_PIPE" in log.read_text(errors="replace"):
            break
        time.sleep(0.1)
    assert "AFTER_PIPE" in log.read_text(errors="replace"), (
        "the respawned pane's first line never reached the pipe; the terminal would go blank"
    )
    assert _tmux(socket, "display-message", "-p", "-t", f"={name}:", "#{pane_pipe}").stdout.strip() == "1"


def test_remain_on_exit_still_set_after_a_respawn(socket, tmp_path):
    name = "again"
    _tmux(
        socket,
        "new-session", "-d", "-s", name, "-c", str(tmp_path), "-x", "80", "-y", "24",
        'sh -c "exit 0"',
    )
    _tmux(socket, "set-option", "-t", name, "remain-on-exit", "on")
    assert _wait_dead(socket, name)
    _tmux(socket, "respawn-pane", "-t", name, 'sh -c "echo up; sleep 30"')
    time.sleep(0.8)

    opt = _tmux(socket, "show-options", "-t", name, "remain-on-exit").stdout
    assert "on" in opt, f"remain-on-exit was lost by the respawn: {opt!r}"


def test_bare_shell_pane_reports_no_start_command(socket):
    _tmux(socket, "new-session", "-d", "-s", "bare", "-x", "80", "-y", "24")
    time.sleep(0.5)
    ok, (_d, _s, _p, start) = _pane_fields(socket, "bare")
    assert ok
    assert start.strip() == "", f"expected no start command, got {start!r}"

    plan = resolve_respawn_plan(
        probe_ok=True, pane_dead="1", pane_start_command=start, agent_command="cld"
    )
    assert plan.kind == RESPAWN_SHELL


def test_missing_session_probe_is_cannot_determine(socket):
    ok, _fields = _pane_fields(socket, "no-such-session-here")
    assert ok is False
    plan = resolve_respawn_plan(
        probe_ok=ok, pane_dead=None, pane_start_command=None, agent_command="cld"
    )
    assert plan.kind == RESPAWN_CANNOT_DETERMINE
