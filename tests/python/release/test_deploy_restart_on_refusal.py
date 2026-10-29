
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from tests.python.release import test_deploy_detached_engine as harness


def _block(text: str, name: str) -> str:
    start = text.index(f"\n{name}() {{") + 1
    return text[start : text.index("\n}\n", start) + 3]


def _prepare(tmp: Path, port: int, spawned: tuple[int, ...], job: str = "absent", slow_bootstrap: bool = False) -> tuple[Path, dict[str, str], Path]:
    text = harness.SCRIPT.read_text(encoding="utf-8")
    seg = text[text.index('log "stop $CUR'): text.index('log "install $V')].replace("8000", str(port))
    traps = "\n".join(line for line in text.splitlines() if line.startswith("trap "))
    calls = tmp / "calls.log"
    printed = {"absent": "exit 1", "running": "echo 'state = running'", "idle": "echo 'state = waiting'"}
    bindir = tmp / "bin"
    bindir.mkdir(exist_ok=True)
    stubs = {
        "launchctl": f'echo "launchctl $*" >> "{calls}"\ncase "$1" in print) {printed[job]};; bootstrap) {"sleep 1" if slow_bootstrap else ":"};; esac\n',
        "open": f'echo "open $*" >> "{calls}"\n',
        "pgrep": "".join(f"echo {p}\n" for p in spawned),
    }
    for name, stub_body in stubs.items():
        stub = bindir / name
        stub.write_text("#!/bin/bash\n" + stub_body)
        stub.chmod(0o755)
    allowed = " ".join(str(p) for p in spawned)
    funcs = "\n".join(_block(text, n) for n in ("log", "bootstrap_with_retries", "restart_previous_app", "arm_rollback_if_swapped", "on_exit", "boot_out_all_carnivore_jobs"))
    funcs += "\n" + harness._function_source(text)
    body = (
        "set -euo pipefail\nPOLL_S=0.1\nPOLL_TRIES=20\nTS=t\nPLIST=/nonexistent.plist\nLABEL=ai.test.label\nCUR=1.0.0\nAPP=/nonexistent.app\nSTAGED_APP=/nonexistent-stage/Carnivore.app\n"
        f'ROLLBACK_ARMED=0\nKEEP_STAGE=0\nMNT=""\nSTAGE=/nonexistent-stage\nOLD_APP_STOPPED=0\n'
        f'kill() {{ case " {allowed} " in *" ${{@: -1}} "*) builtin kill "$@";; *) echo "TEST GUARD: refused kill $*" >&2; return 1;; esac; }}\n'
        f'ENGINE_DIR="{tmp / "server"}"\n{funcs}\n{traps}\n' + seg
    )
    runner = tmp / "run.sh"
    runner.write_text(body)
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "TMPDIR": str(tmp)}
    return runner, env, calls


def _run_segment(tmp: Path, port: int, spawned: tuple[int, ...], job: str = "absent") -> tuple[subprocess.CompletedProcess, list[str]]:
    runner, env, calls = _prepare(tmp, port, spawned, job)
    done = subprocess.run(["/bin/bash", str(runner)], capture_output=True, text=True, timeout=60, env=env)
    return done, calls.read_text().splitlines() if calls.exists() else []


def _wait_for(path: Path, needle: str, run: subprocess.Popen) -> None:
    for _ in range(200):
        if path.exists() and needle in path.read_text():
            return
        harness.time.sleep(0.05)
    run.kill()
    raise AssertionError(f"never saw {needle!r} in {path}")


def test_a_foreign_port_holder_restarts_the_previous_app(tmp_path: Path) -> None:
    port = harness._free_port()
    foreign = harness._start_listener(tmp_path / "elsewhere", port)
    try:
        done, calls = _run_segment(tmp_path, port, (foreign.pid,))
        assert done.returncode == 2 and "REFUSED" in done.stdout, done.stdout + done.stderr
        assert any(c.startswith("launchctl bootstrap") for c in calls), calls
        assert not harness._gone(foreign), "the foreign listener was signaled"
    finally:
        foreign.kill()


