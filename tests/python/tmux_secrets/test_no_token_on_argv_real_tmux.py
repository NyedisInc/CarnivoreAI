
from __future__ import annotations

import asyncio
import os
import secrets
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_argv_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_argv_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core.tmux_transport import local as local_transport
from src.core.tmux_backend import TmuxBackend
from src.core.tmux_discovery import tmux_argv_prefix
from tests.socket_guard import derive_test_socket

pytestmark = pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux not on PATH")

_SEP = "\x1f"


def _tmux(socket: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["tmux", "-L", socket, *args], capture_output=True, text=True,
                          check=False, timeout=20)


def _wait_for_text(path: Path, timeout: float = 10.0) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists() and path.read_text().strip():
            return path.read_text().strip()
        time.sleep(0.05)
    return ""


def _argv_of(pid: str) -> str:
    return subprocess.run(["ps", "-ww", "-o", "command=", "-p", pid], capture_output=True,
                          text=True, check=False).stdout


@pytest.fixture()
def rig(tmp_path, monkeypatch):
    socket = derive_test_socket(f"argv_{uuid.uuid4().hex[:6]}")
    real = tmux_argv_prefix(socket)[0]
    log = tmp_path / "argv.log"
    shim = tmp_path / "tmux-shim"
    shim.write_text(
        "#!/bin/sh\n"
        f"( for a in \"$@\"; do printf '%s{_SEP}' \"$a\"; done; printf '\\n' ) >> '{log}'\n"
        f"exec '{real}' \"$@\"\n"
    )
    shim.chmod(0o700)
    monkeypatch.setattr(local_transport, "tmux_argv_prefix",
                        lambda sock: [str(shim), "-L", sock])
    _tmux(socket, "kill-server")
    assert _tmux(socket, "list-sessions").returncode != 0, "socket is not cold"
    try:
        yield socket, log
    finally:
        _tmux(socket, "kill-server")


def _probe(tmp_path: Path, marker: Path) -> str:
    script = tmp_path / f"probe_{marker.stem}.sh"
    script.write_text(f'#!/bin/sh\nprintf %s "$CLOUDECODE_HOOK_TOKEN" > \'{marker}\'\nsleep 60\n')
    return f"sh '{script}'"


def _require(ok: bool, message: str) -> None:
    if not ok:
        raise AssertionError(message)


def _assert_off_every_argv(token: str, log: Path, socket: str, name: str) -> None:
    recorded = log.read_text() if log.exists() else ""
    assert recorded.count("\n") >= 1, "no tmux invocation was recorded; the check saw nothing"
    _require(token not in recorded, "a tmux client was run with the token on its command line")
    server_pid = _tmux(socket, "display-message", "-p", "#{pid}").stdout.strip()
    pane_pid = _tmux(socket, "list-panes", "-t", f"={name}", "-F", "#{pane_pid}").stdout.strip()
    assert server_pid and pane_pid, "could not read the server or pane pid"
    server_argv = _argv_of(server_pid)
    assert "tmux" in server_argv, "ps could not read the server's argv; the check saw nothing"
    _require(token not in server_argv, "the tmux server's command line carries the token")
    _require(token not in _argv_of(pane_pid), "the pane's command line carries the token")


@pytest.mark.asyncio
async def test_create_and_restart_keep_the_token_off_every_command_line(rig, tmp_path):
    socket, log = rig
    name = f"carnivore_argv_{uuid.uuid4().hex[:6]}"
    born, restarted = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    first, second = tmp_path / "born.txt", tmp_path / "restarted.txt"
    backend = TmuxBackend(session_id=name, working_dir=tmp_path, on_output=None,
                          socket_name=socket, session_name=name)
    await backend.start(command=_probe(tmp_path, first), env={
        "CLOUDECODE_HOOK_TOKEN": born, "CARNIVORE_HOOK_TOKEN": born,
        "CLOUDECODE_SESSION_ID": "ses_argv"})
    try:
        _require(_wait_for_text(first) == born, "the pane did not inherit the token it was born with")
        _assert_off_every_argv(born, log, socket, name)
        _require(born not in _tmux(socket, "show-environment", "-g").stdout,
                 "the token seeded the server's global environment")

        result = await backend.respawn(
            chosen_agent_command=_probe(tmp_path, second), chosen_agent_type="probe",
            live_restart_confirmed=True,
            spawn_env={"CLOUDECODE_HOOK_TOKEN": restarted, "CARNIVORE_HOOK_TOKEN": restarted})
        assert result.ok, result.detail
        _require(_wait_for_text(second) == restarted, "the restarted pane did not inherit the new token")
        _assert_off_every_argv(restarted, log, socket, name)

        third = secrets.token_urlsafe(32)
        outcome = await backend.set_session_environment(
            f"={name}", {"CLOUDECODE_HOOK_TOKEN": third}, note="test_adopt_push")
        _require(outcome.failures == (), "the adopt/boot push failed")
        _require(f"CLOUDECODE_HOOK_TOKEN={third}" in _tmux(
            socket, "show-environment", "-t", f"={name}").stdout, "the adopt/boot push did not land")
        _require(third not in log.read_text(), "the adopt/boot push put the token on a command line")
    finally:
        await backend.stop()


@pytest.mark.asyncio
async def test_hostile_arguments_reach_tmux_verbatim_through_stdin(rig, tmp_path):
    socket, _ = rig
    name = f"carnivore_quote_{uuid.uuid4().hex[:6]}"
    nasty = "it's ; $HOME ~ {x} # \"q\" \\ tail"
    backend = TmuxBackend(session_id=name, working_dir=tmp_path, on_output=None,
                          socket_name=socket, session_name=name)
    await backend.start(command="sleep 60", env={"CC_NASTY": nasty})
    try:
        shown = _tmux(socket, "show-environment", "-t", f"={name}", "CC_NASTY").stdout
        assert shown.rstrip("\n") == f"CC_NASTY={nasty}"
        rc, _, _ = await backend._run_tmux_private("set-environment", "-t", f"={name}",
                                                   "CC_NASTY", "-x;y\nline2")
        assert rc == 0
        shown = _tmux(socket, "show-environment", "-t", f"={name}", "CC_NASTY").stdout
        assert shown == "CC_NASTY=-x;y\nline2\n"
        rc, _, err = await backend._run_tmux_private("set-environment", "-t", "=nosuch", "A", "1",
                                                     check=False)
        assert rc != 0 and err, "a failing command must still report failure through stdin"
    finally:
        await backend.stop()


def test_a_quoting_refusal_runs_nothing():
    from src.core.tmux_command_batch import run_on_stdin

    calls = []

    async def fake(*args, **kwargs):
        calls.append(args)
        return 0, b"", b""

    rc, _, err = asyncio.run(run_on_stdin(fake, "set-environment", "-t", "s", "A", "nul\0byte"))
    assert rc == 1 and b"\\x00" in err and calls == []
