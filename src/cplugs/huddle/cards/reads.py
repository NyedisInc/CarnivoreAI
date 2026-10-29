
from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, List, Mapping, Optional, Sequence

from src.cplugs.huddle import groups, rules
from src.cplugs.huddle.cards import policy, projection, state_log
from src.cplugs.huddle.cards.columns import CHAT_KINDS
from src.cplugs.huddle.wire import ITEM_COLS

CARD_WHERE = "deleted = 0 AND swarm_ref = '' AND kind NOT IN (" + ", ".join(f"'{k}'" for k in CHAT_KINDS) + ")"
_TITLE_MAX = 120
EVENT_COLS = "at, kind, from_col, to_col, by"


def in_use_ids(conn: sqlite3.Connection, list_key: str) -> set:
    return {r[0] for r in conn.execute(
        "SELECT id FROM work_items WHERE list_key = ? AND deleted = 0 AND (card_origin != '' OR card_parent IS NOT NULL "
        "OR card_holder IS NOT NULL OR card_last_holder IS NOT NULL "
        "OR EXISTS (SELECT 1 FROM work_items c WHERE c.card_parent = work_items.id AND c.deleted = 0))", (list_key,))}


def origin(row: Mapping[str, Any]) -> Dict[str, str]:
    stored = row["card_origin"]
    if stored:
        kind, _, ref = stored.partition(":")
        return {"kind": kind, "ref": ref}
    key = row["created_key"]
    if key == rules.OWNER_KEY:
        return {"kind": "owner", "ref": ""}
    if key and key != rules.SWARM_KEY:
        return {"kind": "session", "ref": key}
    return {"kind": "before_cards", "ref": ""}


def _validation(raw: str) -> Optional[Dict[str, Any]]:
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _stranded_shape(row: sqlite3.Row) -> bool:
    return (origin(row)["kind"] == "agent" and row["state"] == rules.OPEN and projection.column(row) == projection.TODO
            and row["card_paused_mode"] == "" and row["card_archived_at"] is None)


def owner_touched(conn: sqlite3.Connection, rows: Sequence[sqlite3.Row]) -> set:
    ids = [r["id"] for r in rows if _stranded_shape(r)]
    seen: set = set()
    for start in range(0, len(ids), 500):
        chunk = ids[start:start + 500]
        seen.update(r[0] for r in conn.execute(f"SELECT DISTINCT item_id FROM work_card_events WHERE by = 'owner' AND {state_log.NOT_STATE} AND item_id IN ({','.join('?' * len(chunk))})", chunk))
    return seen


def stranded(row: sqlite3.Row, children: Mapping[str, int], owner_seen: bool) -> bool:
    return _stranded_shape(row) and not children.get("total") and not owner_seen


def view(row: sqlite3.Row, *, queue: Optional[int], children: Mapping[str, int], owner_seen: bool = False) -> Dict[str, Any]:
    text = row["text"] or ""
    title = (row["title"] or text.strip().split("\n", 1)[0])[:_TITLE_MAX]
    key = row["list_key"]
    held = row["card_holder"]
    return {
        "id": row["id"], "list_key": key, "project_id": int(key) if key.isdigit() else None, "title": title, "text": text,
        "column": projection.column(row), "state": row["state"], "position": row["position"],
        "queue_index": queue, "group_id": row["group_id"],
        "holder": None if held is None else {"agent_id": held, "name": None, "since": row["card_held_since"],
                                             "started_at": row["card_started_at"], "beat_at": row["card_beat_at"]},
        "legacy_claim": (row["claude_working_by"] or None) if row["claude_working"] and held is None else None,
        "last_holder": row["card_last_holder"], "dealt_to": row["card_dealt_to"], "parent": row["card_parent"],
        "children": dict(children), "origin": origin(row),
        "paused": None if not row["card_paused_mode"] else {"mode": row["card_paused_mode"], "by": row["card_paused_by"], "at": row["card_paused_at"]},
        "mark": None if not row["card_mark"] else {"name": row["card_mark"], "at": row["card_mark_at"]},
        "accepted_at": row["card_accepted_at"], "report_id": row["card_report_id"],
        "pin": {"agent_id": row["card_pin_agent"], "place": bool(row["card_pin_place"])},
        "progress": row["card_progress"], "result": row["card_result"], "handoff": row["card_handoff"],
        "how_to_validate": row["review_description"] or "", "validate_link": row["review_link"] or "",
        "proof": row["card_proof"] or None, "validation": _validation(row["card_validation"]),
        "phone_sent_at": row["phone_sent_at"], "revision": row["revision"],
        "summary": row["card_summary"], "queued": projection.queued(row), "archived_at": row["card_archived_at"],
        "auto_promote": bool(row["card_auto_promote"]), "owner_note": row["card_owner_note"],
        "stranded": stranded(row, children, owner_seen),
        "created_at": row["created_at"], "updated_at": row["updated_at"],
    }


