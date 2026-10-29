
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, List, Optional, Set

import structlog

from src.core import session_journal_store
from src.core.session_restore_offer import OFFER_OPEN

logger = structlog.get_logger()


def open_offer_candidates(state_dir: Path) -> List[dict]:
    load = session_journal_store.load_journal(state_dir)
    if load.outcome != session_journal_store.LOAD_OK:
        if load.outcome != session_journal_store.LOAD_ABSENT:
            logger.warning("offer_reservation_journal_unread", detail=load.detail, note="offered names are not reserved")
        return []
    offer: Any = load.journal.get("offer")
    if not isinstance(offer, dict) or offer.get("state") != OFFER_OPEN:
        return []
    return [c for c in offer.get("candidates") or [] if isinstance(c, dict)]


def offered_names(state_dir: Path) -> Set[str]:
    return {str(c["tmux_name"]) for c in open_offer_candidates(state_dir) if c.get("tmux_name")}


def offered_project_ids(state_dir: Path, db_path: Optional[Path]) -> Set[int]:
    uuids = [str(c["session_uuid"]) for c in open_offer_candidates(state_dir) if c.get("session_uuid")]
    if not uuids or db_path is None or not db_path.exists():
        return set()
    from src.core.db import DatastoreUnreadableError, column_exists, connect

    marks = ",".join("?" for _ in uuids)
    try:
        with closing(connect(db_path, create=False)) as conn:
            if not column_exists(conn, "sessions", "project_id"):
                return set()
            rows = conn.execute(
                f"SELECT DISTINCT project_id FROM sessions WHERE project_id IS NOT NULL AND session_uuid IN ({marks})", uuids)
            return {int(r[0]) for r in rows}
    except (DatastoreUnreadableError, OSError, sqlite3.Error) as exc:
        logger.warning("offer_reservation_projects_unread", error=str(exc), note="no project is held for the offer")
        return set()
