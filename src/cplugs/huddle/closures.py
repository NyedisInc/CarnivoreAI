
from __future__ import annotations

import base64
import json
import sqlite3
from typing import Any, Dict, List, Mapping, Optional, Tuple

from src.cplugs.huddle import lane, rules
from src.cplugs.huddle.cards import state_log
from src.cplugs.huddle.wire import ITEM_COLS, item_dict

CANCELLED_DETAIL = "cancelled"
COMPLETED, CANCELLED = "completed", "cancelled"
DEFAULT_LIMIT, MAX_LIMIT = 25, 100
MAX_TERMS, MAX_TERM_CHARS = 8, 100


class CursorError(ValueError):
    pass


def outcome_of(detail: str) -> str:
    return CANCELLED if detail == CANCELLED_DETAIL else COMPLETED


def closure_of(conn: sqlite3.Connection, item_id: int) -> Optional[Dict[str, Any]]:
    state = conn.execute("SELECT state FROM work_items WHERE id = ? AND deleted = 0", (item_id,)).fetchone()
    if state is None or state["state"] not in rules.APPROVED_STATES:
        return None
    marks = ", ".join("?" for _ in rules.APPROVED_STATES)
    found = conn.execute(f"SELECT id, at, by, detail, from_col FROM work_card_events WHERE item_id = ? AND kind = ? AND to_col IN ({marks}) ORDER BY id DESC LIMIT 1",
                         (item_id, state_log.KIND, *rules.APPROVED_STATES)).fetchone()
    if found is None:
        return {"id": None, "closed_at": None, "closed_by": None, "outcome": COMPLETED, "from_state": "", "latest": False, "known": False}
    newest = conn.execute("SELECT MAX(id) FROM work_card_events WHERE item_id = ? AND kind = ?", (item_id, state_log.KIND)).fetchone()[0]
    return {"id": found["id"], "closed_at": found["at"], "closed_by": found["by"], "outcome": outcome_of(found["detail"]), "from_state": found["from_col"],
            "latest": found["id"] == newest, "known": True}


def encode_cursor(closed_at: Optional[float], item_id: int) -> str:
    return base64.urlsafe_b64encode(json.dumps([closed_at, item_id]).encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> Tuple[Optional[float], int]:
    try:
        at, item_id = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
        if (at is not None and not isinstance(at, (int, float))) or isinstance(item_id, bool) or not isinstance(item_id, int):
            raise ValueError("shape")
        return (None if at is None else float(at)), item_id
    except (ValueError, TypeError) as exc:
        raise CursorError("cursor is not one this list issued") from exc


def _like(term: str) -> str:
    return "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _terms(q: str) -> List[str]:
    return [w[:MAX_TERM_CHARS] for w in (q or "").split()][:MAX_TERMS]


def _search_sql(terms: List[str]) -> Tuple[str, List[str]]:
    sql, params = "", []
    for term in terms:
        pat = _like(term)
        sql += (" AND (i.text LIKE ? ESCAPE '\\' OR i.note LIKE ? ESCAPE '\\' OR COALESCE(i.title, '') LIKE ? ESCAPE '\\' "
                "OR EXISTS (SELECT 1 FROM work_messages m WHERE m.item_id = i.id AND m.text LIKE ? ESCAPE '\\'))")
        params += [pat, pat, pat, pat]
    return sql, params


def page(conn: sqlite3.Connection, *, q: str = "", cursor: Optional[str] = None, limit: int = DEFAULT_LIMIT,
         list_key: Optional[str] = None) -> Dict[str, Any]:
    limit = max(1, min(int(limit), MAX_LIMIT))
    marks = ", ".join("?" for _ in rules.APPROVED_STATES)
    where, params = f"i.state IN ({marks}) AND i.deleted = 0 AND i.lane != ?", [*rules.APPROVED_STATES, lane.SWARM]
    if list_key:
        where, params = where + " AND i.list_key = ?", [*params, list_key]
    search, search_params = _search_sql(_terms(q))
    where, params = where + search, [*params, *search_params]
    if cursor:
        at, last_id = decode_cursor(cursor)
        if at is None:
            where, params = where + " AND c.at IS NULL AND i.id < ?", [*params, last_id]
        else:
            where, params = where + " AND (c.at IS NULL OR c.at < ? OR (c.at = ? AND i.id < ?))", [*params, at, at, last_id]
    rows = conn.execute(
        "SELECT i.id AS item_id, c.id AS closure_id, c.at AS closed_at, c.by AS closed_by, c.detail AS detail, "
        "(c.id = (SELECT MAX(id) FROM work_card_events WHERE item_id = i.id AND kind = ?)) AS latest FROM work_items i "
        f"LEFT JOIN work_card_events c ON c.id = (SELECT MAX(id) FROM work_card_events WHERE item_id = i.id AND kind = ? AND to_col IN ({marks})) "
        f"WHERE {where} ORDER BY (c.at IS NULL), c.at DESC, i.id DESC LIMIT ?",
        [state_log.KIND, state_log.KIND, *rules.APPROVED_STATES, *params, limit + 1]).fetchall()
    more = len(rows) > limit
    rows = rows[:limit]
    wire = {r["id"]: r for r in conn.execute(f"SELECT {ITEM_COLS} FROM work_items WHERE id IN ({', '.join('?' for _ in rows)})", [r["item_id"] for r in rows])} if rows else {}
    items = [{"item": {**item_dict(wire[r["item_id"]]), "thread": []}, "closure": _wire_closure(r)} for r in rows]
    last = rows[-1] if rows else None
    return {"items": items, "next_cursor": encode_cursor(last["closed_at"], last["item_id"]) if more and last is not None else None}


def _wire_closure(row: Mapping[str, Any]) -> Dict[str, Any]:
    known = row["closure_id"] is not None
    return {"id": row["closure_id"], "closed_at": row["closed_at"], "closed_by": row["closed_by"], "outcome": outcome_of(row["detail"] or ""),
            "known": known, "can_undo": known and bool(row["latest"])}
