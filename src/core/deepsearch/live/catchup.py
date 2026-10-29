
from __future__ import annotations

import sqlite3
from typing import Any, Dict, Iterable

from src.core.deepsearch import constants as K

def coverage(conn: sqlite3.Connection, kinds: Iterable[str]) -> Dict[str, Any]:
    from src.core.transcript_manifest import constants as TM

    wanted = sorted(kinds)
    marks = ", ".join("?" for _ in wanted)
    rows = conn.execute(
        f"SELECT t.kind, COUNT(*), SUM(l.id IS NOT NULL), SUM(CASE WHEN l.id IS NULL THEN t.complete_bytes ELSE 0 END) "
        f"FROM {TM.TABLE} t LEFT JOIN {K.CACHE_LIVE_REF} l ON l.path = t.path "
        f"WHERE t.kind IN ({marks}) AND t.gone_at IS NULL AND t.dataless = 0 AND t.complete_bytes > 0 "
        "AND t.conversation_id IS NOT NULL AND t.conversation_id != '' GROUP BY t.kind", wanted).fetchall()
    out: Dict[str, Any] = {K.FILE_CONVERSATION: {"files": 0, "indexed": 0},
                           K.FILE_SUBAGENT: {"files": 0, "indexed": 0}, "backlog_files": 0, "backlog_bytes": 0}
    for kind, files, indexed, behind_bytes in rows:
        out[kind] = {"files": int(files or 0), "indexed": int(indexed or 0)}
        out["backlog_files"] += int(files or 0) - int(indexed or 0)
        out["backlog_bytes"] += int(behind_bytes or 0)
    return out
