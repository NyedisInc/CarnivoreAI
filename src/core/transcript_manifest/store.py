
from __future__ import annotations

import sqlite3
from dataclasses import asdict, fields
from typing import Any, Dict, List, Optional, Sequence

from src.core.db import transaction
from src.core.transcript_manifest import constants as K
from src.core.transcript_manifest.scan import Row, ScanResult

_COLUMNS: Sequence[str] = tuple(f.name for f in fields(Row) if f.name != "id")


def table_present(conn: sqlite3.Connection) -> bool:
    row = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (K.TABLE,)).fetchone()
    return row is not None


def _row(record: Any) -> Row:
    data = {name: record[name] for name in (*_COLUMNS, "id")}
    return Row(**data)


def load_rows(conn: sqlite3.Connection) -> Dict[str, Row]:
    if not table_present(conn):
        return {}
    conn.row_factory = sqlite3.Row
    return {r[0]: Row(*r) for r in conn.execute(f"SELECT {', '.join(_COLUMNS)}, id FROM {K.TABLE}")}


def persist(conn: sqlite3.Connection, result: ScanResult, now: str) -> None:
    placeholders = ", ".join("?" for _ in _COLUMNS)
    updates = ", ".join(f"{c} = excluded.{c}" for c in _COLUMNS if c != "path")
    sql = (f"INSERT INTO {K.TABLE} ({', '.join(_COLUMNS)}) VALUES ({placeholders}) "
           f"ON CONFLICT(path) DO UPDATE SET {updates}")
    with transaction(conn):
        for row in result.changed:
            values = asdict(row)
            conn.execute(sql, tuple(values[c] for c in _COLUMNS))
        roots = sorted(result.complete_roots)
        if roots:
            marks = ", ".join("?" for _ in roots)
            conn.execute(f"UPDATE {K.TABLE} SET last_seen = ? WHERE gone_at IS NULL AND root IN ({marks})",
                         (now, *roots))


def path_for_conversation(conn: sqlite3.Connection, conversation_id: str, family: Optional[str]) -> Optional[str]:
    if not table_present(conn):
        return None
    sql = (f"SELECT path FROM {K.TABLE} WHERE conversation_id = ? AND kind = ? AND gone_at IS NULL"
           + (" AND family = ?" if family else "") + " ORDER BY id LIMIT 1")
    args = (conversation_id, K.KIND_CONVERSATION, *((family,) if family else ()))
    row = conn.execute(sql, args).fetchone()
    return str(row[0]) if row else None


def summary(conn: sqlite3.Connection) -> Dict[str, Any]:
    out: Dict[str, Any] = {"total": 0, "by_status": {s: 0 for s in K.STATUSES}, "by_kind": {k: 0 for k in K.KINDS},
                           "by_family": {}, "dataless": 0, "present_bytes": 0}
    if not table_present(conn):
        return out
    for status, kind, family, dataless, count, size in conn.execute(
            f"SELECT status, kind, family, dataless, COUNT(*), SUM(size) FROM {K.TABLE} "
            "GROUP BY status, kind, family, dataless"):
        out["total"] += count
        out["by_status"][status] = out["by_status"].get(status, 0) + count
        out["by_kind"][kind] = out["by_kind"].get(kind, 0) + count
        out["by_family"][family] = out["by_family"].get(family, 0) + count
        if dataless:
            out["dataless"] += count
        if status != K.STATUS_GONE:
            out["present_bytes"] += int(size or 0)
    return out


def list_rows(conn: sqlite3.Connection, *, status: Optional[str] = None, kind: Optional[str] = None,
              family: Optional[str] = None, conversation_id: Optional[str] = None,
              limit: int = K.DEFAULT_LIST_LIMIT, offset: int = 0) -> List[Dict[str, Any]]:
    if not table_present(conn):
        return []
    clauses: List[str] = []
    args: List[Any] = []
    for column, value in (("status", status), ("kind", kind), ("family", family),
                          ("conversation_id", conversation_id)):
        if value is not None:
            clauses.append(f"{column} = ?")
            args.append(value)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    conn.row_factory = sqlite3.Row
    rows = conn.execute(f"SELECT id, {', '.join(_COLUMNS)} FROM {K.TABLE}{where} "
                        "ORDER BY changed_at DESC, id DESC LIMIT ? OFFSET ?", (*args, limit, offset))
    return [asdict(_row(r)) for r in rows]
