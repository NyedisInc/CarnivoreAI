
from __future__ import annotations

import glob
import os
import sqlite3
from typing import Any, Dict, List

import structlog

from src.core.project_pack import manifest, store
from src.core.project_pack import constants as K
from src.core.project_pack.env import PackEnv
from src.core.project_pack.inventory import top_level_names
from src.core.project_pack.pack import EXPECTED, reverse_moves, unlink_created

logger = structlog.get_logger()


def _staging(root: str, prefix: str) -> List[str]:
    return sorted(glob.glob(os.path.join(glob.escape(root), prefix + "*")))


def _pack_files(root: str, row: Dict[str, Any]) -> List[str]:
    names = [row.get("archive_name") or "", K.MANIFEST_NAME, K.README_NAME]
    partials = [os.path.basename(p) for p in glob.glob(os.path.join(glob.escape(root), "*" + K.PARTIAL_SUFFIX))]
    return [n for n in names + partials if n]


def _back_to_unpacked(conn: sqlite3.Connection, row: Dict[str, Any], root: str, note: str) -> str:
    for staging in _staging(root, K.ORIGINALS_PREFIX):
        moved = [(os.path.join(root, n), os.path.join(staging, n)) for n in sorted(os.listdir(staging))]
        for src, dst in moved:
            if os.path.lexists(src):
                raise OSError(f"cannot put {os.path.basename(src)} back: the name is taken")
        reverse_moves(moved)
        os.rmdir(staging)
    unlink_created(root, _pack_files(root, row))
    store.mark_unpacked(conn, row["project_id"], last_error=note)
    return "unpacked"


def recover_one(conn: sqlite3.Connection, row: Dict[str, Any], project_root: str, env: PackEnv) -> str:
    state, pid = row["state"], row["project_id"]
    if state in (K.STATE_PACKING, K.STATE_VERIFYING):
        return _back_to_unpacked(conn, row, project_root, "interrupted by a restart while packing; nothing was removed")
    if state == K.STATE_RETIRING:
        if _staging(project_root, K.ORIGINALS_PREFIX):
            return _back_to_unpacked(conn, row, project_root, "interrupted by a restart before the originals were "
                                                              "trashed; they were put back")
        manifest.read_sidecar(project_root)
        store.put(conn, pid, state=K.STATE_PACKED, packed_at=row.get("packed_at"), last_error=None)
        return K.STATE_PACKED
    if state == K.STATE_EXTRACTING:
        env.trash(_staging(project_root, K.RESTORE_PREFIX))
        store.put(conn, pid, state=K.STATE_PACKED, last_error="interrupted by a restart while extracting")
        return K.STATE_PACKED
    _, entries = manifest.read_sidecar(project_root)
    for staging in _staging(project_root, K.RESTORE_PREFIX):
        for name in sorted(os.listdir(staging)):
            if not os.path.lexists(os.path.join(project_root, name)):
                os.rename(os.path.join(staging, name), os.path.join(project_root, name))
        os.rmdir(staging)
    missing = [n for n in top_level_names(entries) if not os.path.lexists(os.path.join(project_root, n))]
    if missing:
        raise OSError(f"restore cannot be completed, missing: {missing[:5]}")
    env.trash([os.path.join(project_root, n) for n in _pack_files(project_root, row)
               if os.path.lexists(os.path.join(project_root, n))])
    store.mark_unpacked(conn, pid)
    return "unpacked"


def recover_all(conn: sqlite3.Connection, env: PackEnv | None = None) -> Dict[int, str]:
    env = env or PackEnv()
    out: Dict[int, str] = {}
    for row in store.busy_rows(conn):
        project = conn.execute("SELECT root FROM projects WHERE id = ?", (row["project_id"],)).fetchone()
        if project is None:
            logger.error("project_pack_recover_no_project", project_id=row["project_id"], state=row["state"])
            out[row["project_id"]] = "stuck"
            continue
        try:
            out[row["project_id"]] = recover_one(conn, row, project["root"], env)
            logger.info("project_pack_recovered", project_id=row["project_id"], was=row["state"], now=out[row["project_id"]])
        except (OSError, *EXPECTED) as exc:
            logger.error("project_pack_recover_stuck", project_id=row["project_id"], state=row["state"], error=str(exc))
            out[row["project_id"]] = "stuck"
    return out
