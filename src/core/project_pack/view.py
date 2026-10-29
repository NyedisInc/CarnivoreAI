
from __future__ import annotations

import sqlite3
from typing import Any, Dict, Optional

from src.core.project_pack import constants as K
from src.core.project_pack import integrity, store


def storage_view(row: Dict[str, Any], root: Optional[str], progress: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    check = None
    if row["state"] == K.STATE_PACKED and root and not row.get("packed_in"):
        check = integrity.cheap_check(root, row).as_dict()
    return {
        "state": row["state"], "logical_bytes": row.get("logical_bytes"), "archive_bytes": row.get("archive_bytes"),
        "file_count": row.get("file_count"), "packed_at": row.get("packed_at"), "packed_in": row.get("packed_in"),
        "last_error": row.get("last_error"), "accepted_local_only": row.get("accepted_local_only"),
        "progress": progress, "integrity": check,
    }


def storage_by_project(conn: sqlite3.Connection, roots: Dict[int, str],
                       progress_of: Any = None) -> Dict[int, Dict[str, Any]]:
    return storage_from_rows(store.all_rows(conn), roots, progress_of)


def storage_from_rows(rows: Dict[int, Dict[str, Any]], roots: Dict[int, str],
                      progress_of: Any = None) -> Dict[int, Dict[str, Any]]:
    return {pid: storage_view(row, roots.get(pid), progress_of(pid) if progress_of else None)
            for pid, row in rows.items()}
