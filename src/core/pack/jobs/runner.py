
from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Mapping, Optional

import structlog

from src.core.pack.jobs import paths
from src.core.pack.jobs.types import HostState, JobError, RunStatus
from src.core.pack.load import process_tree
from src.core.tmux_control.tmux_error import TmuxError
from src.core.tmux_discovery import tmux_argv_prefix

log = structlog.get_logger(__name__)

_ENV_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-Z\\-_]")
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_TMUX_TIMEOUT = 10.0

_RUN_SH = """#!/bin/bash
# Written by Carnivore for one job. Clean environment first, then the job's own variables.
if [ -z "$CVJOB_CLEAN" ]; then
  exec /usr/bin/env -i HOME="$HOME" USER="$USER" LOGNAME="$LOGNAME" SHELL="$SHELL" TMPDIR="$TMPDIR" LANG="$LANG" TERM="$TERM" \\
    PATH=/usr/bin:/bin:/usr/sbin:/sbin CVJOB_CLEAN=1 /bin/bash "$0"
fi
unset CVJOB_CLEAN
D=$(cd "$(dirname "$0")" && pwd)
. "$D/env.sh"
export CARNIVORE_JOB_ID={job_id} CARNIVORE_JOB_DIR={cwd}
{push_block}
CAP={cap}
set -m
RUN_SHELL="${{SHELL:-/bin/bash}}"
case "$(basename "$RUN_SHELL")" in
  zsh) "$RUN_SHELL" -l -o no_nomatch "$D/command.sh" >> "$D/output.log" 2>&1 < /dev/null & ;;
  *)   "$RUN_SHELL" -l "$D/command.sh" >> "$D/output.log" 2>&1 < /dev/null & ;;
esac
PID=$!
( sleep "$CAP"; : > "$D/capped"; kill -TERM -"$PID" 2>/dev/null; sleep 10; kill -KILL -"$PID" 2>/dev/null ) &
WATCH=$!
wait "$PID"
RC=$?
kill -KILL -"$WATCH" 2>/dev/null
[ -e "$D/capped" ] && RC=124
echo "$RC" > "$D/exit.tmp" && mv "$D/exit.tmp" "$D/exit"
exit "$RC"
"""


def _push_block_exports() -> str:
    env = paths.push_block_env()
    lines = [f"export GIT_CONFIG_COUNT={env['GIT_CONFIG_COUNT']}"]
    for i in range(int(env["GIT_CONFIG_COUNT"])):
        lines.append(f"export GIT_CONFIG_KEY_{i}={env[f'GIT_CONFIG_KEY_{i}']} GIT_CONFIG_VALUE_{i}={env[f'GIT_CONFIG_VALUE_{i}']}")
    return "\n".join(lines)


def _tmux(socket: str, *args: str) -> "subprocess.CompletedProcess[str]":
    try:
        return subprocess.run(tmux_argv_prefix(socket) + list(args), capture_output=True, text=True, timeout=_TMUX_TIMEOUT, check=False,
                              env={**paths.clean_env(path=os.environ.get("PATH", "/usr/bin:/bin")), **({"TMUX_TMPDIR": os.environ["TMUX_TMPDIR"]}
                                                                                                         if "TMUX_TMPDIR" in os.environ else {})})
    except subprocess.TimeoutExpired as exc:
        raise JobError("tmux_timeout", "tmux did not answer in time", 503) from exc
    except OSError as exc:
        raise JobError("tmux_missing", "tmux could not be run on this computer", 503) from exc
    except TmuxError as exc:
        raise JobError("tmux_skew", "tmux on this computer does not match the running jobs server", 503) from exc


