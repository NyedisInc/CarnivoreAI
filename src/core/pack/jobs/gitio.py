
from __future__ import annotations

import os
import subprocess
from typing import Mapping, Optional, Sequence

import structlog

from src.core.dev_tools import git_guard
from src.core.pack.jobs.types import JobError

log = structlog.get_logger()

_FIXED_CONFIG = (
    "core.autocrlf=false", "core.safecrlf=false", "core.fsmonitor=false", "core.untrackedCache=false", "core.splitIndex=false", "core.hooksPath=/dev/null",
    "gc.auto=0", "maintenance.auto=false", "filter.lfs.process=", "filter.lfs.required=false", "filter.lfs.clean=cat",
    "filter.lfs.smudge=cat",
)
_IDENTITY = {"GIT_AUTHOR_NAME": "carnivore-jobs", "GIT_AUTHOR_EMAIL": "jobs@carnivore.invalid",
             "GIT_COMMITTER_NAME": "carnivore-jobs", "GIT_COMMITTER_EMAIL": "jobs@carnivore.invalid"}


def _environment(extra: Optional[Mapping[str, str]]) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update({"GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C", **_IDENTITY})
    if extra:
        env.update(extra)
    return env


def run(args: Sequence[str], *, git_dir: Optional[str] = None, work_tree: Optional[str] = None, cwd: Optional[str] = None,
        env: Optional[Mapping[str, str]] = None, input: Optional[bytes] = None, check: bool = True,
        timeout: float = 300.0, quiet_fail: bool = False) -> "subprocess.CompletedProcess[bytes]":
    if not git_guard.git_available():
        raise JobError("git_missing", "git is not installed on this computer", 503)
    argv = ["git"]
    for item in _FIXED_CONFIG:
        argv += ["-c", item]
    if git_dir is not None:
        argv.append(f"--git-dir={git_dir}")
    if work_tree is not None:
        argv.append(f"--work-tree={work_tree}")
    argv += list(args)
    verb = next((a for a in args if not a.startswith("-")), "git")
    try:
        cp = subprocess.run(argv, cwd=cwd, env=_environment(env), input=input, capture_output=True, timeout=timeout, shell=False)
    except subprocess.TimeoutExpired as exc:
        raise JobError("git_timeout", f"git {verb} took longer than {int(timeout)} seconds") from exc
    except FileNotFoundError as exc:
        raise JobError("git_missing", "git is not installed on this computer", 503) from exc
    if cp.returncode != 0:
        if check or not quiet_fail:
            log.warning("jobs_git_failed", verb=verb, returncode=cp.returncode, stderr_bytes=len(cp.stderr))
        if check:
            raise JobError("git_failed", f"git {verb} exited {cp.returncode}")
    return cp


def out(cp: "subprocess.CompletedProcess[bytes]") -> str:
    return cp.stdout.decode("utf-8", "replace").rstrip("\n")
