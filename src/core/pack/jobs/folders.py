
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import structlog

from src.core.pack.jobs import gitio, guards, paths
from src.core.pack.jobs.store import JobStore
from src.core.pack.jobs.types import JobError

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class SlotLease:

    path: str
    slot: int
    fresh: bool


def busy_count(store: JobStore, project_uid: str) -> int:
    return sum(1 for r in store.slot_rows(project_uid) if r["job_id"])


def _keep_patterns(memo: dict) -> List[str]:
    names = {n for n in guards.DEP_DIR_NAMES if n != "__pycache__"}
    names.update(k for k in memo if k != "override")
    return sorted(names)


def _remove_slot(repo_root: str, path: str) -> None:
    gitio.run(["-C", repo_root, "worktree", "remove", "--force", path], check=False)
    shutil.rmtree(path, ignore_errors=True)
    gitio.run(["-C", repo_root, "worktree", "prune"], check=False)


def acquire(store: JobStore, *, jobs_root: Path, project_uid: str, project_name: str, repo_root: str, commit: str,
            job_id: str, max_slots: int = 3) -> SlotLease:
    claim = store.slot_claim(project_uid, repo_root, lambda n: str(paths.slot_dir(jobs_root, project_name, project_uid, n)), job_id,
                             max_slots=max_slots)
    if claim is None:
        raise JobError("no_free_slot", f"all {max_slots} folders for this project are busy")
    slot, path, fresh = claim
    if not fresh and not os.path.exists(os.path.join(path, ".git")):
        fresh = True
    try:
        if fresh:
            _remove_slot(repo_root, path)
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            gitio.run(["-C", repo_root, "worktree", "add", "--detach", path, commit])
        else:
            memo = next((r["memo"] for r in store.slot_rows(project_uid) if r["path"] == path), {})
            gitio.run(["-C", path, "checkout", "--detach", "-f", commit])
            keep = [a for p in _keep_patterns(memo) for a in ("-e", p)]
            gitio.run(["-C", path, "clean", "-ffdx", *keep])
    except JobError:
        if fresh:
            _remove_slot(repo_root, path)
            store.slot_drop(path)
        else:
            store.slot_free(path)
        raise
    log.info("pack_job_slot_acquired", job_id=job_id, slot=slot, fresh=fresh)
    return SlotLease(path, slot, fresh)


def release(store: JobStore, *, path: str, memo: Optional[dict] = None, keep_hours: float = 0, now: float) -> None:
    store.slot_free(path, memo=memo, keep_until=now + keep_hours * 3600 if keep_hours > 0 else None)


def sweep(store: JobStore, *, now: float, idle_days: float = 7) -> List[str]:
    acted: List[str] = []
    for row in store.slot_rows():
        if row["job_id"]:
            continue
        if row["last_used"] is not None and row["last_used"] < now - idle_days * 86400 and not (row["keep_until"] and row["keep_until"] > now):
            _remove_slot(row["repo_root"], row["path"])
            store.slot_drop(row["path"])
            acted.append(row["path"])
        elif row["keep_until"] is not None and row["keep_until"] <= now:
            store.slot_free(row["path"])
            acted.append(row["path"])
    return acted
