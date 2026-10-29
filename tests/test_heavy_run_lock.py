
from __future__ import annotations

import os
import shutil
import signal
import stat
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional

REPO = Path(__file__).resolve().parents[1]

FAKE_PYTHON = """#!/bin/bash
echo "start $$" >> "$FAKE_LOG"
sleep "${FAKE_SLEEP:-0}"
echo "end $$" >> "$FAKE_LOG"
exit "${FAKE_RC:-0}"
"""


def _fake_repo(root: Path) -> Path:
    (root / "scripts" / "lib").mkdir(parents=True)
    shutil.copy2(REPO / "scripts" / "run-tests.sh", root / "scripts" / "run-tests.sh")
    shutil.copy2(
        REPO / "scripts" / "lib" / "heavy-run-lock.sh",
        root / "scripts" / "lib" / "heavy-run-lock.sh",
    )
    (root / "tests").mkdir()
    for name in ("test_perf_harness_smoke.py", "test_browser_real_chromium.py"):
        (root / "tests" / name).write_text("")
    py = root / "venv" / "bin" / "python3"
    py.parent.mkdir(parents=True)
    py.write_text(FAKE_PYTHON)
    py.chmod(py.stat().st_mode | stat.S_IXUSR)
    return root


class Harness:

    def __init__(self, tmp_path: Path) -> None:
        self.repo = _fake_repo(tmp_path / "repo")
        self.locks = tmp_path / "locks"
        self.log = tmp_path / "fake.log"
        self.log.write_text("")
        self.procs: List[subprocess.Popen] = []

    def env(self, **extra: str) -> Dict[str, str]:
        env = {k: v for k, v in os.environ.items() if not k.startswith("CLOUDE_HEAVY_RUN_")}
        env.update(
            CLOUDE_HEAVY_RUN_LOCK_DIR=str(self.locks),
            CLOUDE_HEAVY_RUN_POLL="0.2",
            CLOUDE_HEAVY_RUN_MAX_WAIT="30",
            CLOUDE_HEAVY_RUN_MAX_LOAD="100000",
            FAKE_LOG=str(self.log),
            FAKE_SLEEP="0",
        )
        env.update(extra)
        return env

    def start(self, *args: str, **extra: str) -> subprocess.Popen:
        proc = subprocess.Popen(
            ["bash", str(self.repo / "scripts" / "run-tests.sh"), *args],
            env=self.env(**extra),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        self.procs.append(proc)
        return proc

    def slot(self, i: int = 1) -> Path:
        return self.locks / f"slot-{i}.lock"

    def wait_for(self, predicate, timeout: float = 10.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.05)
        raise AssertionError("condition never became true")

    def wait_for_stderr(self, proc: subprocess.Popen, needle: str, timeout: float = 10.0) -> str:
        if not hasattr(proc, "_stderr_buf"):
            proc._stderr_buf = ""
            os.set_blocking(proc.stderr.fileno(), False)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                chunk = os.read(proc.stderr.fileno(), 65536)
            except BlockingIOError:
                chunk = b""
            if chunk:
                proc._stderr_buf += chunk.decode(errors="replace")
            if needle in proc._stderr_buf:
                return proc._stderr_buf
            time.sleep(0.05)
        raise AssertionError(f"{needle!r} never appeared on stderr: {proc._stderr_buf!r}")

    def plant(self, pid: int, *, pid_start: Optional[str], started: int, i: int = 1) -> Path:
        slot = self.slot(i)
        slot.mkdir(parents=True)
        lines = [f"pid={pid}", f"started={started}", "worktree=/elsewhere", "branch=feat/other"]
        if pid_start is not None:
            lines.append(f"pid_start={pid_start}")
        (slot / "owner").write_text("\n".join(lines) + "\n")
        return slot

    def max_concurrency(self) -> int:
        running = peak = 0
        for line in self.log.read_text().splitlines():
            running += 1 if line.startswith("start") else -1
            peak = max(peak, running)
        return peak

    def cleanup(self) -> None:
        for proc in self.procs:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()


def _pid_start(pid: int) -> str:
    out = subprocess.run(
        ["ps", "-o", "lstart=", "-p", str(pid)],
        capture_output=True, text=True, env={**os.environ, "LC_ALL": "C"},
    ).stdout
    return out.strip()


def _dead_pid() -> int:
    proc = subprocess.Popen(["true"])
    proc.wait()
    return proc.pid


def _harness(tmp_path, request) -> Harness:
    h = Harness(tmp_path)
    request.addfinalizer(h.cleanup)
    return h


def test_a_second_full_run_waits_for_the_first_and_names_its_holder(tmp_path, request):
    h = _harness(tmp_path, request)
    first = h.start(FAKE_SLEEP="1.5")
    h.wait_for(lambda: (h.slot() / "owner").exists())
    second = h.start()
    assert second.wait(30) == 0
    assert first.wait(30) == 0
    err = second.stderr.read()
    assert "waiting for a heavy-run slot" in err
    assert f"held by pid {first.pid}" in err
    assert h.max_concurrency() == 1
    assert not h.slot().exists()


def test_slot_count_two_lets_two_run_and_queues_the_third(tmp_path, request):
    h = _harness(tmp_path, request)
    runs = [h.start(FAKE_SLEEP="1.5", CLOUDE_HEAVY_RUN_SLOTS="2") for _ in range(3)]
    assert [r.wait(30) for r in runs] == [0, 0, 0]
    assert h.max_concurrency() == 2
    assert sum("waiting for a heavy-run slot" in r.stderr.read() for r in runs) == 1
    assert not h.slot(1).exists() and not h.slot(2).exists()


def test_a_dead_holder_is_broken(tmp_path, request):
    h = _harness(tmp_path, request)
    h.plant(_dead_pid(), pid_start=None, started=int(time.time()))
    run = h.start()
    assert run.wait(30) == 0
    err = run.stderr.read()
    assert "broke heavy-run slot slot-1.lock" in err and "is dead" in err
    assert h.max_concurrency() == 1


def test_a_live_holder_is_not_broken_and_the_wait_is_bounded(tmp_path, request):
    h = _harness(tmp_path, request)
    me = os.getpid()
    h.plant(me, pid_start=_pid_start(me), started=int(time.time()))
    run = h.start(CLOUDE_HEAVY_RUN_MAX_WAIT="1")
    assert run.wait(30) == 90
    assert "REFUSED" in run.stderr.read()
    assert h.log.read_text() == ""
    assert (h.slot() / "owner").read_text().startswith(f"pid={me}\n")


def test_a_reused_pid_is_broken(tmp_path, request):
    h = _harness(tmp_path, request)
    h.plant(os.getpid(), pid_start="Thu Jan  1 00:00:00 1970", started=int(time.time()))
    run = h.start()
    assert run.wait(30) == 0
    assert "was reused" in run.stderr.read()


def test_a_slot_older_than_three_hours_is_broken(tmp_path, request):
    h = _harness(tmp_path, request)
    me = os.getpid()
    h.plant(me, pid_start=_pid_start(me), started=int(time.time()) - 4 * 3600)
    run = h.start()
    assert run.wait(30) == 0
    assert "over the 10800 s cap" in run.stderr.read()


def test_ctrl_c_releases_the_slot(tmp_path, request):
    h = _harness(tmp_path, request)
    run = h.start(FAKE_SLEEP="30")
    h.wait_for(lambda: "start" in h.log.read_text())
    assert h.slot().exists()
    os.killpg(run.pid, signal.SIGINT)
    assert run.wait(60) == 130
    assert not h.slot().exists()


def test_term_to_the_process_group_releases_the_slot(tmp_path, request):
    h = _harness(tmp_path, request)
    run = h.start(FAKE_SLEEP="30")
    h.wait_for(lambda: "start" in h.log.read_text())
    os.killpg(run.pid, signal.SIGTERM)
    assert run.wait(10) == 143
    assert not h.slot().exists()


def test_ctrl_c_while_queued_leaves_the_holders_slot_alone(tmp_path, request):
    h = _harness(tmp_path, request)
    me = os.getpid()
    h.plant(me, pid_start=_pid_start(me), started=int(time.time()))
    run = h.start(CLOUDE_HEAVY_RUN_MAX_WAIT="300")
    h.wait_for_stderr(run, "waiting for a heavy-run slot")
    assert run.poll() is None
    os.killpg(run.pid, signal.SIGINT)
    assert run.wait(60) == 130
    assert (h.slot() / "owner").read_text().startswith(f"pid={me}\n")


def test_the_load_gate_waits_bounded_then_runs(tmp_path, request):
    h = _harness(tmp_path, request)
    run = h.start(CLOUDE_HEAVY_RUN_MAX_LOAD="0", CLOUDE_HEAVY_RUN_LOAD_MAX_WAIT="1")
    assert run.wait(30) == 0
    err = run.stderr.read()
    assert "is over 0; waiting" in err and "running anyway" in err


def test_a_targeted_run_is_not_gated(tmp_path, request):
    h = _harness(tmp_path, request)
    me = os.getpid()
    h.plant(me, pid_start=_pid_start(me), started=int(time.time()))
    run = h.start("tests/test_perf_harness_smoke.py", CLOUDE_HEAVY_RUN_MAX_WAIT="1")
    assert run.wait(30) == 0
    assert "heavy-run" not in run.stderr.read()


def test_term_to_the_script_alone_releases_once_the_running_pass_returns(tmp_path, request):
    h = _harness(tmp_path, request)
    run = h.start(FAKE_SLEEP="1.5")
    h.wait_for(lambda: "start" in h.log.read_text())
    os.kill(run.pid, signal.SIGTERM)
    time.sleep(0.5)
    assert h.slot().exists()
    assert run.wait(10) == 143
    assert not h.slot().exists()
