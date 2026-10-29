
from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, List, Optional

ACTIONS = ("create", "update", "delete")
_VOLATILE = ("next_fire_at",)
_BOOKKEEPING = frozenset({"revision", "updated_at", "updated_by", "updated_actor", "next_fire_at"})
PAGE_MAX = 100


def snapshot(automation: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if automation is None:
        return None
    return {k: v for k, v in automation.items() if k not in _VOLATILE}


def diff(before: Optional[Dict[str, Any]], after: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    old, new = before or {}, after or {}
    keys = sorted((set(old) | set(new)) - _BOOKKEEPING)
    return [{"field": k, "before": old.get(k), "after": new.get(k)} for k in keys if old.get(k) != new.get(k)]


def record(conn: sqlite3.Connection, automation_id: str, action: str, at: float, actor: Dict[str, Any],
           before: Optional[Dict[str, Any]], after: Optional[Dict[str, Any]]) -> None:
    if action not in ACTIONS:
        raise ValueError(f"unknown change action {action!r}")
    conn.execute("INSERT INTO automation_changes (automation_id, action, at, actor, before, after) VALUES (?,?,?,?,?,?)",
                 (automation_id, action, at, json.dumps(actor),
                  json.dumps(snapshot(before)) if before is not None else None,
                  json.dumps(snapshot(after)) if after is not None else None))


def read(conn: sqlite3.Connection, automation_id: str, limit: int = 50, before_seq: Optional[int] = None) -> List[Dict[str, Any]]:
    sql, args = "SELECT * FROM automation_changes WHERE automation_id = ?", [automation_id]
    if before_seq is not None:
        sql += " AND seq < ?"
        args.append(before_seq)
    rows = conn.execute(sql + " ORDER BY seq DESC LIMIT ?", (*args, max(1, min(limit, PAGE_MAX)))).fetchall()
    out = []
    for row in rows:
        old = json.loads(row["before"]) if row["before"] else None
        new = json.loads(row["after"]) if row["after"] else None
        out.append({"seq": row["seq"], "automation_id": row["automation_id"], "action": row["action"], "at": row["at"],
                    "actor": json.loads(row["actor"]), "before": old, "after": new, "changes": diff(old, new)})
    return out
