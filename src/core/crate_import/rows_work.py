
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import structlog

from src.core.crate_import import idmap as ids
from src.core.crate_import import policy
from src.core.crate_import import rows_write as rw
from src.core.crate_import.keyrules import REF, rule_for
from src.core.crate_import.model import W_DANGLING_REF, W_TASK_FILE_NOT_COPIED
from src.core.inventory.model import MAIN_STORE
from src.core.work.import_rows import import_rows

logger = structlog.get_logger()

PROJECTS = f"{MAIN_STORE}.projects"
SESSIONS = f"{MAIN_STORE}.sessions"
ITEMS = f"{MAIN_STORE}.work_items"
GROUPS = f"{MAIN_STORE}.work_item_groups"
MESSAGES = f"{MAIN_STORE}.work_messages"
INBOX = f"{MAIN_STORE}.work_inbox"
LINEAGE = f"{MAIN_STORE}.work_item_lineage"
EVENTS = f"{MAIN_STORE}.work_card_events"
BLOCKERS = f"{MAIN_STORE}.work_blockers"

TABLES: Tuple[str, ...] = policy.WORK_TABLES
OWNER_LIST = "all"
SWARM_PREFIX = "agent:"
SKIP_SWARM_LIST = "swarm_list"
SKIP_NO_PROJECT = "project_not_here"
GROUP_PLACEHOLDER = -1


def map_list_key(ctx: rw.WriteCtx, value: Any) -> Tuple[Optional[str], str]:
    if value is None:
        return None, SKIP_NO_PROJECT
    text = str(value)
    if text.startswith(SWARM_PREFIX):
        return None, SKIP_SWARM_LIST
    if not text.isdigit():
        return text, ""
    mapped = ctx.idmap.get(PROJECTS, int(text))
    return (str(mapped), "") if mapped is not None else (None, SKIP_NO_PROJECT)


def _text_key(row: Dict[str, Any]) -> Tuple[Any, str]:
    return row.get("created_at"), hashlib.sha256(str(row.get("text") or "").encode("utf-8")).hexdigest()


def _live_keys(ctx: rw.WriteCtx, list_key: str) -> Dict[Tuple[Any, str], int]:
    rows = ctx.conn.execute("SELECT id, created_at, text FROM work_items WHERE list_key = ? AND deleted = 0", (list_key,)).fetchall()
    return {_text_key({"created_at": r["created_at"], "text": r["text"]}): int(r["id"]) for r in rows}


