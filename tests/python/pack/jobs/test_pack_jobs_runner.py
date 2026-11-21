
from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Callable, Iterator, List

import pytest

from src.core.pack.jobs import paths, runner
from src.core.pack.jobs.types import HostState
from src.core.product_identity import is_owned_session_name
from src.core.tmux_discovery import tmux_argv_prefix

MARKER = "marker-value-123"


@pytest.fixture()
def launch(tmux_test_socket: str, tmp_path: Path) -> Iterator[Callable[..., tuple]]:
    made: List[str] = []
    work = tmp_path / "work dir"
    work.mkdir()

    def go(command: str, cap: int = 60, env: dict | None = None) -> tuple:
        job_id = paths.new_job_id()
        made.append(job_id)
        meta = paths.meta_dir(tmp_path / "jobs root", job_id)
        runner.start(job_id, cwd=str(work), command=command, env=env or {}, time_cap_s=cap, meta_dir=meta, socket=tmux_test_socket)
        return job_id, meta

    yield go
    for job_id in made:
        subprocess.run(tmux_argv_prefix(tmux_test_socket) + ["kill-session", "-t", "=" + paths.session_name(job_id)], capture_output=True, check=False)


def wait_for(sock: str, job_id: str, meta: Path, want: HostState, secs: float = 20.0):
    end = time.monotonic() + secs
    st = runner.status(job_id, meta_dir=meta, socket=sock)
    while st.state != want and time.monotonic() < end:
        time.sleep(0.2)
        st = runner.status(job_id, meta_dir=meta, socket=sock)
    return st


def test_exit_code_output_and_files(launch, tmux_test_socket: str) -> None:
    job_id, meta = launch("echo hi; echo \"id=$CARNIVORE_JOB_ID\"; exit 3", env={"K": "it's"})
    st = wait_for(tmux_test_socket, job_id, meta, HostState.EXITED)
    assert st.state == HostState.EXITED and st.exit_code == 3
    assert "hi" in st.output_tail and f"id={job_id}" in st.output_tail
    assert oct((meta / "env.sh").stat().st_mode & 0o777) == "0o600"
    assert oct((meta / "run.sh").stat().st_mode & 0o777) == "0o700"
    assert "export K='it'\\''s'" in (meta / "env.sh").read_text()
    runner.start(job_id, cwd=str(meta), command="exit 9", env={}, time_cap_s=5, meta_dir=meta, socket=tmux_test_socket)
    assert runner.status(job_id, meta_dir=meta, socket=tmux_test_socket).exit_code == 3


def test_secret_not_on_argv_and_session_not_owned(launch, tmux_test_socket: str) -> None:
    job_id, meta = launch("sleep 30", env={"SECRET_X": MARKER})
    assert runner.alive(job_id, socket=tmux_test_socket)
    shown = subprocess.run(tmux_argv_prefix(tmux_test_socket) + ["list-panes", "-a", "-F", "#{pane_start_command}"], capture_output=True, text=True).stdout
    assert MARKER not in shown
    pid = runner.pane_pids(socket=tmux_test_socket)
    assert pid
    for p in pid:
        args = subprocess.run(["ps", "-o", "args=", "-p", str(p)], capture_output=True, text=True).stdout
        assert MARKER not in args
    assert not is_owned_session_name(paths.session_name(job_id))
    runner.stop(job_id, meta_dir=meta, socket=tmux_test_socket)


def test_time_cap(launch, tmux_test_socket: str) -> None:
    job_id, meta = launch("sleep 300", cap=2)
    st = wait_for(tmux_test_socket, job_id, meta, HostState.EXITED)
    assert st.exit_code == 124 and st.detail == "time cap"


def test_stop_kills_grandchild(launch, tmux_test_socket: str, tmp_path: Path) -> None:
    job_id, meta = launch("sleep 300 & echo $! > grand.pid; wait")
    grand = Path(tmp_path / "work dir" / "grand.pid")
    end = time.monotonic() + 10
    while not grand.exists() and time.monotonic() < end:
        time.sleep(0.1)
    time.sleep(0.3)
    pid = int(grand.read_text().strip())
    assert runner._exists(pid)
    assert runner.pane_pids(socket=tmux_test_socket)
    runner.stop(job_id, meta_dir=meta, socket=tmux_test_socket)
    time.sleep(0.3)
    assert not runner.alive(job_id, socket=tmux_test_socket)
    assert not subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip().replace("Z", "")
    runner.stop(job_id, meta_dir=meta, socket=tmux_test_socket)


def test_killed_session_is_failed(launch, tmux_test_socket: str) -> None:
    job_id, meta = launch("sleep 300")
    subprocess.run(tmux_argv_prefix(tmux_test_socket) + ["kill-session", "-t", "=" + paths.session_name(job_id)], check=True)
    st = runner.status(job_id, meta_dir=meta, socket=tmux_test_socket)
    assert st.state == HostState.FAILED and "without an exit code" in (st.detail or "")


def test_git_push_refused(launch, tmux_test_socket: str) -> None:
    cmd = "git init -q r && cd r && git remote add o https://example.invalid/x.git && git -c user.name=a -c user.email=a@b commit -q --allow-empty -m m && git push o HEAD 2>&1; echo rc=$?"
    job_id, meta = launch(cmd)
    st = wait_for(tmux_test_socket, job_id, meta, HostState.EXITED, 30)
    assert "carnivore-no-push" in st.output_tail and "rc=0" not in st.output_tail


def test_tail_strips_ansi(launch, tmux_test_socket: str) -> None:
    job_id, meta = launch("printf '\\033[31mred\\033[0m\\a ok\\nnext\\n'")
    st = wait_for(tmux_test_socket, job_id, meta, HostState.EXITED)
    assert "red ok\nnext" in st.output_tail and "\x1b" not in st.output_tail