def children_counts(conn: sqlite3.Connection, parent_ids: Sequence[int]) -> Dict[int, Dict[str, int]]:
    out: Dict[int, Dict[str, int]] = {i: {"total": 0, "done": 0, "in_review": 0} for i in parent_ids}
    if not parent_ids:
        return out
    marks = ",".join("?" * len(parent_ids))
    for r in conn.execute(f"SELECT card_parent p, {projection.COLUMN_SQL} AS col, COUNT(*) n FROM work_items "
                          f"WHERE {CARD_WHERE} AND card_parent IN ({marks}) GROUP BY card_parent, col", list(parent_ids)):
        counts = out[r["p"]]
        counts["total"] += r["n"]
        if r["col"] == projection.DONE:
            counts["done"] += r["n"]
        elif r["col"] == projection.REVIEW:
            counts["in_review"] += r["n"]
    return out


def one(conn: sqlite3.Connection, card_id: int) -> Optional[Dict[str, Any]]:
    row = conn.execute(f"SELECT {ITEM_COLS} FROM work_items WHERE id = ? AND {CARD_WHERE}", (card_id,)).fetchone()
    if row is None:
        return None
    siblings = conn.execute(f"SELECT {ITEM_COLS} FROM work_items WHERE list_key = ? AND {CARD_WHERE} {groups.ITEM_ORDER}", (row["list_key"],)).fetchall()
    return view(row, queue=projection.queue_index(siblings).get(card_id), children=children_counts(conn, [card_id])[card_id],
                owner_seen=card_id in owner_touched(conn, [row]))


def many(conn: sqlite3.Connection, list_keys: Sequence[str], *, holder: Optional[int] = None, parent: Optional[int] = None,
         columns: Sequence[str] = ()) -> List[Dict[str, Any]]:
    keys = list(list_keys) or sorted(r[0] for r in conn.execute(f"SELECT DISTINCT list_key FROM work_items WHERE {CARD_WHERE}"))
    rows_by_list = {key: conn.execute(f"SELECT {ITEM_COLS} FROM work_items WHERE list_key = ? AND {CARD_WHERE} {groups.ITEM_ORDER}", (key,)).fetchall()
                    for key in keys}
    flat = [r for key in keys for r in rows_by_list[key]]
    kids = children_counts(conn, [r["id"] for r in flat])
    seen = owner_touched(conn, flat)
    out: List[Dict[str, Any]] = []
    for key in keys:
        places = projection.queue_index(rows_by_list[key])
        for row in rows_by_list[key]:
            card = view(row, queue=places.get(row["id"]), children=kids[row["id"]], owner_seen=row["id"] in seen)
            if ((holder is None or card["holder"] is not None and card["holder"]["agent_id"] == holder)
                    and (parent is None or card["parent"] == parent) and (not columns or card["column"] in columns)):
                out.append(card)
    return out


def wins(conn: sqlite3.Connection, list_keys: Sequence[str], since: float) -> Dict[str, int]:
    if not list_keys:
        return {"through_review_today": 0, "in_review": 0}
    marks = ",".join("?" * len(list_keys))
    through = conn.execute(f"SELECT COUNT(DISTINCT item_id) FROM work_card_events WHERE kind = 'done' AND from_col = 'review' "
                           f"AND at >= ? AND list_key IN ({marks})", [since, *list_keys]).fetchone()[0]
    reviewing = conn.execute(f"SELECT COUNT(*) FROM work_items WHERE {CARD_WHERE} AND list_key IN ({marks}) "
                             f"AND ({projection.COLUMN_SQL}) = 'review'", list(list_keys)).fetchone()[0]
    return {"through_review_today": int(through), "in_review": int(reviewing)}


