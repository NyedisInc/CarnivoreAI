
from __future__ import annotations

import sqlite3
from typing import Any, Dict, List

import structlog

from src.core.exports import store

logger = structlog.get_logger()


def attach(conn: sqlite3.Connection, groups: List[Dict[str, Any]]) -> None:
    for group in groups:
        group["exported"] = None
    if not groups:
        return
    try:
        pointers = store.pointers_for(conn, [g["conversation_id"] for g in groups])
        bundles = store.bundles_for(conn, {p.bundle_id for p in pointers.values()})
    except sqlite3.OperationalError as exc:
        logger.debug("deepsearch_exports_unavailable", error=str(exc)[:200])
        return
    for group in groups:
        found = pointers.get(group["conversation_id"])
        held = bundles.get(found.bundle_id) if found is not None else None
        if found is not None and held is not None:
            group["exported"] = {"bundle_id": held.bundle_id, "label": held.label,
                                 "exported_at": store.iso_utc(found.exported_at), "local_removed": held.local_removed}
