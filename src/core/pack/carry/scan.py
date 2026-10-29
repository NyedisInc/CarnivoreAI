
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from typing import Any, Collection, Dict, List, Optional, Tuple

from src.core.pack.transport import bundles, ladder
from src.core.pack.transport.tarball import EXCLUDE_ANYWHERE

CARRY_TREE = "pack.carry_tree"
IGNORED_WHY = "ignored content is never carried"
_NOISE = frozenset({".DS_Store"})
_GIT_TIMEOUT = 60.0
_MAX_FILES = 10_000


@dataclass
class RepoUnit:

    rel: str
    head: Optional[str]
    dirty: int
    ignored: List[str] = field(default_factory=list)


@dataclass
class CarrySet:

    root: str
    root_is_repo: bool
    repos: List[RepoUnit] = field(default_factory=list)
    worktrees: List[str] = field(default_factory=list)
    worktree_repos: Dict[str, str] = field(default_factory=dict)
    files: List[str] = field(default_factory=list)

    @property
    def nested(self) -> List[RepoUnit]:
        return [r for r in self.repos if r.rel != "."]

    @property
    def has_content(self) -> bool:
        return bool(self.repos or self.files or self.worktrees)

    def total_bytes(self, *, air_gap: bool = False) -> int:
        total = 0
        for r in self.repos:
            counts = dict(ln.split(": ", 1) for ln in (_git(os.path.join(self.root, r.rel), "count-objects", "-v", air_gap=air_gap) or "").splitlines() if ": " in ln)
            total += sum(int(counts.get(k, "0")) for k in ("size", "size-pack") if counts.get(k, "0").isdigit()) * 1024
        for f in self.files:
            try:
                total += os.lstat(os.path.join(self.root, f)).st_size
            except OSError:
                continue
        return total

    def view(self, carries_wip: bool = False) -> Dict[str, Any]:
        units: List[Dict[str, Any]] = [{"kind": "repo", "path": r.rel, "state": "dirty" if r.dirty else "clean"} for r in self.repos]
        units += [{"kind": "worktree", "path": w, "state": "outside the folder"} for w in self.worktrees]
        if self.files:
            units.append({"kind": "files", "path": f"{len(self.files)} {'file' if len(self.files) == 1 else 'files'} outside any repo", "state": "loose"})
        left = [{"what": f"{r.dirty} uncommitted {'file' if r.dirty == 1 else 'files'} in the project folder", "why": "only commits are carried"} for r in self.repos if r.dirty and r.rel == "." and not carries_wip]
        left += [{"what": f"{r.rel}/{name}", "why": IGNORED_WHY} for r in self.repos for name in r.ignored]
        return {"units": units, "left_behind": left}


def _git(path: str, *args: str, air_gap: bool) -> Optional[str]:
    try:
        done = ladder.run(["git", "-C", path, *args], air_gap=air_gap, timeout=_GIT_TIMEOUT)
    except (subprocess.TimeoutExpired, OSError):
        return None
    return done.stdout.decode(errors="replace") if done.returncode == 0 else None


def _unit(root: str, path: str, *, air_gap: bool) -> RepoUnit:
    status = _git(path, "status", "--porcelain", "--ignored=matching", air_gap=air_gap) or ""
    lines = [ln for ln in status.splitlines() if ln.strip()]
    head = (_git(path, "rev-parse", "-q", "--verify", "HEAD", air_gap=air_gap) or "").strip() or None
    return RepoUnit(rel=os.path.relpath(path, root), head=head, dirty=sum(1 for ln in lines if not ln.startswith("!!")),
                    ignored=[ln[3:].rstrip("/") for ln in lines if ln.startswith("!!")][:20])


def outside_worktrees(root: str, *, air_gap: bool = False) -> List[str]:
    return _outside_worktrees(root, root, air_gap=air_gap) if bundles.is_repo(root) else []


def _outside_worktrees(root: str, path: str, *, air_gap: bool) -> List[str]:
    out = _git(path, "worktree", "list", "--porcelain", air_gap=air_gap) or ""
    paths = [ln[len("worktree "):] for ln in out.splitlines() if ln.startswith("worktree ")][1:]
    real_root = os.path.realpath(root)
    return [p for p in paths if os.path.isdir(p) and not (os.path.realpath(p) + os.sep).startswith(real_root + os.sep)]


def _walk(root: str, air_gap: bool, has_repo: bool) -> Tuple[List[str], List[str]]:
    repos, files = [], []
    for here, dirs, names in os.walk(root):
        if here != root and (".git" in dirs or ".git" in names):
            if has_repo and _git(root, "check-ignore", "-q", here, air_gap=air_gap) is not None:
                dirs[:] = []
                continue
            repos.append(here)
            dirs[:] = []
            continue
        dirs[:] = [d for d in dirs if d not in EXCLUDE_ANYWHERE]
        files += [os.path.relpath(os.path.join(here, n), root) for n in names if n not in _NOISE]
        if len(files) >= _MAX_FILES:
            break
    return repos, files


def scan_project(root: str, *, air_gap: bool = False) -> CarrySet:
    is_repo = bundles.is_repo(root)
    nested, files = _walk(root, air_gap, is_repo)
    found = CarrySet(root=root, root_is_repo=is_repo)
    if is_repo:
        found.repos.append(_unit(root, root, air_gap=air_gap))
        files = []
    for path in nested:
        found.repos.append(_unit(root, path, air_gap=air_gap))
    for path in ([root] if is_repo else []) + nested:
        outside = _outside_worktrees(root, path, air_gap=air_gap)
        found.worktrees += outside
        found.worktree_repos.update({w: os.path.relpath(path, root) for w in outside})
    found.files = files
    return found


def blockers(found: CarrySet, target_label: str, target_caps: Collection[str]) -> Optional[Tuple[str, str]]:
    can = CARRY_TREE in target_caps
    lost = [] if can else [f"{r.rel} (nested repo)" for r in found.nested]
    lost += [] if can else [f"{os.path.basename(w)} (worktree outside the folder)" for w in found.worktrees]
    if found.files and not can:
        lost.append(f"{len(found.files)} loose {'file' if len(found.files) == 1 else 'files'} outside any repo")
    if lost:
        why = f"{target_label} runs an older carnivore and cannot take" if not can else "this computer cannot send yet"
        tail = f"; update {target_label}, then send again" if not can else ""
        return "content_not_carried", f"{why} {', '.join(lost)}{tail}"
    if can and len(found.files) >= _MAX_FILES:
        return "carry_too_large", "the loose files outside any repo are too many to send; move them into a repo or a subfolder you untick, then send again"
    unborn = [r.rel for r in found.nested if r.head is None and r.dirty]
    if unborn:
        return "content_not_carried", f"{', '.join(unborn)} has files but no commit yet, so it cannot be sent; commit once, then send again"
    root_repo = next((r for r in found.repos if r.rel == "."), None)
    if root_repo is not None and root_repo.head is None and root_repo.dirty:
        return "target_copy_empty", f"the project has files but no commit yet, so {target_label} would get an empty folder; commit once, then send again"
    return None
