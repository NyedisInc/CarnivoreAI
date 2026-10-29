
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

import structlog

from src.core.pack.migrate import task_manager_history, task_manager_names
from src.core.work import tables
from src.core.work.import_rows import import_rows

logger = structlog.get_logger()

def _storage(state_dir: str) -> Any:
    from src.core.work.storage import storage_for  # noqa: PLC0415

    return storage_for(Path(state_dir))


def _notify(list_key: str) -> None:
    from src.core import resource_push

    try:
        resource_push.notify(f"cplug.huddle.list:{list_key}")
    except (RuntimeError, ValueError) as exc:
        logger.warning("pack_migrate_task_manager_notify_failed", error=str(exc))


def _rows(cursor: sqlite3.Cursor) -> List[Dict[str, Any]]:
    return [dict(r) for r in cursor.fetchall()]


def export_list(state_dir: str, list_key: str) -> Dict[str, Any]:
    """The live items (with their messages), groups and history of one list. Output: {items, messages, groups, lineage, blockers, inbox}. BLOCKING.

    Each item's ``state`` is in the wire's retired names (``task_manager_names.wire_state``), so an older build reads it too.
    A machine whose ``huddle.db`` does not exist yet has nothing: the answer is empty, and no file is created.
    Example: export_list("/s", "16") -> {"items": [{"id": 3, "text": "ship it", "state": "done_by_claude", ...}], "messages": [...], "groups": [], ...}
    """
    storage = _storage(state_dir)
    if not storage.db_path.is_file():
        return {"items": [], "messages": [], "groups": [], "lineage": [], "blockers": [], "inbox": []}
    with closing(storage.connect(False)) as conn:
        conn.row_factory = sqlite3.Row
        items = _rows(conn.execute("SELECT * FROM work_items WHERE list_key = ? AND deleted = 0 ORDER BY position, id", (list_key,)))
        ids = [i["id"] for i in items]
        messages: List[Dict[str, Any]] = []
        if ids:
            marks = ",".join("?" * len(ids))
            messages = _rows(conn.execute(f"SELECT * FROM work_messages WHERE item_id IN ({marks}) ORDER BY id", ids))
        groups = _rows(conn.execute("SELECT * FROM work_item_groups WHERE list_key = ? AND deleted = 0 ORDER BY position, id", (list_key,)))
        history = task_manager_history.export_of(conn, items)
    for item in items:
        item["state"] = task_manager_names.wire_state(item["state"], item.get("note"))
    return {"items": items, "messages": messages, "groups": groups, **history}


def import_list(state_dir: str, list_key: str, data: Mapping[str, Any], agent_map: Mapping[int, int]) -> Dict[str, Any]:
    storage = _storage(state_dir)
    with closing(storage.connect(True)) as conn, conn:
        undo_record = import_rows(conn, list_key, data, agent_map, replace_existing=True)
    _notify(list_key)
    return undo_record


def undo(state_dir: str, list_key: str, record: Mapping[str, Any]) -> None:
    storage = _storage(state_dir)
    if not storage.db_path.is_file():
        return
    with closing(storage.connect(True)) as conn, conn:
        task_manager_history.undo(conn, record.get("item_ids", []), record.get("inbox_ids", []))
        for table in (tables.ITEMS, tables.ITEM_GROUPS):
            ids = record.get("item_ids" if table == tables.ITEMS else "group_ids", [])
            for row_id in ids:
                if table == tables.ITEMS:
                    conn.execute("DELETE FROM work_messages WHERE item_id = ?", (row_id,))
                conn.execute(f"DELETE FROM {table} WHERE id = ?", (row_id,))
            for row_id in record.get("replaced_item_ids" if table == tables.ITEMS else "replaced_group_ids", []):
                conn.execute("UPDATE work_meta SET v = v + 1 WHERE k = 'seq'")
                seq = conn.execute("SELECT v FROM work_meta WHERE k = 'seq'").fetchone()[0]
                conn.execute(f"UPDATE {table} SET deleted = 0, seq = ? WHERE id = ?", (seq, row_id))
    _notify(list_key)


def counts(state_dir: str, list_key: str) -> Dict[str, int]:
    data = export_list(state_dir, list_key)
    return {"items": len(data["items"]), "messages": len(data["messages"]), "groups": len(data["groups"])}
