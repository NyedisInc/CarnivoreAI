
from __future__ import annotations

import sqlite3
from typing import Any, Dict, Mapping, Optional

from src.core.pack.migrate import task_manager_history, task_manager_names
from src.core.work import tables
from src.core.work.file_refs import FileHome

_NOT_COPIED = frozenset({"id", "list_key", "created_seq", "seq", "attention_seq", "seen_seq", "joe_seq", "claude_read_seq", "info_seq",
                         "call_seq", "claude_working", "claude_working_by", "group_id", "forked_from", "card_parent", "card_report_id",
                         "from_project_id", "card_holder", "card_last_holder", "card_dealt_to", "card_paused_by", "card_pin_agent",
                         "inbox_id"})
_AGENT_COLS = ("card_holder", "card_last_holder", "card_dealt_to", "card_paused_by", "card_pin_agent")


def import_rows(conn: sqlite3.Connection, list_key: str, data: Mapping[str, Any], agent_map: Mapping[int, int], *,
                replace_existing: bool, files: Optional[FileHome] = None) -> Dict[str, Any]:
    undo: Dict[str, Any] = {"item_ids": [], "group_ids": [], "replaced_item_ids": [], "replaced_group_ids": [], "inbox_ids": [],
                            "item_map": {}, "group_map": {}, "message_map": {}}
    previous_factory = conn.row_factory
    conn.row_factory = sqlite3.Row
    try:
        have = {r[1] for r in conn.execute("PRAGMA table_info(work_items)")}
        have_msg = {r[1] for r in conn.execute("PRAGMA table_info(work_messages)")}
        have_grp = {r[1] for r in conn.execute("PRAGMA table_info(work_item_groups)")}

        def next_seq() -> int:
            conn.execute("UPDATE work_meta SET v = v + 1 WHERE k = 'seq'")
            return int(conn.execute("SELECT v FROM work_meta WHERE k = 'seq'").fetchone()[0])

        for table, key in (((tables.ITEMS, "replaced_item_ids"), (tables.ITEM_GROUPS, "replaced_group_ids")) if replace_existing else ()):
            live = [r[0] for r in conn.execute(f"SELECT id FROM {table} WHERE list_key = ? AND deleted = 0", (list_key,))]
            for row_id in live:
                conn.execute(f"UPDATE {table} SET deleted = 1, seq = ? WHERE id = ?", (next_seq(), row_id))
            undo[key] = live
        group_map: Dict[int, int] = {}
        for g in data.get("groups", []):
            cols = [c for c in g if c in have_grp and c not in ("id", "list_key", "seq")]
            seq = next_seq()
            cur = conn.execute(f"INSERT INTO work_item_groups (list_key, seq, {', '.join(cols)}) VALUES (?, ?, {', '.join('?' * len(cols))})",
                               (list_key, seq, *[g[c] for c in cols]))
            group_map[g["id"]] = int(cur.lastrowid)
            undo["group_map"][str(g["id"])] = int(cur.lastrowid)
            undo["group_ids"].append(int(cur.lastrowid))
        item_map: Dict[int, int] = {}
        states: Dict[int, str] = {}
        for item in data.get("items", []):
            seq = next_seq()
            values = {c: v for c, v in item.items() if c in have and c not in _NOT_COPIED}
            values.update(list_key=list_key, created_seq=seq, seq=seq, group_id=group_map.get(item.get("group_id")))
            if "state" in values:
                values["state"] = task_manager_names.current_state(values["state"])
            if "lane" in have and "lane" not in item:
                values["lane"] = task_manager_names.lane_of(item, list_key)
            for col in _AGENT_COLS:
                if col in have:
                    values[col] = agent_map.get(item.get(col)) if item.get(col) is not None else None
            cur = conn.execute(f"INSERT INTO work_items ({', '.join(values)}) VALUES ({', '.join('?' * len(values))})", tuple(values.values()))
            item_map[item["id"]] = int(cur.lastrowid)
            undo["item_map"][str(item["id"])] = int(cur.lastrowid)
            states[int(cur.lastrowid)] = str(values.get("state") or "open")
            undo["item_ids"].append(int(cur.lastrowid))
        for item in data.get("items", []):
            for col in ("forked_from", "card_parent"):
                old = item.get(col)
                if old in item_map and col in have:
                    conn.execute(f"UPDATE work_items SET {col} = ? WHERE id = ?", (item_map[old], item_map[item["id"]]))
        for msg in data.get("messages", []):
            if msg["item_id"] not in item_map:
                continue
            msg = dict(msg)
            if files is not None and msg.get("parts"):
                msg["parts"], msg["text"] = files.rewrite_message(msg["parts"], msg.get("text") or "", msg["item_id"], item_map[msg["item_id"]])
            cols = [c for c in msg if c in have_msg and c not in ("id", "item_id", "seq")]
            cur = conn.execute(f"INSERT INTO work_messages (item_id, seq, {', '.join(cols)}) VALUES (?, ?, {', '.join('?' * len(cols))})",
                               (item_map[msg["item_id"]], next_seq(), *[msg[c] for c in cols]))
            if "id" in msg:
                undo["message_map"][str(msg["id"])] = int(cur.lastrowid)
        undo.update(task_manager_history.import_into(conn, list_key, data, item_map, states))
    finally:
        conn.row_factory = previous_factory
    return undo
