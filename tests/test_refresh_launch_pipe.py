
from __future__ import annotations

import os
import re
import signal
import subprocess
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
REFRESH_SCRIPT = REPO_ROOT / "scripts" / "refresh-local-install.sh"
DEPLOY_MINI_SCRIPT = REPO_ROOT / "scripts" / "deploy-mini.sh"

PIPE_TIMEOUT = 5.0

OLD_BAD_LAUNCH_TEMPLATE = '( cd "{macos_dir}" && nohup npm start > {logfile} 2>&1 & disown )'


def _extract_launch_line(script_text: str) -> str:
    match = re.search(r'^\s*\(\s*cd\s+"\$REPO_ROOT/macOS".*disown\s*$', script_text, re.MULTILINE)
    assert match, "could not find the npm start relaunch line in refresh-local-install.sh"
    return match.group(0).strip()


def _make_npm_stub(bin_dir: Path, pidfile: Path) -> None:
    stub = bin_dir / "npm"
    stub.write_text('#!/bin/bash\necho $$ > "{pidfile}"\nsleep 30\n'.format(pidfile=pidfile))
    stub.chmod(0o755)


def _run_piped(bash_command: str, env: dict) -> tuple[bool, float]:
    proc = subprocess.Popen(
        ["bash", "-c", bash_command],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
    )
    start = time.monotonic()
    try:
        proc.communicate(timeout=PIPE_TIMEOUT)
        return True, time.monotonic() - start
    except subprocess.TimeoutExpired:
        return False, time.monotonic() - start
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


def _read_pid(pidfile: Path, deadline: float = 5.0) -> int:
    end = time.monotonic() + deadline
    while time.monotonic() < end:
        if pidfile.exists():
            text = pidfile.read_text().strip()
            if text:
                return int(text)
        time.sleep(0.05)
    raise AssertionError(f"stub never wrote its pid to {pidfile}")


def _is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def _kill_pid(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


@pytest.fixture()
def stub_env(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    macos_dir = tmp_path / "macOS"
    macos_dir.mkdir()
    pidfile = tmp_path / "npm.pid"
    _make_npm_stub(bin_dir, pidfile)
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    return {"macos_dir": macos_dir, "pidfile": pidfile, "env": env, "tmp_path": tmp_path}


def test_old_shape_hangs_the_pipe_while_stub_is_alive(stub_env):
    logfile = stub_env["tmp_path"] / "old.log"
    cmd = OLD_BAD_LAUNCH_TEMPLATE.format(macos_dir=stub_env["macos_dir"], logfile=logfile)

    closed, elapsed = _run_piped(cmd, stub_env["env"])
    pid = _read_pid(stub_env["pidfile"])
    try:
        assert _is_alive(pid), "stub should still be running (sleeping) when we check"
        assert not closed, (
            f"expected the pipe to still be open after {elapsed:.1f}s with the "
            "pre-fix shape; it closed instead, so this negative control no "
            "longer proves anything"
        )
    finally:
        _kill_pid(pid)


def test_current_launch_line_closes_the_pipe_promptly(stub_env):
    launch_line = _extract_launch_line(REFRESH_SCRIPT.read_text())
    logfile = stub_env["tmp_path"] / "new.log"

    cmd = launch_line.replace("$REPO_ROOT/macOS", str(stub_env["macos_dir"])).replace(
        "/tmp/cloude-menubar-refresh.log", str(logfile)
    )

    closed, elapsed = _run_piped(cmd, stub_env["env"])
    pid = _read_pid(stub_env["pidfile"])
    try:
        assert closed, (
            f"the pipe was still open after {elapsed:.1f}s; the current relaunch "
            "line in refresh-local-install.sh regressed to backgrounding a "
            "process that inherits the caller's fds"
        )
        assert elapsed < PIPE_TIMEOUT
        assert _is_alive(pid), "the launched stub should still be running"
    finally:
        _kill_pid(pid)


def test_deploy_mini_relaunch_line_has_no_bare_and_list_background():
    text = DEPLOY_MINI_SCRIPT.read_text()
    match = re.search(r"pkill -f 'CloudeCode-v1\.1.*?sleep 1", text)
    assert match, "could not find the v1.1 remote relaunch line in deploy-mini.sh"
    line = match.group(0)
    assert "exec nohup" in line
    assert "</dev/null" in line


def _launch_then_kill_group(launch_cmd: str, pidfile: Path, env: dict) -> int:
    shell = subprocess.Popen(
        ["bash", "-c", launch_cmd + "\nsleep 30"],
        env=env,
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    pid = _read_pid(pidfile)
    time.sleep(0.3)
    os.killpg(shell.pid, signal.SIGKILL)
    shell.wait(timeout=5)
    time.sleep(0.5)
    return pid


def _pgid_sess(pid: int) -> tuple[int, str]:
    out = subprocess.run(
        ["ps", "-o", "pgid=,sess=", "-p", str(pid)], capture_output=True, text=True
    ).stdout.split()
    return int(out[0]), out[1]


def test_old_shape_dies_with_callers_process_group_kill(stub_env):
    logfile = stub_env["tmp_path"] / "old.log"
    cmd = OLD_BAD_LAUNCH_TEMPLATE.format(macos_dir=stub_env["macos_dir"], logfile=logfile)
    pid = _launch_then_kill_group(cmd, stub_env["pidfile"], stub_env["env"])
    try:
        assert not _is_alive(pid), "old shape should die with its caller's process group"
    finally:
        _kill_pid(pid)


def test_current_launch_line_survives_callers_process_group_kill(stub_env):
    launch_line = _extract_launch_line(REFRESH_SCRIPT.read_text())
    logfile = stub_env["tmp_path"] / "new.log"
    cmd = launch_line.replace("$REPO_ROOT/macOS", str(stub_env["macos_dir"])).replace(
        "/tmp/cloude-menubar-refresh.log", str(logfile)
    )
    pid = _launch_then_kill_group(cmd, stub_env["pidfile"], stub_env["env"])
    try:
        assert _is_alive(pid), "launched app died with the caller's process group"
        pgid, _sess = _pgid_sess(pid)
        assert pgid == pid, "launched app is not the leader of its own process group/session"
    finally:
        _kill_pid(pid)
