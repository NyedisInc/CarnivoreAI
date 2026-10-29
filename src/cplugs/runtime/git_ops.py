
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

from src.core.dev_tools import git_guard

HARDENING = ("-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null", "-c", "diff.external=",
             "-c", "protocol.ext.allow=never", "-c", "core.pager=cat", "--no-pager")
READ_OPS = {
    "status": ["status", "--porcelain=v1", "--branch"],
    "branch": ["rev-parse", "--abbrev-ref", "HEAD"],
    "remote": ["remote", "-v"],
    "diff_names": ["diff", "--no-ext-diff", "--name-only"],
}
TURN = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
SNAPSHOT_NAMESPACE = "refs/carnivore/"
GIT = "/usr/bin/git"
TIMEOUT_SECONDS = 10
MAX_OUTPUT_BYTES = 64 * 1024
_USERINFO = re.compile(r"(?<=//)[^/@\s]+@")
UNSAFE_CONFIG = re.compile(r"^(filter\..+|.+\.textconv|diff\..+\.command|core\.(fsmonitor|hookspath|sshcommand|askpass|pager|editor))$", re.I)
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


class GitRefused(Exception):
    pass


class GitUnavailable(GitRefused):
    pass


def git_env() -> Dict[str, str]:
    return {"PATH": "/usr/bin:/bin", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0", "HOME": "/var/empty", "LANG": "C",
            "GIT_ATTR_SOURCE": EMPTY_TREE}


def read_argv(repo: Path, op: object) -> List[str]:
    if not isinstance(op, str) or op not in READ_OPS:
        raise GitRefused("unknown git op")
    return [GIT, "-C", str(repo), *HARDENING, *READ_OPS[op]]


def snapshot_ref(turn: object) -> str:
    if not isinstance(turn, str) or not TURN.match(turn):
        raise GitRefused("bad turn")
    return f"{SNAPSHOT_NAMESPACE}snap-{turn}"


def _require_git() -> None:
    if not git_guard.usr_bin_git_available():
        raise GitUnavailable("git is not installed")


def _run(argv: List[str]) -> str:
    _require_git()
    try:
        done = subprocess.run(argv, capture_output=True, env=git_env(), timeout=TIMEOUT_SECONDS, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GitRefused(type(exc).__name__) from exc
    if done.returncode != 0:
        raise GitRefused(f"git exited {done.returncode}")
    return done.stdout[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")


def refuse_unsafe_config(repo: Path) -> None:
    argv = [GIT, "-C", str(repo), "--no-pager", "config", "--list", "--includes", "-z"]
    _require_git()
    try:
        done = subprocess.run(argv, capture_output=True, env=git_env(), timeout=TIMEOUT_SECONDS, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GitRefused(type(exc).__name__) from exc
    if done.returncode != 0:
        raise GitRefused(f"git config exited {done.returncode}")
    for entry in done.stdout.decode("utf-8", errors="replace").split("\0"):
        key = entry.split("\n", 1)[0]
        if key and UNSAFE_CONFIG.match(key):
            raise GitRefused("repo config runs a program")


def read(repo: Path, op: object) -> Dict[str, str]:
    if not Path(repo).is_dir():
        raise GitRefused("not a directory")
    argv = read_argv(repo, op)
    refuse_unsafe_config(repo)
    return {"output": _USERINFO.sub("", _run(argv))}


def snapshot(repo: Path, turn: object) -> Optional[str]:
    ref = snapshot_ref(turn)
    if not Path(repo).is_dir():
        raise GitRefused("not a directory")
    refuse_unsafe_config(repo)
    base = [GIT, "-C", str(repo), *HARDENING]
    sha = _run([*base, "stash", "create"]).strip() or _run([*base, "rev-parse", "HEAD"]).strip()
    if not re.fullmatch(r"[0-9a-f]{40,64}", sha):
        raise GitRefused("no commit to record")
    _run([*base, "update-ref", ref, sha])
    return ref
