
from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Iterator

import pytest

from tests.socket_guard import (
    FORBIDDEN_SOCKET_NAME,
    TEST_SOCKET_NAME,
    TEST_SOCKET_PREFIX,
    TmuxSocketGuardError,
    classify_tmux_argv,
    derive_test_socket,
    guard_is_installed,
    sweep_stale_test_sockets,
)
from scripts.perf.tmux_socket_file import kill_server_and_unlink, tmux_socket_path

TESTS_DIR = Path(__file__).resolve().parent


def test_resolved_socket_is_never_the_production_socket() -> None:
    assert TEST_SOCKET_NAME != FORBIDDEN_SOCKET_NAME
    assert TEST_SOCKET_NAME.startswith(TEST_SOCKET_PREFIX), (
        f"socket {TEST_SOCKET_NAME!r} must carry the throwaway prefix "
        f"{TEST_SOCKET_PREFIX!r} so it is identifiable as disposable"
    )


def test_guard_is_installed_for_every_test() -> None:
    assert guard_is_installed(), (
        "the subprocess guard is not installed, so nothing prevents a test "
        "from reaching the production socket"
    )


@pytest.mark.parametrize(
    "argv,expected",
    [
        (["tmux", "-L", FORBIDDEN_SOCKET_NAME, "ls"], "unsafe"),
        (["tmux", "-L", "someone-elses-socket", "ls"], "unsafe"),
        (["/opt/homebrew/bin/tmux", "-L", FORBIDDEN_SOCKET_NAME, "ls"], "unsafe"),
        (["tmux", "ls"], "unsafe"),
        (["tmux", "new-session", "-d", "-s", "x"], "unsafe"),
        (["tmux", "-L", TEST_SOCKET_NAME, "ls"], "safe"),
        (["tmux", f"-L{TEST_SOCKET_NAME}", "ls"], "safe"),
        (["git", "status"], "not_tmux"),
        (["tmux", "-L"], "undetermined"),
        (["tmux", "-S"], "undetermined"),
        ("tmux -L cloude ls", "undetermined"),
        (["sh", "-c", "tmux -L cloude ls"], "undetermined"),
    ],
)
def test_classify_tmux_argv_verdicts(argv: object, expected: str) -> None:
    verdict, _name, detail = classify_tmux_argv(argv)
    assert verdict == expected, f"{argv!r} classified {verdict!r}: {detail}"
    assert detail, "every verdict must carry a reason"


def test_bare_tmux_with_no_socket_flag_is_not_treated_as_safe() -> None:
    verdict, name, _detail = classify_tmux_argv(["tmux", "kill-server"])
    assert verdict == "unsafe"
    assert name == "default"


def test_undetermined_is_a_failure_not_a_pass() -> None:
    for cmd in ("tmux -L cloude ls", ["tmux", "-L"], ["sh", "-c", "tmux ls"]):
        verdict, _name, _detail = classify_tmux_argv(cmd)
        assert verdict != "safe", f"{cmd!r} must not be classified safe"
        assert verdict != "not_tmux", f"{cmd!r} must not be waved through"


def test_guard_blocks_a_real_subprocess_call_to_the_production_socket() -> None:
    with pytest.raises(TmuxSocketGuardError) as excinfo:
        subprocess.run(
            ["tmux", "-L", FORBIDDEN_SOCKET_NAME, "list-sessions"],
            capture_output=True,
        )
    assert FORBIDDEN_SOCKET_NAME in str(excinfo.value)


def test_guard_blocks_popen_and_check_output_too() -> None:
    with pytest.raises(TmuxSocketGuardError):
        subprocess.Popen(["tmux", "-L", FORBIDDEN_SOCKET_NAME, "ls"])
    with pytest.raises(TmuxSocketGuardError):
        subprocess.check_output(["tmux", "-L", FORBIDDEN_SOCKET_NAME, "ls"])


@pytest.mark.asyncio
async def test_guard_blocks_asyncio_create_subprocess_exec() -> None:
    import asyncio

    with pytest.raises(TmuxSocketGuardError):
        await asyncio.create_subprocess_exec(
            "tmux", "-L", FORBIDDEN_SOCKET_NAME, "ls"
        )


def test_guard_permits_the_designated_test_socket() -> None:
    proc = subprocess.run(
        ["tmux", "-L", TEST_SOCKET_NAME, "list-sessions"],
        capture_output=True,
    )
    assert proc.returncode in (0, 1)


