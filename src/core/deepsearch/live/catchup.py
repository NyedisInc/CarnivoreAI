
from __future__ import annotations

import sqlite3
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set

from src.core.deepsearch import constants as K

SCAN_BYTES: int = 256 * 1024 * 1024
SCAN_FILES: int = 2000


def _backlog_sql(kinds: Iterable[str]) -> tuple:
    from src.core.transcript_manifest import constants as TM

    marks = ", ".join("?" for _ in kinds)
    sql = (f"SELECT t.path, t.source_path, t.kind, t.family, t.conversation_id, t.complete_bytes "
           f"FROM {TM.TABLE} t LEFT JOIN {K.CACHE_LIVE_REF} l ON l.path = t.path "
           f"WHERE t.kind IN ({marks}) AND l.id IS NULL AND t.gone_at IS NULL AND t.dataless = 0 "
           "AND t.complete_bytes > 0 AND t.conversation_id IS NOT NULL AND t.conversation_id != '' "
           "ORDER BY t.mtime_ns DESC, t.path")
    return sql, tuple(kinds)


def backlog(conn: sqlite3.Connection, kinds: Set[str], planned: Mapping[str, Mapping[str, Any]], *,
            budget_bytes: Optional[int] = None, budget_files: Optional[int] = None) -> Dict[str, List[Dict[str, Any]]]:
    budget_bytes = SCAN_BYTES if budget_bytes is None else budget_bytes
    budget_files = SCAN_FILES if budget_files is None else budget_files
    if not kinds or budget_files <= 0:
        return {}
    sql, params = _backlog_sql(sorted(kinds))
    out: Dict[str, List[Dict[str, Any]]] = {}
    used_bytes = used_files = 0
    for path, source_path, kind, family, conv, end in conn.execute(sql, params):
        if path in planned.get(conv, {}):
            continue
        if used_files >= budget_files or (used_files and used_bytes + int(end) > budget_bytes):
            break
        out.setdefault(conv, []).append({"path": path, "source_path": source_path, "file_kind": kind,
                                         "family": family, "start": 0, "end": int(end)})
        used_bytes += int(end)
        used_files += 1
    return out


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
