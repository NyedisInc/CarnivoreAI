
from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict

import structlog

from src.core.db import get_meta, set_meta
from src.core.db_models import META_PROJECT_RECONCILE_LAST

logger = structlog.get_logger()


def record_migration(conn: sqlite3.Connection, summary: Dict[str, Any]) -> None:
    set_meta(conn, META_PROJECT_RECONCILE_LAST, json.dumps(summary))


def migration_summary(conn: sqlite3.Connection) -> Dict[str, Any]:
    raw = get_meta(conn, META_PROJECT_RECONCILE_LAST)
    if not raw:
        return {
            "state": "never_run",
            "ok": None,
            "reason": None,
            "cannot_determine": None,
            "notice": None,
        }
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError) as exc:
        logger.error("project_migration_record_unreadable", error=str(exc))
        return {
            "state": "unreadable",
            "ok": None,
            "reason": None,
            "cannot_determine": None,
            "notice": (
                "the projects migration record exists but cannot be read "
                f"({exc}), so what the last migration did CANNOT BE "
                "DETERMINED"
            ),
        }
    parsed["state"] = "ok"
    return parsed


reconcile_summary = migration_summary


__all__ = ["migration_summary", "reconcile_summary", "record_migration"]