_FORBIDDEN_EXEC_PATTERN = re.compile(
    r'["\']-L["\']\s*,\s*["\']' + re.escape(FORBIDDEN_SOCKET_NAME) + r'["\']'
)
_FORBIDDEN_ASSIGN_PATTERN = re.compile(
    r'tmux_socket_name\s*=\s*["\']' + re.escape(FORBIDDEN_SOCKET_NAME) + r'["\']'
)


def test_no_test_file_hardcodes_the_production_socket() -> None:
    offenders: list[str] = []
    for path in sorted(TESTS_DIR.glob("test_*.py")):
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if path.name == "test_tmux_socket_isolation.py":
                continue
            if _FORBIDDEN_EXEC_PATTERN.search(line) or _FORBIDDEN_ASSIGN_PATTERN.search(line):
                offenders.append(f"{path.name}:{lineno}: {line.strip()}")

    assert not offenders, (
        "test files hardcode the production tmux socket "
        f"{FORBIDDEN_SOCKET_NAME!r}. Use the tmux_test_socket fixture or "
        "tests.socket_guard.TEST_SOCKET_NAME instead:\n  "
        + "\n  ".join(offenders)
    )




@pytest.fixture
def private_tmux_tmpdir(monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    root = tempfile.mkdtemp(dir="/tmp", prefix="tsk")
    monkeypatch.setenv("TMUX_TMPDIR", root)
    sock_dir = Path(root) / f"tmux-{os.getuid()}"
    sock_dir.mkdir(mode=0o700)
    yield sock_dir
    shutil.rmtree(root, ignore_errors=True)


def _start_server(name: str) -> None:
    subprocess.run(
        ["tmux", "-L", name, "-f", "/dev/null", "new-session", "-d", "sleep 300"],
        check=True, capture_output=True, timeout=10,
    )


def _dead_socket_file(path: Path, age_s: float) -> None:
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.bind(str(path))
    sock.close()
    stamp = time.time() - age_s
    os.utime(path, (stamp, stamp))


def test_kill_server_and_unlink_leaves_no_socket_file(private_tmux_tmpdir: Path) -> None:
    name = derive_test_socket("unlink")
    path = tmux_socket_path(name)
    assert path.parent == private_tmux_tmpdir

    _start_server(name)
    assert path.exists()
    subprocess.run(["tmux", "-L", name, "kill-server"], capture_output=True, timeout=10)
    assert path.exists(), "tmux now removes its own file; this helper may be moot"

    name = derive_test_socket("unlink")
    path = tmux_socket_path(name)
    _start_server(name)
    assert path.exists()
    kill_server_and_unlink(name)
    assert not path.exists()
    kill_server_and_unlink(name)


def test_sweep_removes_only_old_dead_test_files(private_tmux_tmpdir: Path) -> None:
    old = 2 * 3600.0
    old_test = private_tmux_tmpdir / f"{TEST_SOCKET_PREFIX}999_dead"
    old_perf = private_tmux_tmpdir / "cloudeperf_deadbeef"
    fresh_test = private_tmux_tmpdir / f"{TEST_SOCKET_PREFIX}999_fresh"
    other = private_tmux_tmpdir / "someone_else"
    default = private_tmux_tmpdir / "default"
    for path in (old_test, old_perf, other, default):
        _dead_socket_file(path, old)
    _dead_socket_file(fresh_test, 0)

    live = derive_test_socket("sweeplive")
    _start_server(live)
    live_path = tmux_socket_path(live)
    os.utime(live_path, (time.time() - old, time.time() - old))
    try:
        assert sweep_stale_test_sockets() == (2, 0)
        assert not old_test.exists() and not old_perf.exists()
        assert fresh_test.exists() and other.exists() and default.exists()
        assert live_path.exists(), "a young live server must be left alone"
        listing = subprocess.run(
            ["tmux", "-L", live, "list-sessions"], capture_output=True, timeout=10
        )
        assert listing.returncode == 0, "the sweep killed a young live server"

        removed, killed = sweep_stale_test_sockets(now=time.time() + 13 * 3600)
        assert killed == 1 and not live_path.exists()
        assert removed == 1 and not fresh_test.exists()
        assert other.exists() and default.exists()
    finally:
        kill_server_and_unlink(live)