def policy_read(conn: sqlite3.Connection, op: str, args: Mapping[str, Any]) -> Dict[str, Any]:
    if op == "rules":
        return {"rules": {key: policy.rules(conn, key) for key in args.get("list_keys", ())}}
    if op == "deal":
        row = conn.execute("SELECT * FROM work_card_deals WHERE project_key = ?", (args["project_key"],)).fetchone()
        return {"deal": None if row is None else {**dict(row), "reasons": json.loads(row["reasons"]), "offered_ids": json.loads(row["offered_ids"])}}
    if op == "grants":
        return {"grants": [dict(r) for r in conn.execute("SELECT scope, slots, set_by, set_at, reason FROM work_card_grants ORDER BY scope")]}
    if op == "wins":
        return wins(conn, list(args.get("list_keys", ())), float(args["since"]))
    if op == "dealing":
        key = args["project_key"]
        return {"step": policy.dealing_step_done(conn), "dealing": policy.dealing_on(conn, key), **policy_read(conn, "deal", {"project_key": key})}
    if op == "deals":
        return {"deals": [{**dict(r), "reasons": json.loads(r["reasons"]), "offered_ids": json.loads(r["offered_ids"])}
                          for r in conn.execute("SELECT * FROM work_card_deals WHERE state IN ('waiting', 'delivered') ORDER BY requested_at")]}
    if op == "leases":
        return leases(conn)
    if op == "events":
        return {"events": events(conn, int(args["card_id"]))}
    if op == "events_window":
        return events_window(conn, args["list_keys"], float(args["since"]), float(args["until"]), int(args["limit"]), args.get("item_ids"))
    if op == "waiting":
        return {"waiting": [{"id": r["id"], "list_key": r["list_key"], "dealt_to": r["card_dealt_to"], "at": r["card_mark_at"]} for r in conn.execute(
            f"SELECT id, list_key, card_dealt_to, card_mark_at FROM work_items WHERE {CARD_WHERE} AND card_mark = 'waiting_for_slot' "
            "AND card_dealt_to IS NOT NULL AND card_holder IS NULL AND state = ? AND card_paused_mode = '' ORDER BY card_mark_at, id", (rules.OPEN,))]}
    raise ValueError(f"unknown policy read {op!r}")


def events(conn: sqlite3.Connection, card_id: int) -> List[Dict[str, Any]]:
    return [dict(r) for r in conn.execute(f"SELECT {EVENT_COLS}, detail FROM work_card_events WHERE item_id = ? AND {state_log.NOT_STATE} ORDER BY at, id", (card_id,))]


def events_window(conn: sqlite3.Connection, list_keys: Sequence[str], since: float, until: float, limit: int,
                  item_ids: Optional[Sequence[int]] = None) -> Dict[str, Any]:
    if not list_keys or (item_ids is not None and not item_ids):
        return {"events": [], "truncated": False}
    where = f"list_key IN ({','.join('?' * len(list_keys))}) AND at >= ? AND at < ? AND {state_log.NOT_STATE}"
    params: List[Any] = [*list_keys, since, until]
    if item_ids is not None:
        where += f" AND item_id IN ({','.join('?' * len(item_ids))})"
        params.extend(int(i) for i in item_ids)
    rows = [dict(r) for r in conn.execute(f"SELECT item_id, list_key, {EVENT_COLS} FROM work_card_events WHERE {where} ORDER BY at DESC, id DESC LIMIT ?",
                                          (*params, limit + 1))]
    return {"events": rows[:limit][::-1], "truncated": len(rows) > limit}


def leases(conn: sqlite3.Connection) -> Dict[str, Any]:
    rows = conn.execute(f"SELECT id, list_key, card_holder, card_held_since, card_started_at, card_beat_at, card_refresh_asked_at, card_mark "
                        f"FROM work_items WHERE {CARD_WHERE} AND card_holder IS NOT NULL AND state = ? AND claude_working = 0 "
                        f"AND card_paused_mode = '' ORDER BY id", (rules.OPEN,)).fetchall()
    out = [{"id": r["id"], "list_key": r["list_key"], "holder": r["card_holder"], "held_since": r["card_held_since"],
            "started_at": r["card_started_at"], "beat_at": r["card_beat_at"], "refresh_asked_at": r["card_refresh_asked_at"],
            "mark": r["card_mark"]} for r in rows]
    return {"leases": out, "dealing": {key: policy.dealing_on(conn, key) for key in sorted({r["list_key"] for r in rows})}}


def card_for_report(conn: sqlite3.Connection, report_id: int) -> Optional[Dict[str, Any]]:
    row = conn.execute(f"SELECT id FROM work_items WHERE card_report_id = ? AND {CARD_WHERE} ORDER BY id DESC", (report_id,)).fetchone()
    return None if row is None else one(conn, row["id"])
