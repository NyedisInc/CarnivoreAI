
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
REPO_SCRIPT = REPO / "scripts" / "deploy-dmg.sh"
SCRIPT = Path(os.environ.get("DEPLOY_DMG_SCRIPT") or REPO_SCRIPT)
if SCRIPT != REPO_SCRIPT and os.environ.get("DEPLOY_DMG_ALLOW_SCRATCH") != "1":
    raise RuntimeError(f"DEPLOY_DMG_SCRIPT={SCRIPT} is not the repo script; set DEPLOY_DMG_ALLOW_SCRATCH=1 to test a scratch copy on purpose")

LISTENER = """
import signal, socket, time
if open("ignore_term").read() == "1":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(("127.0.0.1", int(open("port").read()))); s.listen(1)
time.sleep(60)
"""


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


FUNCTIONS = (
    "pid_alive", "engine_holder_check", "port_accepts", "signal_engines", "stop_detached_engine",
    "stop_stray_engines", "wait_for_port_free",
)


def _function_source(text: str | None = None) -> str:
    text = text if text is not None else SCRIPT.read_text(encoding="utf-8")
    assert "stop_detached_engine() {" in text, "deploy-dmg.sh has no stop_detached_engine"
    out = []
    for name in FUNCTIONS:
        start = text.find(f"{name}() {{")
        if start >= 0:
            out.append(text[start : text.index("\n}\n", start) + 3])
    return "\n".join(out)


def _start_listener(folder: Path, port: int, ignore_term: bool = False) -> subprocess.Popen:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "ignore_term").write_text("1" if ignore_term else "0")
    (folder / "src").mkdir(parents=True)
    (folder / "src" / "__init__.py").write_text("")
    (folder / "src" / "main.py").write_text(LISTENER)
    (folder / "port").write_text(str(port))
    proc = subprocess.Popen([sys.executable, "-m", "src.main"], cwd=folder)
    for _ in range(100):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return proc
        time.sleep(0.05)
    proc.kill()
    pytest.fail("the fake engine never listened")


def _run(
    engine_dir: Path, port: int, work: Path, stub_lsof: str = "", stub_ps: str = "", call: str = "", script_text: str | None = None,
    spawned: tuple[int, ...] = (),
) -> subprocess.CompletedProcess:
    env = {**os.environ, "REAL_LSOF": "/usr/sbin/lsof", "REAL_PS": "/bin/ps"}
    allowed = " ".join(str(p) for p in spawned)
    pgrep_stub = f'for p in {allowed}; do echo $p; done\n'
    for name, body in (("lsof", stub_lsof), ("ps", stub_ps), ("pgrep", pgrep_stub)):
        if body:
            (work / "bin").mkdir(exist_ok=True)
            stub = work / "bin" / name
            stub.write_text("#!/bin/bash\n" + body)
            stub.chmod(0o755)
            env["PATH"] = f"{work / 'bin'}:{env['PATH']}"
    body = (
        "set -euo pipefail\nPOLL_S=0.1\nPOLL_TRIES=20\n"
        f'log() {{ echo "$*"; }}\n'
        f'kill() {{ case " {allowed} " in *" ${{@: -1}} "*) builtin kill "$@";; *) echo "TEST GUARD: refused kill $*" >&2; return 1;; esac; }}\n'
        f'ENGINE_DIR="{engine_dir}"\n{_function_source(script_text)}\n'
        f"{call or f'stop_detached_engine {port}'}\n"
    )
    runner = work / "run.sh"
    runner.write_text(body)
    return subprocess.run(["bash", str(runner)], capture_output=True, text=True, timeout=60, env=env)


def _gone(proc: subprocess.Popen) -> bool:
    try:
        proc.wait(timeout=5)
        return True
    except subprocess.TimeoutExpired:
        return False


def test_the_install_s_own_engine_is_stopped(tmp_path: Path) -> None:
    port = _free_port()
    engine = tmp_path / "server"
    proc = _start_listener(engine, port)
    try:
        out = _run(engine.resolve(), port, tmp_path, spawned=(proc.pid,))
        assert "stop the detached engine" in out.stdout
        assert _gone(proc), "the engine still runs after stop_detached_engine"
    finally:
        proc.kill()


def test_a_listener_from_another_folder_is_left_alone(tmp_path: Path) -> None:
    port = _free_port()
    proc = _start_listener(tmp_path / "elsewhere", port)
    try:
        out = _run((tmp_path / "server").resolve(), port, tmp_path, spawned=(proc.pid,))
        assert "stop the detached engine" not in out.stdout
        assert out.returncode != 0 and "not our engine" in out.stdout
        assert not _gone(proc), "a listener outside the engine folder was stopped"
    finally:
        proc.kill()


def test_a_silent_port_is_a_no_op(tmp_path: Path) -> None:
    out = _run(tmp_path, _free_port(), tmp_path)
    assert out.returncode == 0 and out.stdout == ""


def test_a_holder_that_vanishes_mid_check_is_treated_as_stopped(tmp_path: Path) -> None:
    ghost = subprocess.Popen(["true"])
    ghost.wait()
    stub = f'''case "$*" in *-iTCP*) echo {ghost.pid};; *) exit 1;; esac\n'''
    out = _run(tmp_path.resolve(), 1, tmp_path, stub_lsof=stub)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "stop the detached engine" not in out.stdout


