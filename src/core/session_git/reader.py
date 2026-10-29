
from __future__ import annotations

import subprocess
from src.core.dev_tools import git_guard
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import structlog

from src.core.swarm.gitrun import run_git
from src.models.session_git import GitCounts, GitFile, GitFileKind, SessionGitStatus

log = structlog.get_logger()

MAX_FILES = 500
TIMEOUT_S = 8.0
_SHORT = 7
_STATUS_ARGS = ("status", "--porcelain=v2", "-z", "--branch", "--untracked-files=normal")


def _kind(x: str, y: str, conflicted: bool) -> GitFileKind:
    if conflicted:
        return "conflicted"
    codes = x + y
    for code, kind in (("R", "renamed"), ("C", "copied"), ("A", "added"), ("D", "deleted"), ("T", "typechange")):
        if code in codes:
            return kind  # type: ignore[return-value]
    return "modified"


def _parse_entry(rec: str, rest: List[str]) -> Tuple[Optional[GitFile], str]:
    t = rec[:1]
    if t == "1":
        parts = rec.split(" ", 8)
        if len(parts) == 9:
            x, y = parts[1][0], parts[1][1]
            return GitFile(path=parts[8], index=x, worktree=y, kind=_kind(x, y, False), submodule=parts[2][:1] == "S"), t
    elif t == "2":
        parts = rec.split(" ", 9)
        if len(parts) == 10:
            x, y = parts[1][0], parts[1][1]
            orig = rest.pop(0) if rest else None
            return GitFile(path=parts[9], orig_path=orig, index=x, worktree=y, kind=_kind(x, y, False),
                           submodule=parts[2][:1] == "S"), t
    elif t == "u":
        parts = rec.split(" ", 10)
        if len(parts) == 11:
            return GitFile(path=parts[10], index=parts[1][0], worktree=parts[1][1], kind="conflicted",
                           submodule=parts[2][:1] == "S"), t
    elif t == "?" and rec[1:2] == " ":
        return GitFile(path=rec[2:], index="?", worktree="?", kind="untracked"), t
    return None, t


def parse_status(raw: str) -> SessionGitStatus:
    head: Dict[str, str] = {}
    counts = GitCounts()
    files: List[GitFile] = []
    total = 0
    fields = raw.split("\0")
    while fields:
        rec = fields.pop(0)
        if not rec:
            continue
        if rec.startswith("# "):
            key, _, val = rec[2:].partition(" ")
            head[key] = val
            continue
        f, t = _parse_entry(rec, fields)
        if f is None:
            continue
        total += 1
        if t == "u":
            counts.conflicted += 1
        elif t == "?":
            counts.untracked += 1
        else:
            counts.staged += f.index != "."
            counts.unstaged += f.worktree != "."
        if len(files) < MAX_FILES:
            files.append(f)
    oid, name = head.get("branch.oid", ""), head.get("branch.head", "")
    unborn = oid == "(initial)"
    detached = name == "(detached)"
    ahead = behind = None
    ab = head.get("branch.ab", "").split()
    if len(ab) == 2 and ab[0][:1] == "+" and ab[1][:1] == "-" and ab[0][1:].isdigit() and ab[1][1:].isdigit():
        ahead, behind = int(ab[0][1:]), int(ab[1][1:])
    return SessionGitStatus(
        state="ok", branch=None if detached or name == "" else name, detached=detached, unborn=unborn,
        head_short=oid[:_SHORT] if oid and not unborn else None, upstream=head.get("branch.upstream") or None,
        ahead=ahead, behind=behind, counts=counts, files=files, truncated=total - len(files))


def _has_git_entry(directory: Path) -> bool:
    return any((d / ".git").exists() for d in (directory, *directory.parents))


def _unknown() -> SessionGitStatus:
    return SessionGitStatus(state="unknown", read_at=time.time())


def read_session_git(directory: Path) -> SessionGitStatus:
    deadline = time.monotonic() + TIMEOUT_S

    def git(repo: Path, *args: str) -> "subprocess.CompletedProcess[str]":
        return run_git(repo, *args, timeout=max(0.1, deadline - time.monotonic()), optional_locks=False, untrusted_repo=True)

    try:
        if not directory.is_dir() or not git_guard.git_available():
            return _unknown()
        top = git(directory, "rev-parse", "--show-toplevel")
        if top.returncode == 128 and not _has_git_entry(directory.resolve()):
            return SessionGitStatus(state="not_a_repo", read_at=time.time())
        root = top.stdout.rstrip("\n")
        if top.returncode != 0 or not root:
            return _unknown()
        raw = git(Path(root), *_STATUS_ARGS)
        if raw.returncode != 0:
            return _unknown()
        status = parse_status(raw.stdout)
        status.repo_root, status.repo_name = root, Path(root).name
        if status.upstream and status.branch:
            rem = git(Path(root), "config", "--get", f"branch.{status.branch}.remote")
            status.remote = rem.stdout.strip() or None if rem.returncode == 0 else None
        status.read_at = time.time()
        return status
    except subprocess.TimeoutExpired:
        log.warning("session_git_timeout", directory=str(directory))
        return _unknown()
    except (OSError, ValueError) as exc:
        log.warning("session_git_read_failed", directory=str(directory), error=type(exc).__name__)
        return _unknown()
