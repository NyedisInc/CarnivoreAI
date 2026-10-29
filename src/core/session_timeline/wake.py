
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, List

from src.core.db_models import SESSION_LIFECYCLE_RUNNING
from src.core.session_timeline.assemble import parse_time


def is_running(db: Path, session_uuid: str) -> bool:
    from src.core.db import DatastoreUnreadableError, connect

    try:
        with closing(connect(db, create=False)) as conn:
            row = conn.execute("SELECT lifecycle, archived_at FROM sessions WHERE session_uuid = ?",
                               (session_uuid,)).fetchone()
    except (DatastoreUnreadableError, sqlite3.Error):
        return False
    return bool(row) and row["lifecycle"] == SESSION_LIFECYCLE_RUNNING and not row["archived_at"]


def close_gaps(answer: Dict[str, Any]) -> Dict[str, Any]:
    gaps: List[Dict[str, Any]] = answer.get("gaps") or []
    starts = sorted(t for g in gaps if (t := parse_time(g["start"])) is not None)
    lives = sorted(t for a in answer.get("attention") or [] if (t := parse_time(a.get("start"))) is not None)
    for gap in gaps:
        start = parse_time(gap["start"])
        if not gap.get("open") or start is None:
            continue
        later = [t for t in starts + lives if t > start]
        gap["end"] = (min(later).isoformat() if later else answer["now"])
        gap["open"] = False
    return answer
