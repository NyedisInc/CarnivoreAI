
from __future__ import annotations

import os
import sqlite3
from typing import List, Sequence, Tuple

import structlog

from src.core.db import table_exists
from src.core.pack.trust_carry import store

logger = structlog.get_logger()

CarriedRow = Tuple[str, str, str, str]


def read_carried(conn: sqlite3.Connection, moved: Sequence[Tuple[int, str, str]]) -> List[CarriedRow]:
    if not table_exists(conn, "pack_carried_trust"):
        return []
    rows: List[CarriedRow] = []
    for project_id, old_root, new_root in moved:
        for folder, uid, install, op in conn.execute(
                "SELECT t.folder, t.project_uid, t.source_install_id, t.op_id FROM pack_carried_trust t "
                "JOIN projects p ON p.uid = t.project_uid WHERE p.id = ?", (project_id,)).fetchall():
            if folder == os.path.realpath(old_root):
                rows.append((new_root, uid, install, op))
    return rows


def record_carried(conn: sqlite3.Connection, rows: Sequence[CarriedRow], *, projects_dir: str) -> int:
    recorded = 0
    for folder, uid, install, op in rows:
        try:
            recorded += bool(store.record(conn, folder, uid, install, op, projects_dir=projects_dir))
        except (sqlite3.Error, OSError) as exc:
            logger.warning("project_move_carried_trust_failed", error=type(exc).__name__)
    logger.info("project_move_carried_trust", rows=len(rows), recorded=recorded)
    return recorded
