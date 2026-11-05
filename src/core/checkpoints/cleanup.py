
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Iterable, List, Optional

import structlog

from src.core.checkpoints.capture import REF_PREFIX, SCRATCH_DIRNAME, repo_lock
from src.core.checkpoints.shadow import GIT_TIMEOUT_S, SHADOW_DIRNAME
from src.core.checkpoints.store import KIND_SAFETY, KIND_TURN, Checkpoint, CheckpointStore
from src.core.swarm.gitrun import run_git

logger = structlog.get_logger()

KEEP_NEWEST = 20
MAX_AGE_S = 7 * 24 * 3600
SCRATCH_MAX_AGE_S = 3600


def doomed(rows: List[Checkpoint], pinned: set, now: float) -> List[Checkpoint]:
    out: List[Checkpoint] = []
    turns = sorted((r for r in rows if r.kind == KIND_TURN), key=lambda r: (r.created_at, r.id), reverse=True)
    unpinned_rank = 0
    for row in turns:
        if row.prompt_uuid in pinned:
            continue
        unpinned_rank += 1
        if unpinned_rank > KEEP_NEWEST or now - row.created_at > MAX_AGE_S:
            out.append(row)
    out += [r for r in rows if r.kind == KIND_SAFETY and now - r.created_at > MAX_AGE_S]
    out += [r for r in rows if r not in out and not os.path.isdir(r.work_tree)]
    return out


def drop(store: CheckpointStore, rows: Iterable[Checkpoint]) -> int:
    gone = []
    for row in rows:
        if os.path.isdir(row.shadow):
            run_git(Path(row.shadow), "update-ref", "-d", row.ref, timeout=GIT_TIMEOUT_S)
        gone.append(row.id)
    store.delete(gone)
    return len(gone)


def prune_session(store: CheckpointStore, session_uuid: str, now: Optional[float] = None) -> int:
    rows = store.for_session(session_uuid)
    return drop(store, doomed(rows, store.pinned_prompts(session_uuid), time.time() if now is None else now))


def purge_session(store: CheckpointStore, session_uuid: str) -> int:
    return drop(store, store.for_session(session_uuid))


def _orphan_refs(store: CheckpointStore, root: Path) -> int:
    wanted = {(r.shadow, r.ref) for s in store.sessions() for r in store.for_session(s)}
    dropped = 0
    for shadow in sorted(root.glob("*.git")) if root.is_dir() else []:
        listed = run_git(shadow, "for-each-ref", "--format=%(refname)", REF_PREFIX, timeout=GIT_TIMEOUT_S)
        orphans = [ref for ref in listed.stdout.split() if (str(shadow), ref) not in wanted] if listed.returncode == 0 else []
        for ref in orphans:
            run_git(shadow, "update-ref", "-d", ref, timeout=GIT_TIMEOUT_S)
        if orphans:
            with repo_lock(shadow):
                run_git(shadow, "gc", "--auto", "--quiet", timeout=GIT_TIMEOUT_S * 4, low_priority=True)
        dropped += len(orphans)
    return dropped


def at_start(store: CheckpointStore, state_root: Path, now: Optional[float] = None) -> int:
    when = time.time() if now is None else now
    removed = sum(prune_session(store, s, when) for s in store.sessions())
    removed += _orphan_refs(store, state_root / SHADOW_DIRNAME)
    scratch = state_root / SHADOW_DIRNAME / SCRATCH_DIRNAME
    if scratch.is_dir():
        for entry in scratch.iterdir():
            try:
                if when - entry.lstat().st_mtime > SCRATCH_MAX_AGE_S:
                    entry.unlink()
            except OSError as exc:
                logger.warning("checkpoint_scratch_sweep_failed", error=str(exc))
    return removed
