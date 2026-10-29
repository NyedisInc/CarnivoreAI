
from __future__ import annotations

import os
import re
import subprocess
from src.core.dev_tools import git_guard
from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

import structlog

logger = structlog.get_logger()

RUNG_GIT, RUNG_CARRIED, RUNG_TAR = "git", "carried", "tar"
RUNG_UNITS = "units"
PURPOSE_SPAN, PURPOSE_MOVE = "span", "move"
GITHUB_HOST = "github.com"
_REMOTE_VERBS = frozenset({"push", "pull", "clone", "ls-remote", "remote", "submodule"})
DEFAULT_TIMEOUT = 120.0


class AirGapViolation(Exception):
    pass


class RungUnavailable(Exception):

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code, self.detail = code, detail


@dataclass(frozen=True)
class Choice:

    rung: str
    reason: str


def git_verb(argv: Sequence[str]) -> Optional[str]:
    skip = False
    for arg in argv[1:]:
        if skip:
            skip = False
        elif arg in ("-C", "-c", "--git-dir", "--work-tree", "--namespace"):
            skip = True
        elif not arg.startswith("-"):
            return arg
    return None


def check_argv(argv: Sequence[str], *, air_gap: bool) -> None:
    if not air_gap:
        return
    if any(GITHUB_HOST in str(a).lower() for a in argv):
        raise AirGapViolation("air-gap: an argument names github.com")
    if os.path.basename(str(argv[0])) == "gh":
        raise AirGapViolation("air-gap: gh is never run for an air-gapped project")
    if os.path.basename(str(argv[0])) == "git":
        verb = git_verb(argv)
        if verb in _REMOTE_VERBS:
            raise AirGapViolation(f"air-gap: git {verb} reaches a remote")
        if verb == "fetch" and not any(os.path.isfile(str(a)) for a in argv[2:]):
            raise AirGapViolation("air-gap: git fetch is allowed only from a local bundle file")


def run(argv: Sequence[str], *, air_gap: bool, cwd: Optional[str] = None, env: Optional[Mapping[str, str]] = None,
        stdin: Optional[bytes] = None, timeout: float = DEFAULT_TIMEOUT) -> subprocess.CompletedProcess:
    check_argv(argv, air_gap=air_gap)
    if argv and argv[0] == "git" and not git_guard.git_available():
        return subprocess.CompletedProcess(list(argv), 127, b"", b"git is not installed")
    merged: Dict[str, str] = {**os.environ, "GIT_TERMINAL_PROMPT": "0", **(env or {})}
    return subprocess.run(list(argv), cwd=cwd, env=merged, input=stdin, capture_output=True, timeout=timeout, check=False)


def choose_rung(*, purpose: str, air_gap: bool, has_git: bool, has_remote: bool) -> Choice:
    if purpose not in (PURPOSE_SPAN, PURPOSE_MOVE):
        raise ValueError(f"unknown purpose {purpose!r}")
    if has_git and has_remote and not air_gap:
        return Choice(RUNG_GIT, "the project has a remote, so the other computer clones it and pushes as usual")
    if has_git:
        why = "air-gap is on, so carnivore carries the commits over the link" if air_gap else \
            "the project has no remote, so carnivore carries the commits over the link"
        return Choice(RUNG_CARRIED, why)
    if purpose == PURPOSE_MOVE:
        return Choice(RUNG_TAR, "the folder is not a git repo, so it goes one way as an archive and the copies will not stay in sync")
    raise RungUnavailable("span_needs_git", "a folder with no git cannot span; publish a private repo or move it one way")


_SSH_URL = re.compile(r"^(?:ssh://)?git@github\.com[:/](?P<path>[^\s]+)$", re.IGNORECASE)


_URL_USERINFO = re.compile(r"^[a-z][a-z0-9+.-]*://[^/?#]*@", re.IGNORECASE)


def remote_has_userinfo(remote: str) -> bool:
    text = remote.strip()
    return not _SSH_URL.match(text) and bool(_URL_USERINFO.match(text))


def https_url(remote: str) -> str:
    found = _SSH_URL.match(remote.strip())
    return f"https://github.com/{found.group('path')}" if found else remote.strip()


def clone_args(remote: str, dest: str, helper_config: Sequence[Tuple[str, str]]) -> List[str]:
    argv: List[str] = ["git"]
    for key, value in helper_config:
        argv += ["-c", f"{key}={value}"]
    return argv + ["clone", "--", https_url(remote), dest]


def clone_from_origin(remote: str, dest: str, helper_config: Sequence[Tuple[str, str]], *, air_gap: bool,
                      timeout: float = 600.0) -> None:
    if remote_has_userinfo(remote):
        raise RuntimeError("clone_failed")
    done = run(clone_args(remote, dest, helper_config), air_gap=air_gap, timeout=timeout)
    if done.returncode != 0:
        logger.warning("pack_transport_clone_failed", status=done.returncode, stderr_bytes=len(done.stderr))
        raise RuntimeError("clone_failed")
