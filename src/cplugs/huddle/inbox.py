
from __future__ import annotations

import json
from typing import Any, Dict, List, Mapping, Optional


QUEUED, FILING, STUCK, FILED, FALLBACK = "queued", "filing", "stuck", "filed", "fallback"
OPEN_STATUSES = (QUEUED, FILING, STUCK)
ACTIVE_STATUSES = (QUEUED, FILING)
FINAL_STATUSES = (FILED, FALLBACK)
OPEN_SQL = "status IN ('queued', 'filing', 'stuck')"
ACTIVE_SQL = "status IN ('queued', 'filing')"

SELECT_COLS = ("inbox_id, (SELECT i.raw_text FROM work_inbox i WHERE i.id = work_items.inbox_id) AS inbox_text, "
               "EXISTS(SELECT 1 FROM work_inbox i, json_each(i.item_ids) j WHERE i.id = work_items.inbox_id AND j.value = work_items.id) AS inbox_direct")
FIELD = "from_inbox"

FALLBACK_SETTING = "inboxFallbackSeconds"
DEFAULT_FALLBACK_S, MIN_FALLBACK_S, MAX_FALLBACK_S = 120.0, 15.0, 3600.0
POLL_S = 5.0
MAX_FILED_ITEMS = 20
QUOTE_CHARS = 1500
STUCK_CATEGORY = "inbox_stuck"
OWNER = "joe"
REASON_TIMEOUT = "no session filed it in time"
REASON_OWNER_FILED = "the owner chose to file it plainly"


def clamp_fallback(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return DEFAULT_FALLBACK_S
    return min(max(float(value), MIN_FALLBACK_S), MAX_FALLBACK_S)


def armed_at(entry: Mapping[str, Any]) -> float:
    return max(entry["created_at"], entry.get("delivered_at") or 0.0)


def expired(entry: Mapping[str, Any], now: float, wait_s: float) -> bool:
    return now - armed_at(entry) >= wait_s


def ids_of(row: Mapping[str, Any]) -> List[int]:
    try:
        found = json.loads(row["item_ids"] or "[]")
    except ValueError:
        return []
    return [i for i in found if isinstance(i, int)]


def entry_dict(row: Mapping[str, Any]) -> Dict[str, Any]:
    return {"id": row["id"], "list": row["list_key"], "text": row["raw_text"], "author": row["author"],
            "created_at": row["created_at"], "status": row["status"], "delivered_at": row["delivered_at"], "delivered_to": row["delivered_to"],
            "filed_at": row["filed_at"], "item_ids": ids_of(row), "error": row["error"]}


def wire(row: Mapping[str, Any]) -> Dict[str, Any]:
    if "inbox_id" not in row.keys() or row["inbox_id"] is None:
        return {}
    direct = "inbox_direct" in row.keys() and bool(row["inbox_direct"])
    return {FIELD: {"id": row["inbox_id"], "text": row["inbox_text"] or "", "direct": direct}}


def pending_dict(row: Mapping[str, Any]) -> Dict[str, Any]:
    return {"id": row["id"], "text": row["raw_text"], "status": row["status"], "created_at": row["created_at"]}


def lead_line(entry_id: int, text: str) -> str:
    flat = " / ".join(part.strip() for part in text.strip().splitlines() if part.strip())
    quoted = flat if len(flat) <= QUOTE_CHARS else flat[:QUOTE_CHARS - 1].rstrip() + "..."
    return (f"huddle inbox: the owner typed this into the add box; file entry {entry_id} with task_manager_entry_import "
            f"(split it into one item per request, obey a leading backlog, now or ask; see the guide's section on filing inbox entries). "
            f'Raw text: "{quoted}". ')
