from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence

import structlog

from src.core.project_worktree import run_git
from src.core.worktrees.store import WorktreeRecord, WorktreeStore

logger = structlog.get_logger()

DIRTY_LIST_MAX = 50
FINGERPRINT_CHARS = 16


class CleanupRefused(ValueError):

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code


@dataclass
class WorktreeState:

    path: str
    repo: str
    branch: str
    base_branch: str
    exists: bool
    head: Optional[str] = None
    dirty: List[str] = field(default_factory=list)
    untracked: int = 0
    merged: bool = False
    unmerged_commits: int = 0
    pushed: Optional[bool] = None
    finished: bool = False
    steps: List[str] = field(default_factory=list)


async def _lines(args: Sequence[str]) -> List[str]:
    code, out, _err = await run_git(args)
    return [line for line in out.splitlines() if line] if code == 0 else []


async def inspect(record: WorktreeRecord) -> WorktreeState:
    state = WorktreeState(path=record.path, repo=record.repo, branch=record.branch, base_branch=record.base_branch,
                          exists=os.path.isdir(record.path))
    if state.exists:
        status = await _lines(["-C", record.path, "status", "--porcelain=v1", "--untracked-files=normal"])
        state.untracked = sum(1 for s in status if s.startswith("??"))
        state.dirty = [s[3:] for s in status][:DIRTY_LIST_MAX]
        code, head, _ = await run_git(["-C", record.path, "rev-parse", "HEAD"])
        state.head = head if code == 0 else None
    code, _o, _e = await run_git(["-C", record.repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{record.branch}"])
    branch_exists = code == 0
    if branch_exists:
        code, _o, _e = await run_git(["-C", record.repo, "merge-base", "--is-ancestor", record.branch, record.base_branch])
        state.merged = code == 0
        code, count, _ = await run_git(["-C", record.repo, "rev-list", "--count", f"{record.base_branch}..{record.branch}"])
        state.unmerged_commits = int(count) if code == 0 and count.isdigit() else 0
        code, upstream, _ = await run_git(["-C", record.repo, "rev-parse", "--abbrev-ref", f"{record.branch}@{{upstream}}"])
        if code == 0 and upstream:
            code, ahead, _ = await run_git(["-C", record.repo, "rev-list", "--count", f"{upstream}..{record.branch}"])
            state.pushed = code == 0 and ahead == "0"
        else:
            state.pushed = False
    state.finished = (not state.exists) or (not state.dirty and state.merged)
    state.steps = _steps(state, branch_exists)
    return state


def _steps(state: WorktreeState, branch_exists: bool) -> List[str]:
    steps = ["stop the agent in this worktree"]
    if state.exists:
        steps.append(f"git worktree remove {state.path}")
    steps.append("git worktree prune")
    if branch_exists:
        steps.append(f"git branch -d {state.branch}" if state.merged else f"keep unmerged branch {state.branch}")
    steps += ["archive the session rows", "archive the empty child project"]
    return steps


def _fingerprint(states: Sequence[WorktreeState]) -> str:
    material = [{k: v for k, v in asdict(s).items() if k != "steps"} for s in states]
    raw = json.dumps(material, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:FINGERPRINT_CHARS]


async def plan(store: WorktreeStore, paths: Optional[Sequence[str]] = None, *, finished_only: bool = False) -> Dict[str, Any]:
    records = store.live()
    if paths is not None:
        wanted = {os.path.realpath(p) for p in paths}
        known = {r.path for r in records}
        if wanted - known:
            raise CleanupRefused("not_offered", "only worktrees Carnivore made can be removed")
        records = [r for r in records if r.path in wanted]
    states = [await inspect(r) for r in records]
    if finished_only:
        states = [s for s in states if s.finished]
    return {"worktrees": [asdict(s) for s in states], "fingerprint": _fingerprint(states)}


Callback = Callable[[str], Awaitable[None]]


async def apply(store: WorktreeStore, paths: Sequence[str], fingerprint: Optional[str], *, stop: Callback,
                archive: Callback, delete_unmerged: bool = False, remove_dirty: bool = False) -> Dict[str, Any]:
    if not fingerprint:
        raise CleanupRefused("fingerprint_missing", "quote the plan's fingerprint")
    fresh = await plan(store, paths)
    if fresh["fingerprint"] != fingerprint:
        raise CleanupRefused("fingerprint_stale", "something changed since the plan was read; read it again")
    results: List[Dict[str, Any]] = []
    for item in fresh["worktrees"]:
        state = WorktreeState(**item)
        results.append(await _remove_one(store, state, stop=stop, archive=archive, delete_unmerged=delete_unmerged,
                                         remove_dirty=remove_dirty))
    return {"removed": results}


async def _remove_one(store: WorktreeStore, state: WorktreeState, *, stop: Callback, archive: Callback,
                      delete_unmerged: bool, remove_dirty: bool) -> Dict[str, Any]:
    out: Dict[str, Any] = {"path": state.path, "removed": False, "branch_deleted": False, "error": None}
    await stop(state.path)
    record = WorktreeRecord(path=state.path, repo=state.repo, branch=state.branch, base_branch=state.base_branch,
                            created_at=0.0, removed_at=None)
    if _fingerprint([await inspect(record)]) != _fingerprint([state]):
        out["error"] = "the worktree changed while its agent was stopping; plan again"
        logger.info("worktree_changed_after_stop", path=state.path)
        return out
    if state.exists:
        args = ["-C", state.repo, "worktree", "remove", state.path]
        if state.dirty and remove_dirty:
            args.insert(4, "--force")
        code, _o, err = await run_git(args)
        if code != 0:
            out["error"] = err or "git worktree remove failed"
            logger.info("worktree_remove_refused", path=state.path, dirty=len(state.dirty))
            return out
    await run_git(["-C", state.repo, "worktree", "prune"])
    code, _o, _e = await run_git(["-C", state.repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{state.branch}"])
    if code == 0 and (state.merged or delete_unmerged):
        flag = "-d" if state.merged else "-D"
        code, _o, err = await run_git(["-C", state.repo, "branch", flag, state.branch])
        out["branch_deleted"] = code == 0
        if code != 0:
            out["error"] = err or "git branch delete failed"
    await archive(state.path)
    store.mark_removed(state.path)
    out["removed"] = True
    logger.info("worktree_removed", path=state.path, branch_deleted=out["branch_deleted"])
    return out
