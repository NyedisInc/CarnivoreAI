
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
    """What the last projects migration did, for the UI.

    Description: three outcomes, not two. ``ok`` means a record was
      found and parsed; ``never_run`` means this database has never
      recorded one, which is a different fact from a clean run; and
      ``unreadable`` means a record exists and could not be parsed,
      which is a different fact again and must never render as either
      neighbour.
    Inputs: conn (sqlite3.Connection).
    Output: dict - the stored summary with a ``state`` key added, or a
      marker naming why there is no summary.
    Example: migration_summary(conn)["state"] -> "ok"
    """
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
