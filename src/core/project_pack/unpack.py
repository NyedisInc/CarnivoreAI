
from __future__ import annotations

import os
import sqlite3
from typing import Callable, List, Optional

import structlog

from src.core.project_pack import archive_io, inventory, manifest, store, verify
from src.core.project_pack import constants as K
from src.core.project_pack.env import PackEnv
from src.core.project_pack.integrity import full_check
from src.core.project_pack.jobs import Progress
from src.core.project_pack.pack import EXPECTED, PackError, move_entries, stamp_now
from src.core.project_pack.plan import PackPlan
from src.core.trail_entry import utc_now

logger = structlog.get_logger()


def run_unpack(open_conn: Callable[[], sqlite3.Connection], plan: PackPlan, env: PackEnv, progress: Progress,
               job_id: str) -> None:
    conn = open_conn()
    pid, root = plan.project["id"], plan.root
    staging = os.path.join(root, K.RESTORE_PREFIX + stamp_now())
    restored = False
    try:
        row = store.get(conn, pid) or {}
        store.put(conn, pid, state=K.STATE_EXTRACTING, job_id=job_id, job_started_at=utc_now(), last_error=None)
        doc, entries = manifest.read_sidecar(root)
        progress.set_phase("checking the archive", int(row.get("archive_bytes") or 0))
        verdict = full_check(root, row, doc["archive"]["sha256"])
        if not verdict.ok:
            raise PackError(verdict.message)
        progress.set_phase("extracting")
        os.mkdir(staging)
        archive_io.extract_archive(os.path.join(root, row["archive_name"]), staging)
        progress.set_phase("verifying", sum(e.size for e in entries if e.kind == inventory.KIND_FILE))
        verify.verify_tree(staging, entries, progress.add)
        store.put(conn, pid, state=K.STATE_RESTORING)
        progress.set_phase("moving files into place")
        moved = move_entries(staging, root, inventory.top_level_names(entries))
        restored = True
        os.rmdir(staging)
        _finish(conn, plan, env, row, moved)
    except EXPECTED as exc:
        _fail(conn, pid, env, staging, restored, f"{type(exc).__name__}: {exc}")
    except BaseException as exc:  # noqa: BLE001
        _fail(conn, pid, env, staging, restored, f"unexpected {type(exc).__name__}: {exc}")
        raise
    finally:
        conn.close()


def _finish(conn: sqlite3.Connection, plan: PackPlan, env: PackEnv, row: dict, moved: List) -> None:
    root, pid = plan.root, plan.project["id"]
    try:
        env.trash([os.path.join(root, n) for n in (row["archive_name"], K.MANIFEST_NAME, K.README_NAME)])
    except EXPECTED as exc:
        logger.error("project_unpack_trash_failed", project_id=pid, error=str(exc))
        _mark_unpacked_with_children(conn, pid, f"unpacked, but the pack files could not be moved to the Trash: {exc}")
        return
    _mark_unpacked_with_children(conn, pid)
    logger.info("project_unpacked", project_id=pid, entries=len(moved))


def _mark_unpacked_with_children(conn: sqlite3.Connection, pid: int, last_error: Optional[str] = None) -> None:
    for child in store.children_of(conn, pid):
        store.mark_unpacked(conn, child)
    store.mark_unpacked(conn, pid, last_error=last_error)


def _fail(conn: sqlite3.Connection, pid: int, env: PackEnv, staging: str, restored: bool, reason: str) -> None:
    if restored:
        logger.error("project_unpack_failed_after_restore", project_id=pid, reason=reason)
        _mark_unpacked_with_children(conn, pid, reason)
        return
    if os.path.isdir(staging):
        try:
            env.trash([staging])
        except EXPECTED as exc:
            reason += f" (the extraction folder {os.path.basename(staging)} could not be trashed: {exc})"
    store.put(conn, pid, state=K.STATE_PACKED, last_error=reason)
    logger.error("project_unpack_failed", project_id=pid, reason=reason)

