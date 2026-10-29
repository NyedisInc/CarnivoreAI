
from __future__ import annotations

import os
import sqlite3
import subprocess
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Mapping, Optional, Tuple

import structlog

from src.core.swarm import visibility
from src.core.swarm.gitrun import run_git
from src.core.swarm.memory import SecretRefused, memory_dir, refuse_secrets, require_slug

logger = structlog.get_logger(__name__)

STATUS_TIMEOUT_S = 30
COMMIT_TIMEOUT_S = 180
MAX_SCAN_BYTES = 2_000_000
_IN_PROGRESS = ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply")

COMMITTED = "committed"
NOTHING = "nothing"
SKIPPED = "skipped"
PENDING_APPROVAL = "pending_approval"
REFUSED_SECRET = "refused_secret"


@dataclass(frozen=True)
class CommitResult:

    status: str
    reason: str = ""
    detail: str = ""
    sha: str = ""
    fingerprint: str = ""


def _git(repo: Path, *args: str, timeout: int = STATUS_TIMEOUT_S, optional_locks: bool = True,
         ) -> "subprocess.CompletedProcess[str]":
    return run_git(repo, *args, timeout=timeout, optional_locks=optional_locks)


def _skip(slug: str, reason: str) -> CommitResult:
    logger.info("swarm_memory_commit_skipped", slug=slug, reason=reason)
    return CommitResult(SKIPPED, reason)


def _blocked_state(repo: Path) -> Optional[str]:
    top = _git(repo, "rev-parse", "--show-toplevel", optional_locks=False)
    if top.returncode != 0:
        return "not_a_repo"
    if os.path.realpath(top.stdout.strip()) != os.path.realpath(repo):
        return "not_repo_root"
    for name in _IN_PROGRESS:
        out = _git(repo, "rev-parse", "--git-path", name, optional_locks=False)
        if out.returncode != 0:
            return "not_a_repo"
        path = Path(out.stdout.strip())
        if not path.is_absolute():
            path = repo / path
        if path.exists():
            return f"in_progress_{name.lower().replace('-', '_')}"
    if _git(repo, "symbolic-ref", "-q", "HEAD").returncode != 0:
        return "detached_head"
    return None


def agent_paths(repo: Path, slug: str) -> List[str]:
    candidates = [str(memory_dir(repo, slug, "project").relative_to(repo)),
                  f".claude/agents/{slug}.md", f".codex/agents/{slug}.toml"]
    keep = []
    for rel in candidates:
        if (repo / rel).exists() or _git(repo, "ls-files", "--", rel).stdout.strip():
            keep.append(rel)
    return keep


def _changed_files(repo: Path, paths: List[str]) -> Optional[List[Tuple[str, bool]]]:
    out = _git(repo, "status", "--porcelain", "-z", "--no-renames", "--untracked-files=all", "--", *paths,
               optional_locks=False)
    if out.returncode != 0:
        return None
    return [(e[3:], e[:2] == "??") for e in out.stdout.split("\0") if len(e) >= 4]


def _unscannable(path: Path) -> bool:
    """True when ``path`` exists but cannot be scanned in full: unreadable, not a regular file, or oversize."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return False
    except OSError:
        return True
    if stat.S_ISLNK(st.st_mode):
        return False
    return not stat.S_ISREG(st.st_mode) or st.st_size > MAX_SCAN_BYTES


def _scan(repo: Path, files: List[str]) -> Tuple[str, str]:
    for rel in files:
        path = repo / rel
        if _unscannable(path):
            return "unscannable", rel
        if path.is_symlink() or not path.exists():
            continue
        try:
            text = path.read_bytes().decode("utf-8", errors="replace")
        except OSError:
            return "unscannable", rel
        try:
            refuse_secrets(text, rel)
        except SecretRefused:
            return "secret", rel
    return "", ""


def commit_memory(conn: sqlite3.Connection, agent: Mapping[str, Any], *,
                  fetch: visibility.Fetch = visibility.fetch_visibility, message: str = "") -> CommitResult:
    slug = require_slug(agent["slug"])
    if agent["rank"] == "task" or agent["memory_scope"] == "local":
        return _skip(slug, "local_scope")
    repo_dir = agent.get("repo_dir")
    if not repo_dir or not Path(repo_dir).is_dir():
        return _skip(slug, "no_repo")
    repo = Path(repo_dir)
    try:
        return _commit(conn, repo, slug, fetch, message or f"swarm: {slug} memory")
    except subprocess.TimeoutExpired:
        return _skip(slug, "git_timeout")
    except OSError as exc:
        logger.warning("swarm_memory_commit_os_error", slug=slug, error=type(exc).__name__)
        return _skip(slug, "git_unavailable")


def _commit(conn: sqlite3.Connection, repo: Path, slug: str, fetch: visibility.Fetch, message: str) -> CommitResult:
    blocked = _blocked_state(repo)
    if blocked:
        return _skip(slug, blocked)
    paths = agent_paths(repo, slug)
    entries = _changed_files(repo, paths) if paths else []
    if entries is None:
        return _skip(slug, "status_failed")
    if not entries:
        return CommitResult(NOTHING)
    changed = [rel for rel, _untracked in entries]
    kind, hit = _scan(repo, changed)
    if kind == "secret":
        logger.warning("swarm_memory_commit_secret", slug=slug, file=hit)
        return CommitResult(REFUSED_SECRET, "secret_in_file", detail=hit)
    if kind:
        logger.warning("swarm_memory_commit_unscannable", slug=slug, file=hit)
        return CommitResult(SKIPPED, "unscannable_file", detail=hit)
    row = visibility.check(conn, str(repo), fetch=fetch)
    if visibility.needs_approval(row):
        logger.info("swarm_memory_commit_pending_approval", slug=slug, visibility=row.get("visibility"))
        return CommitResult(PENDING_APPROVAL, "first_commit_needs_approval", detail=str(row.get("visibility")),
                            fingerprint=str(row.get("remote_fingerprint") or ""))
    return _stage_and_commit(repo, slug, changed, [rel for rel, untracked in entries if untracked], message)


def _stage_and_commit(repo: Path, slug: str, changed: List[str], untracked: List[str], message: str) -> CommitResult:
    try:
        if untracked:
            added = _git(repo, "add", "--intent-to-add", "--", *untracked)
            if added.returncode != 0:
                logger.warning("swarm_memory_commit_add_failed", slug=slug, returncode=added.returncode)
                _unmark(repo, slug, untracked)
                return _skip(slug, "add_failed")
        done = _git(repo, "commit", "--only", "-m", message, "--", *changed,
                    timeout=COMMIT_TIMEOUT_S)
    except BaseException:
        _unmark(repo, slug, untracked)
        raise
    if done.returncode != 0:
        logger.warning("swarm_memory_commit_failed", slug=slug, returncode=done.returncode)
        _unmark(repo, slug, untracked)
        return _skip(slug, "commit_failed")
    sha = _git(repo, "rev-parse", "HEAD").stdout.strip()
    logger.info("swarm_memory_committed", slug=slug, sha=sha, files=len(changed))
    return CommitResult(COMMITTED, sha=sha)


def _unmark(repo: Path, slug: str, untracked: List[str]) -> None:
    if not untracked:
        return
    try:
        reset = _git(repo, "reset", "-q", "--", *untracked)
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.warning("swarm_memory_commit_reset_failed", slug=slug, error=type(exc).__name__)
        return
    if reset.returncode != 0:
        logger.warning("swarm_memory_commit_reset_failed", slug=slug, returncode=reset.returncode)
