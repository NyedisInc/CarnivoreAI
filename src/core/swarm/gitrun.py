
from __future__ import annotations

import os
import re
import signal
import subprocess
from src.core.dev_tools import git_guard
import tempfile
from pathlib import Path
from typing import Dict, Optional

GRACE_S = 5
NO_GIT_RC = 127
MAX_OUT = 8_000_000
_KEEP_PREFIXES = ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM", "GIT_CONFIG_NOSYSTEM", "GIT_SSH", "GIT_ASKPASS")


def git_env(*, optional_locks: bool = True) -> Dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_") or k.startswith(_KEEP_PREFIXES)}
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["LC_ALL"] = "C"
    if not optional_locks:
        env["GIT_OPTIONAL_LOCKS"] = "0"
    return env


def _killpg(pid: int, sig: int) -> None:
    try:
        os.killpg(pid, sig)
    except (ProcessLookupError, PermissionError):
        pass


def _reap(proc: "subprocess.Popen[bytes]") -> None:
    try:
        proc.wait(timeout=GRACE_S)
    except subprocess.TimeoutExpired:
        pass


_UNTRUSTED_FLAGS = ("-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null")
_FILTER_KEY = re.compile(r"^filter\.(.+)\.(?:clean|process)$")


def _filter_flags(repo: Path) -> "list[str]":
    if not git_guard.git_available():
        return []
    try:
        done = subprocess.run(["git", "-C", str(repo), "config", "--name-only", "--get-regexp", r"^filter\."],
                              stdin=subprocess.DEVNULL, capture_output=True, env=git_env(), timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return []
    flags: "list[str]" = []
    for key in done.stdout.decode("utf-8", "replace").splitlines():
        m = _FILTER_KEY.match(key)
        if m:
            flags += ["-c", f"filter.{m.group(1)}.clean=", "-c", f"filter.{m.group(1)}.process="]
    return flags


def run_git(repo: Path, *args: str, timeout: float, optional_locks: bool = True, untrusted_repo: bool = False,
            max_out: Optional[int] = None) -> "subprocess.CompletedProcess[str]":
    if not git_guard.git_available():
        return subprocess.CompletedProcess(["git", *args], NO_GIT_RC, "", "")
    pre: "list[str]" = []
    if untrusted_repo:
        pre = list(_UNTRUSTED_FLAGS)
        if args and args[0] in ("status", "diff"):
            pre += _filter_flags(repo)
    limit = MAX_OUT if max_out is None else max_out
    with tempfile.TemporaryFile() as out:
        proc = subprocess.Popen(["git", "-C", str(repo), "--literal-pathspecs", *pre, *args], stdin=subprocess.DEVNULL,
                                stdout=out, stderr=subprocess.DEVNULL, env=git_env(optional_locks=optional_locks),
                                start_new_session=True)
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            _killpg(proc.pid, signal.SIGTERM)
            _reap(proc)
            if proc.poll() is None:
                _killpg(proc.pid, signal.SIGKILL)
                _reap(proc)
            raise
        except BaseException:
            _killpg(proc.pid, signal.SIGKILL)
            _reap(proc)
            raise
        out.seek(0)
        data = out.read(limit + 1)
        if len(data) > limit and max_out is None:
            return subprocess.CompletedProcess(proc.args, -1, "", "")
        return subprocess.CompletedProcess(proc.args, proc.returncode,
                                           data[:limit].decode("utf-8", "replace" if untrusted_repo else "surrogateescape"), "")