def test_a_foreign_holder_next_to_our_engine_refuses_and_signals_nothing(tmp_path: Path) -> None:
    port = _free_port()
    own = _start_listener(tmp_path / "server", port)
    foreign = _start_listener(tmp_path / "elsewhere", _free_port())
    try:
        stub = f'''case "$*" in *-iTCP*) echo {own.pid}; echo {foreign.pid};; *) exec "$REAL_LSOF" "$@";; esac\n'''
        out = _run((tmp_path / "server").resolve(), port, tmp_path, stub_lsof=stub, spawned=(own.pid, foreign.pid,))
        assert out.returncode != 0 and f"pid {foreign.pid} holding" in out.stdout and "is not our engine" in out.stdout
        assert not _gone(own) and not _gone(foreign)
    finally:
        own.kill()
        foreign.kill()


def test_an_engine_dir_given_as_a_symlink_still_matches_the_real_cwd(tmp_path: Path) -> None:
    port = _free_port()
    proc = _start_listener(tmp_path / "server", port)
    link = tmp_path / "link"
    link.symlink_to(tmp_path / "server")
    try:
        out = _run(link, port, tmp_path, spawned=(proc.pid,))
        assert out.returncode == 0 and "stop the detached engine" in out.stdout, out.stdout
        assert _gone(proc)
    finally:
        proc.kill()


def test_a_holder_owned_by_another_uid_is_refused(tmp_path: Path) -> None:
    port = _free_port()
    proc = _start_listener(tmp_path / "server", port)
    try:
        stub = 'case "$*" in *uid=*) echo 0;; *) exec "$REAL_PS" "$@";; esac\n'
        out = _run((tmp_path / "server").resolve(), port, tmp_path, stub_ps=stub, spawned=(proc.pid,))
        assert out.returncode != 0 and "is not our engine" in out.stdout
        assert not _gone(proc)
    finally:
        proc.kill()


def test_a_start_time_that_changes_before_the_signal_is_refused(tmp_path: Path) -> None:
    port = _free_port()
    proc = _start_listener(tmp_path / "server", port)
    counter = tmp_path / "counter"
    try:
        stub = (
            f'case "$*" in *lstart=*) n=$(cat "{counter}" 2>/dev/null || echo 0); echo $((n+1)) > "{counter}"; '
            'echo "start-$n";; *) exec "$REAL_PS" "$@";; esac\n'
        )
        out = _run((tmp_path / "server").resolve(), port, tmp_path, stub_ps=stub, spawned=(proc.pid,))
        assert out.returncode != 0 and "changed identity" in out.stdout
        assert not _gone(proc)
    finally:
        proc.kill()


def test_an_engine_that_ignores_sigterm_is_never_killed_and_the_port_wait_refuses(tmp_path: Path) -> None:
    port = _free_port()
    proc = _start_listener(tmp_path / "server", port, ignore_term=True)
    try:
        out = _run((tmp_path / "server").resolve(), port, tmp_path, call=f"stop_detached_engine {port}; wait_for_port_free {port}", spawned=(proc.pid,))
        assert "ignored SIGTERM" in out.stdout and f"PORT {port} STILL HELD" in out.stdout
        assert out.returncode == 2
        assert proc.poll() is None, "an engine that ignored SIGTERM was killed"
    finally:
        proc.kill()
        proc.wait()


def test_the_rollback_stops_an_engine_that_holds_no_port(tmp_path: Path) -> None:
    mine = _start_listener(tmp_path / "server", _free_port())
    other = _start_listener(tmp_path / "elsewhere", _free_port())
    try:
        out = _run((tmp_path / "server").resolve(), 0, tmp_path, call="stop_stray_engines", spawned=(mine.pid, other.pid,))
        assert out.returncode == 0 and f"pid {mine.pid} " in out.stdout, out.stdout
        assert _gone(mine) and not _gone(other)
    finally:
        mine.kill()
        other.kill()


def test_a_port_that_accepts_connections_with_no_holder_of_ours_is_refused(tmp_path: Path) -> None:
    port = _free_port()
    srv = socket.socket()
    srv.bind(("127.0.0.1", port))
    srv.listen(1)
    try:
        out = _run(tmp_path.resolve(), port, tmp_path, stub_lsof="exit 0\n")
        assert out.returncode != 0
        assert "accepts connections but no process of ours holds it" in out.stdout
    finally:
        srv.close()


def test_the_guards_hold_when_engine_holder_check_is_called_bare_under_set_e(tmp_path: Path) -> None:
    ghost = subprocess.Popen(["true"])
    ghost.wait()
    out = _run(tmp_path.resolve(), 1, tmp_path, stub_lsof="exit 1\n", call=f"engine_holder_check {ghost.pid}")
    assert out.returncode == 2, (out.returncode, out.stdout, out.stderr)


def test_the_script_under_test_is_the_repo_script() -> None:
    if os.environ.get("DEPLOY_DMG_ALLOW_SCRATCH") != "1":
        assert SCRIPT == REPO_SCRIPT
    print(f"deploy-dmg.sh under test: {SCRIPT}")


def test_the_harness_refuses_to_signal_a_pid_it_did_not_spawn(tmp_path: Path) -> None:
    bystander = subprocess.Popen(["sleep", "30"])
    try:
        out = _run(tmp_path, 1, tmp_path, call=f"kill -TERM {bystander.pid} || echo refused")
        assert "TEST GUARD" in out.stderr and "refused" in out.stdout
        assert bystander.poll() is None
    finally:
        bystander.kill()
        bystander.wait()