def _lineage_rows(events: Iterable[Dict[str, Any]], older: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    moves = [{"item_id": e["item_id"], "list_key": e.get("list_key"), "at": e.get("at"), "from_state": e.get("from_col", ""),
              "to_state": e.get("to_col", ""), "by": e.get("by"), "detail": e.get("detail")} for e in events if e.get("kind") == "state"]
    covered = {m["item_id"] for m in moves}
    return moves + [dict(o) for o in older if o["item_id"] not in covered]


class _Plan:

    def __init__(self) -> None:
        self.new: Dict[int, Dict[str, Any]] = {}
        self.present: Dict[int, int] = {}
        self.by_list: Dict[str, List[int]] = {}
        self.had_items: Dict[str, bool] = {}
        self.skipped: Dict[str, int] = {}


def _classify_items(ctx: rw.WriteCtx, items: List[Dict[str, Any]]) -> _Plan:
    plan, known, live = _Plan(), ctx.idmap.maps.get(ITEMS, {}), {}
    for source in items:
        row = dict(source)
        mapped, why = map_list_key(ctx, row.get("list_key"))
        if mapped is None:
            plan.skipped[why] = plan.skipped.get(why, 0) + 1
            continue
        old = int(row["id"])
        if str(old) in known and ctx.conn.execute("SELECT 1 FROM work_items WHERE id = ? AND list_key = ? AND deleted = 0",
                                                  (int(known[str(old)]), mapped)).fetchone() is not None:
            plan.present[old] = int(known[str(old)])
            continue
        if mapped not in live:
            live[mapped] = _live_keys(ctx, mapped)
            plan.had_items[mapped] = bool(live[mapped])
        here = live[mapped].get(_text_key(row))
        if here is not None:
            plan.present[old] = here
            continue
        row["list_key"] = mapped
        plan.new[old] = row
        plan.by_list.setdefault(mapped, []).append(old)
    return plan


def _session_ref(ctx: rw.WriteCtx, row: Dict[str, Any], column: str) -> None:
    value = row.get(column)
    rule = rule_for(MAIN_STORE, "work_items", column)
    if not value or rule is None or rule.kind != REF:
        return
    mapped = ids.ref(ctx.conn, ctx.idmap, rule, value)
    if mapped is None:
        ctx.col.warn(W_DANGLING_REF, f"{ITEMS}.{column}")
    row[column] = mapped or ""


def _list_data(ctx: rw.WriteCtx, plan: _Plan, list_key: str, rows: Dict[str, List[Dict[str, Any]]], label: str) -> Dict[str, Any]:
    wanted = set(plan.by_list[list_key])
    groups = [g for g in rows.get(GROUPS, []) if map_list_key(ctx, g.get("list_key"))[0] == list_key]
    items: List[Dict[str, Any]] = []
    restored_group = bool(plan.had_items.get(list_key))
    for old in plan.by_list[list_key]:
        item = dict(plan.new[old])
        _session_ref(ctx, item, "tagged_session_key")
        item["_source_item_id"] = item.get("source_item_id")
        item["source_item_id"] = None
        if restored_group and item.get("group_id") is None:
            item["group_id"] = GROUP_PLACEHOLDER
        items.append(item)
    if restored_group and any(i.get("group_id") == GROUP_PLACEHOLDER for i in items):
        groups.append({"id": GROUP_PLACEHOLDER, "name": label, "position": 1_000_000, "folded": 0, "created_by": "carnivore",
                       "created_at": items[0].get("created_at") or 0.0, "updated_at": items[0].get("updated_at") or 0.0, "deleted": 0})
    entries = [e for e in rows.get(INBOX, []) if map_list_key(ctx, e.get("list_key"))[0] == list_key]
    for entry in entries:
        for raw in _json_ids(entry.get("item_ids")):
            if raw in wanted:
                plan.new[raw]["inbox_id"] = entry["id"]
    for item in items:
        item["inbox_id"] = plan.new[item["id"]].get("inbox_id")
    return {"groups": groups, "items": items,
            "messages": [m for m in rows.get(MESSAGES, []) if m.get("item_id") in wanted],
            "lineage": [m for m in _lineage_rows(rows.get(EVENTS, []), rows.get(LINEAGE, [])) if m["item_id"] in wanted],
            "blockers": [b for b in rows.get(BLOCKERS, []) if b.get("item_id") in wanted],
            "inbox": [e for e in entries if any(i in wanted for i in _json_ids(e.get("item_ids")))]}


def _json_ids(raw: Any) -> List[int]:
    try:
        parsed = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    return [i for i in parsed if isinstance(i, int) and not isinstance(i, bool)] if isinstance(parsed, list) else []


def _count(ctx: rw.WriteCtx, key: str, inserted: int, present: int = 0) -> None:
    counts = ctx.table_counts(key)
    counts.inserted += inserted
    counts.present += present


def _import_lists(ctx: rw.WriteCtx, plan: _Plan, rows: Dict[str, List[Dict[str, Any]]], label: str) -> Tuple[Set[int], Set[int]]:
    made: Set[int] = set()
    messages: Set[int] = set()
    sources: List[Tuple[int, Any]] = []
    for list_key in sorted(plan.by_list):
        data = _list_data(ctx, plan, list_key, rows, label)
        undo = import_rows(ctx.conn, list_key, data, {}, replace_existing=False, files=ctx.files)
        for table, name in ((ITEMS, "item_map"), (GROUPS, "group_map"), (MESSAGES, "message_map")):
            for old, new in undo[name].items():
                ctx.idmap.put(table, old, new)
        ctx.created.setdefault(ITEMS, []).extend(undo["item_ids"])
        made.update(int(k) for k in undo["item_map"])
        messages.update(int(k) for k in undo["message_map"])
        sources += [(item["id"], item["_source_item_id"]) for item in data["items"] if item.get("_source_item_id") is not None]
        _count(ctx, ITEMS, len(undo["item_ids"]))
        _count(ctx, GROUPS, len(undo["group_ids"]))
        _count(ctx, MESSAGES, len(undo["message_map"]))
        _count(ctx, INBOX, len(undo["inbox_ids"]))
        _count(ctx, LINEAGE, len(data["lineage"]))
        _count(ctx, BLOCKERS, len(data["blockers"]))
    for old, source in sources:
        mapped = ctx.idmap.get(ITEMS, source)
        if mapped is not None:
            ctx.conn.execute("UPDATE work_items SET source_item_id = ? WHERE id = ?", (mapped, ctx.idmap.get(ITEMS, old)))
    for name in ctx.files.dropped if ctx.files is not None else []:
        ctx.col.warn(W_TASK_FILE_NOT_COPIED, name)
    return made, messages


def _neutral(key: str, row: Dict[str, Any], ctx: rw.WriteCtx) -> Dict[str, Any]:
    short = key.rpartition(".")[2]
    if short == "work_item_triggers":
        return {**row, "fire_at": None, "paused": 1}
    if short == "work_item_nudges":
        return {**row, "count": 0, "last_at": 0.0, "basis": "", "stalled_at": None}
    if short == "work_sends":
        current = ctx.conn.execute("SELECT v FROM work_meta WHERE k = 'seq'").fetchone()
        return {**row, "cursor": int(current[0]) if current else 0, "target": ""}
    return row


def _children(ctx: rw.WriteCtx, key: str, rows: List[Dict[str, Any]], made: Set[int], messages: Set[int]) -> None:
    short = key.rpartition(".")[2]
    kept: List[Dict[str, Any]] = []
    for source in rows:
        row = dict(source)
        if "item_id" in row and int(row["item_id"]) not in made:
            continue
        if short == "work_message_receipts" and int(row.get("message_id", -1)) not in messages:
            continue
        for column in ("list_key", "project_key"):
            if column in row:
                mapped, why = map_list_key(ctx, row[column])
                if mapped is None:
                    ctx.table_counts(key).skip(why)
                    row = {}
                    break
                row[column] = mapped
        if row:
            kept.append(_neutral(key, row, ctx))
    rw.write_generic(ctx, key, kept)


def write_work(ctx: rw.WriteCtx, sanitized: Dict[str, List[Dict[str, Any]]], label: str) -> None:
    plan = _classify_items(ctx, sanitized.get(ITEMS, []))
    _count(ctx, ITEMS, 0, len(plan.present))
    for reason, n in plan.skipped.items():
        for _ in range(n):
            ctx.table_counts(ITEMS).skip(reason)
    for old, local in plan.present.items():
        ctx.idmap.put(ITEMS, old, local)
    made, messages = _import_lists(ctx, plan, sanitized, label) if plan.by_list else (set(), set())
    handled = {ITEMS, GROUPS, MESSAGES, INBOX, LINEAGE, EVENTS, BLOCKERS}
    for key in TABLES:
        if key in handled:
            continue
        rows = sanitized.get(key, [])
        _children(ctx, key, rows, made, messages)