def _sq(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def _write(path: Path, text: str, mode: int) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.chmod(path, mode)


def alive(job_id: str, *, socket: str = paths.JOBS_TMUX_SOCKET) -> bool:
    return _tmux(socket, "has-session", "-t", "=" + paths.session_name(job_id)).returncode == 0


def start(job_id: str, *, cwd: str, command: str, env: Mapping[str, str], time_cap_s: int, meta_dir: Path,
          socket: str = paths.JOBS_TMUX_SOCKET) -> None:
    meta = Path(meta_dir)
    if (meta / "exit").exists() or alive(job_id, socket=socket):
        return
    for key in env:
        if not _ENV_KEY.match(key):
            raise JobError("bad_env_name", "an environment variable name is not valid", 422)
    meta.mkdir(parents=True, exist_ok=True)
    os.chmod(meta, 0o700)
    _write(meta / "env.sh", "".join(f"export {k}={_sq(str(v))}\n" for k, v in env.items()), 0o600)
    _write(meta / "command.sh", command if command.endswith("\n") else command + "\n", 0o600)
    _write(meta / "run.sh", _RUN_SH.format(job_id=_sq(job_id), cwd=_sq(cwd), cap=int(time_cap_s), push_block=_push_block_exports()), 0o700)
    _write(meta / "output.log", "", 0o600)
    launcher = ["/bin/bash", str(meta / "run.sh")]
    if sys.platform == "darwin" and os.path.exists("/usr/bin/caffeinate"):
        launcher = ["/usr/bin/caffeinate", "-i"] + launcher
    done = _tmux(socket, "new-session", "-d", "-s", paths.session_name(job_id), "-c", cwd, *launcher)
    if done.returncode != 0:
        log.warning("jobs_runner_start_failed", job_id=job_id, returncode=done.returncode)
        raise JobError("tmux_start_failed", "the job's session could not be started", 503)
    log.info("jobs_runner_started", job_id=job_id)


def _tail(log_path: Path, tail_bytes: int) -> "tuple[str, int]":
    try:
        size = log_path.stat().st_size
        with open(log_path, "rb") as fh:
            fh.seek(max(0, size - tail_bytes))
            raw = fh.read()
    except OSError:
        return "", 0
    text = _ANSI.sub("", raw.decode("utf-8", errors="replace").replace("\r\n", "\n"))
    return _CONTROL.sub("", text), size


def status(job_id: str, *, meta_dir: Path, socket: str = paths.JOBS_TMUX_SOCKET, tail_bytes: int = 16384) -> RunStatus:
    meta = Path(meta_dir)

    def exit_code() -> Optional[int]:
        try:
            return int((meta / "exit").read_text().strip())
        except (OSError, ValueError):
            return None

    code = exit_code()
    text, size = _tail(meta / "output.log", tail_bytes)
    if code is None and alive(job_id, socket=socket):
        return RunStatus(HostState.RUNNING, None, None, text, size)
    if code is None:
        code = exit_code()
        text, size = _tail(meta / "output.log", tail_bytes)
    if code is not None:
        return RunStatus(HostState.EXITED, code, "time cap" if code == 124 else None, text, size)
    return RunStatus(HostState.FAILED, None, "the job's session ended without an exit code", text, size)


def pane_pids(*, socket: str = paths.JOBS_TMUX_SOCKET) -> List[int]:
    return list(pane_pids_by_job(socket=socket).values())


def pane_pids_by_job(*, socket: str = paths.JOBS_TMUX_SOCKET) -> dict:
    done = _tmux(socket, "list-panes", "-a", "-F", "#{session_name} #{session_attached} #{pane_pid}")
    out: dict = {}
    for line in done.stdout.splitlines() if done.returncode == 0 else []:
        parts = line.split()
        if len(parts) == 3 and parts[0].startswith("cvjob_") and parts[1] == "0" and parts[2].isdigit():
            out["job_" + parts[0][len("cvjob_"):]] = int(parts[2])
    return out


def _signal_all(pids: "set[int]", sig: int) -> None:
    for pid in pids:
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            continue
        except PermissionError:
            log.warning("jobs_runner_signal_denied", pid=pid)


def stop(job_id: str, *, meta_dir: Path, socket: str = paths.JOBS_TMUX_SOCKET) -> None:
    name = paths.session_name(job_id)
    panes = _tmux(socket, "list-panes", "-t", "=" + name, "-F", "#{pane_pid}")
    roots = [int(p) for p in panes.stdout.split() if p.isdigit()] if panes.returncode == 0 else []
    procs = process_tree.read() if roots else None
    members: "set[int]" = set()
    for tree in (process_tree.trees(procs, roots).values() if procs else []):
        members |= tree
    members -= {os.getpid()}
    _signal_all(members, signal.SIGTERM)
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and any(_exists(p) for p in members):
        time.sleep(0.1)
    _signal_all({p for p in members if _exists(p)}, signal.SIGKILL)
    _tmux(socket, "kill-session", "-t", "=" + name)
    log.info("jobs_runner_stopped", job_id=job_id, processes=len(members))


def _exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
