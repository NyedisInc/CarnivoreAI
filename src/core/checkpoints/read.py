
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

from src.core.checkpoints.store import Checkpoint, CheckpointStore
from src.core.session_git.diff import _BINARY_LINE, MAX_BYTES, TIMEOUT_S, _cap, _screened
from src.core.session_git.secret_names import is_secret_path
from src.models.session_git import GitFile, SessionGitDiff
from src.core.swarm.gitrun import run_git

_KINDS = {"A": "added", "M": "modified", "D": "deleted", "R": "renamed", "C": "copied", "T": "typechange"}


def _shadow_git(cp: Checkpoint, *args: str, max_out: Optional[int] = None) -> "subprocess.CompletedProcess[str]":
    return run_git(Path(cp.shadow), *args, timeout=TIMEOUT_S, optional_locks=False, untrusted_repo=True, max_out=max_out)


def base_of(store: CheckpointStore, cp: Checkpoint) -> Optional[str]:
    older = [r for r in store.for_session(cp.session_uuid)
             if r.work_tree == cp.work_tree and (r.created_at, r.id) < (cp.created_at, cp.id) and r.commit_sha != cp.commit_sha]
    if older:
        return older[0].commit_sha
    return cp.head_sha


def _empty_tree(cp: Checkpoint) -> Optional[str]:
    done = run_git(Path(cp.shadow), "hash-object", "-t", "tree", "/dev/null", timeout=TIMEOUT_S, untrusted_repo=True)
    return done.stdout.strip() if done.returncode == 0 and done.stdout.strip() else None


def changes(store: CheckpointStore, cp: Checkpoint) -> Optional[List[GitFile]]:
    base = base_of(store, cp) or _empty_tree(cp)
    if base is None:
        return None
    done = _shadow_git(cp, "diff-tree", "-r", "-z", "-M", "--name-status", "--no-commit-id", base, cp.commit_sha)
    if done.returncode != 0:
        return None
    fields = [f for f in done.stdout.split("\0") if f]
    out: List[GitFile] = []
    i = 0
    while i < len(fields):
        status = fields[i]
        letter = status[:1]
        if letter in ("R", "C") and i + 2 < len(fields):
            out.append(GitFile(path=fields[i + 2], orig_path=fields[i + 1], kind=_KINDS[letter]))
            i += 3
        else:
            out.append(GitFile(path=fields[i + 1], kind=_KINDS.get(letter, "modified")))
            i += 2
    return out


def file_diff(store: CheckpointStore, cp: Checkpoint, entry: GitFile) -> SessionGitDiff:
    rel = entry.path
    if is_secret_path(rel, entry.orig_path):
        return SessionGitDiff(state="ok", path=rel, sensitive=True)
    base = base_of(store, cp) or _empty_tree(cp)
    if base is None:
        return SessionGitDiff(state="unknown", path=rel)
    specs = [p for p in (entry.orig_path, rel) if p]
    try:
        done = _shadow_git(cp, "diff", "--no-color", "--no-ext-diff", "--no-textconv", "-M", base, cp.commit_sha, "--",
                           *specs, max_out=MAX_BYTES + 1)
    except subprocess.TimeoutExpired:
        return SessionGitDiff(state="unknown", path=rel)
    if done.returncode != 0:
        return SessionGitDiff(state="unknown", path=rel)
    if _BINARY_LINE.search(done.stdout):
        return SessionGitDiff(state="ok", path=rel, binary=True)
    text, cut = _cap(done.stdout)
    return _screened(SessionGitDiff(state="ok", path=rel, text=text, truncated=cut), entry)


def _bytes_under(folder: Path) -> int:
    total = 0
    for root, _, names in os.walk(folder):
        for name in names:
            try:
                total += os.lstat(os.path.join(root, name)).st_size
            except OSError:
                continue
    return total


def usage(store: CheckpointStore) -> List[Dict[str, object]]:
    by_shadow: Dict[str, Dict[str, object]] = {}
    for session in store.sessions():
        for cp in store.for_session(session):
            row = by_shadow.setdefault(cp.shadow, {"work_tree": cp.work_tree, "checkpoints": 0, "bytes": 0,
                                                   "disabled_reason": None})
            row["checkpoints"] = int(row["checkpoints"]) + 1
    for state in store.disabled_repos():
        by_shadow.setdefault(state["shadow"], {"work_tree": state["work_tree"], "checkpoints": 0, "bytes": 0,
                                               "disabled_reason": None})
    for shadow, row in by_shadow.items():
        row["bytes"] = _bytes_under(Path(shadow)) if os.path.isdir(shadow) else 0
        state = store.repo_state(shadow)
        row["disabled_reason"] = state["disabled_reason"] if state is not None else None
    return sorted(by_shadow.values(), key=lambda r: str(r["work_tree"]))
