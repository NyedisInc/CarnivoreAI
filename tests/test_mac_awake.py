
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import List, Optional

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_macawake_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_macawake_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core.auto_sleep.mac_awake import CAFFEINATE_PATH, MacAwakeGuard, reconcile_at_boot


class FakeProc:

    def __init__(self, pid: int, *, ignores_terminate: bool = False) -> None:
        self.pid = pid
        self._alive = True
        self.terminated = False
        self.killed = False
        self._ignores_terminate = ignores_terminate

    def poll(self) -> Optional[int]:
        return None if self._alive else 0

    def terminate(self) -> None:
        self.terminated = True
        if not self._ignores_terminate:
            self._alive = False

    def kill(self) -> None:
        self.killed = True
        self._alive = False

    def wait(self, timeout: Optional[float] = None) -> int:
        if self._alive:
            raise subprocess.TimeoutExpired(cmd="caffeinate", timeout=timeout or 0)
        return 0

    def die(self) -> None:
        self._alive = False


class FakeLauncher:

    def __init__(self, *, fail: bool = False) -> None:
        self.calls: List[List[str]] = []
        self._next_pid = 9000
        self.fail = fail

    def __call__(self, args: List[str]) -> FakeProc:
        self.calls.append(list(args))
        if self.fail:
            raise OSError("no such file or directory")
        self._next_pid += 1
        return FakeProc(self._next_pid)


def _guard(launcher: FakeLauncher, *, caffeinate_path: str = "/usr/bin/caffeinate") -> MacAwakeGuard:
    return MacAwakeGuard(server_pid=4242, launcher=launcher, caffeinate_path=caffeinate_path)


def test_reconcile_starts_on_the_first_positive_count(tmp_path: Path) -> None:
    launcher = FakeLauncher()
    guard = _guard(launcher)
    assert guard.active is False

    guard.reconcile(1)

    assert guard.active is True
    assert launcher.calls == [["/usr/bin/caffeinate", "-i", "-w", "4242"]]


def test_reconcile_is_idempotent_while_already_running(tmp_path: Path) -> None:
    launcher = FakeLauncher()
    guard = _guard(launcher)

    guard.reconcile(1)
    guard.reconcile(2)
    guard.reconcile(1)

    assert len(launcher.calls) == 1, "a second session going on must never start a second caffeinate"


def test_reconcile_stops_the_tracked_child_when_count_returns_to_zero(tmp_path: Path) -> None:
    launcher = FakeLauncher()
    guard = _guard(launcher)
    guard.reconcile(1)

    guard.reconcile(0)

    assert guard.active is False
    assert launcher.calls == [["/usr/bin/caffeinate", "-i", "-w", "4242"]]


def test_reconcile_zero_with_nothing_running_starts_nothing(tmp_path: Path) -> None:
    launcher = FakeLauncher()
    guard = _guard(launcher)

    guard.reconcile(0)

    assert guard.active is False
    assert launcher.calls == []


def test_a_child_that_died_on_its_own_is_noticed_and_replaced(tmp_path: Path) -> None:
    launcher = FakeLauncher()
    guard = _guard(launcher)
    guard.reconcile(1)

    guard._proc.die()  # type: ignore[attr-defined]

    assert guard.active is False, "a dead child must never read as active"

    guard.reconcile(1)

    assert len(launcher.calls) == 2, "reconcile must start a fresh child once the old one is gone"


def test_reconcile_never_raises_when_the_launcher_fails(tmp_path: Path) -> None:
    launcher = FakeLauncher(fail=True)
    guard = _guard(launcher)

    guard.reconcile(1)

    assert guard.active is False
    assert len(launcher.calls) == 1


def test_missing_caffeinate_binary_fails_soft(tmp_path: Path) -> None:
    launcher = FakeLauncher()
    missing_path = str(tmp_path / "no-such-caffeinate")
    guard = _guard(launcher, caffeinate_path=missing_path)

    guard.reconcile(1)

    assert guard.active is False
    assert launcher.calls == [], "a missing binary must never be exec'd"


def test_stop_kills_a_child_that_ignores_terminate(tmp_path: Path) -> None:
    launcher = FakeLauncher()
    guard = _guard(launcher)
    guard.reconcile(1)
    stubborn = FakeProc(guard._proc.pid, ignores_terminate=True)  # type: ignore[union-attr]
    guard._proc = stubborn  # type: ignore[attr-defined]

    guard.reconcile(0)

    assert stubborn.terminated is True
    assert stubborn.killed is True, "a child that outlives terminate() must be kill()ed, not abandoned"
    assert guard.active is False


def test_stop_with_nothing_tracked_is_a_no_op(tmp_path: Path) -> None:
    launcher = FakeLauncher()
    guard = _guard(launcher)

    guard.reconcile(0)

    assert guard.active is False
    assert launcher.calls == []


def test_concurrent_reconciles_never_start_two_children(tmp_path: Path) -> None:
    import threading as _threading

    launcher = FakeLauncher()
    guard = _guard(launcher)
    barrier = _threading.Barrier(2)

    def go() -> None:
        barrier.wait(timeout=2)
        guard.reconcile(1)

    threads = [_threading.Thread(target=go) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=2)

    assert len(launcher.calls) == 1, "the lock must serialize concurrent reconciles"
    assert guard.active is True


def test_reconcile_at_boot_starts_from_the_stored_keep_awake_list(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"auto_sleep": {"keep_awake": ["abc-123"]}}))
    launcher = FakeLauncher()
    guard = _guard(launcher)

    reconcile_at_boot(guard, config_path)

    assert guard.active is True


def test_reconcile_at_boot_with_no_keep_awake_starts_nothing(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"auto_sleep": {"keep_awake": []}}))
    launcher = FakeLauncher()
    guard = _guard(launcher)

    reconcile_at_boot(guard, config_path)

    assert guard.active is False
    assert launcher.calls == []


def test_reconcile_at_boot_with_no_config_file_fails_soft(tmp_path: Path) -> None:
    config_path = tmp_path / "does-not-exist.json"
    launcher = FakeLauncher()
    guard = _guard(launcher)

    reconcile_at_boot(guard, config_path)

    assert guard.active is False
    assert launcher.calls == []


@pytest.mark.skipif(
    sys.platform != "darwin" or not os.path.exists(CAFFEINATE_PATH),
    reason="real caffeinate boundary test only runs on macOS with the binary present",
)
def test_real_caffeinate_child_holds_and_releases_an_assertion() -> None:
    server_pid = os.getpid()
    guard = MacAwakeGuard(server_pid=server_pid)

    guard.reconcile(1)
    assert guard.active is True
    pid = guard._proc.pid  # type: ignore[union-attr]

    try:
        ps = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True)
        assert ps.returncode == 0, "the started caffeinate pid must still be alive"
        assert "caffeinate" in ps.stdout

        found = False
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and not found:
            assertions = subprocess.run(
                ["pmset", "-g", "assertions"], capture_output=True, text=True, errors="replace"
            )
            found = str(pid) in assertions.stdout and "PreventUserIdleSystemSleep" in assertions.stdout
            if not found:
                time.sleep(0.25)
        assert found, "pmset must show this pid holding a PreventUserIdleSystemSleep assertion"
    finally:
        guard.reconcile(0)

    assert guard.active is False
    deadline = time.monotonic() + 5.0
    gone = False
    while time.monotonic() < deadline and not gone:
        ps = subprocess.run(["ps", "-p", str(pid)], capture_output=True, text=True)
        gone = ps.returncode != 0
        if not gone:
            time.sleep(0.25)
    assert gone, "the caffeinate pid must actually exit after the guard stops it"