def test_a_port_still_held_after_the_stop_restarts_the_previous_app(tmp_path: Path) -> None:
    port = harness._free_port()
    own = harness._start_listener(tmp_path / "server", port, ignore_term=True)
    try:
        done, calls = _run_segment(tmp_path, port, (own.pid,))
        assert done.returncode == 2 and "STILL HELD" in done.stdout, done.stdout + done.stderr
        assert any(c.startswith("launchctl bootstrap") for c in calls), calls
    finally:
        own.kill()


def test_a_clean_stop_launches_nothing(tmp_path: Path) -> None:
    done, calls = _run_segment(tmp_path, harness._free_port(), ())
    assert done.returncode == 0, done.stdout + done.stderr
    assert not any(c.startswith(("launchctl bootstrap", "open")) for c in calls), calls


def test_the_flag_is_cleared_once_the_swap_succeeds() -> None:
    text = harness.SCRIPT.read_text(encoding="utf-8")
    assert text.index("ROLLBACK_ARMED=1\nKEEP_STAGE=1") < text.index("OLD_APP_STOPPED=0   #")
    assert text.index('mv "$STAGED_APP/Contents" "$OLD/Contents"') > text.index("OLD_APP_STOPPED=0   #")


def test_a_job_that_is_already_running_is_not_bootstrapped_again(tmp_path: Path) -> None:
    port = harness._free_port()
    foreign = harness._start_listener(tmp_path / "elsewhere", port)
    try:
        done, calls = _run_segment(tmp_path, port, (foreign.pid,), job="running")
        assert done.returncode == 2 and "already running" in done.stdout, done.stdout + done.stderr
        assert not any(c.startswith("launchctl bootstrap") for c in calls), calls
    finally:
        foreign.kill()


def test_a_job_that_is_loaded_but_not_running_is_bootstrapped(tmp_path: Path) -> None:
    port = harness._free_port()
    foreign = harness._start_listener(tmp_path / "elsewhere", port)
    try:
        done, calls = _run_segment(tmp_path, port, (foreign.pid,), job="idle")
        assert done.returncode == 2 and "already running" not in done.stdout, done.stdout + done.stderr
        assert any(c.startswith("launchctl bootstrap") for c in calls), calls
    finally:
        foreign.kill()


def test_a_sigterm_during_the_port_wait_restarts_the_previous_app(tmp_path: Path) -> None:
    port = harness._free_port()
    own = harness._start_listener(tmp_path / "server", port, ignore_term=True)
    runner, env, calls = _prepare(tmp_path, port, (own.pid,))
    out_file = tmp_path / "out.log"
    try:
        with out_file.open("w") as out:
            run = subprocess.Popen(["/bin/bash", str(runner)], stdout=out, stderr=subprocess.STDOUT, env=env)
        try:
            _wait_for(out_file, "wait for :", run)
            run.send_signal(15)
            rc = run.wait(timeout=20)
        finally:
            if run.poll() is None:
                run.kill()
        recorded = calls.read_text().splitlines() if calls.exists() else []
        assert rc == 143, f"a SIGTERMed deploy exited {rc}, not 143"
        assert any(c.startswith("launchctl bootstrap") for c in recorded), recorded
    finally:
        own.kill()


def test_a_second_signal_does_not_cut_the_restart_off(tmp_path: Path) -> None:
    port = harness._free_port()
    own = harness._start_listener(tmp_path / "server", port, ignore_term=True)
    runner, env, calls = _prepare(tmp_path, port, (own.pid,), slow_bootstrap=True)
    out_file = tmp_path / "out.log"
    try:
        with out_file.open("w") as out:
            run = subprocess.Popen(["/bin/bash", str(runner)], stdout=out, stderr=subprocess.STDOUT, env=env)
        try:
            _wait_for(out_file, "wait for :", run)
            run.send_signal(15)
            _wait_for(calls, "launchctl bootstrap", run)
            run.send_signal(15)
            rc = run.wait(timeout=20)
        finally:
            if run.poll() is None:
                run.kill()
        assert "RESTART done" in out_file.read_text(), out_file.read_text()
        assert rc == 143, rc
    finally:
        own.kill()
