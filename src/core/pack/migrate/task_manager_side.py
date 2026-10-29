
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

import structlog

from src.core.pack.migrate import task_manager_history, task_manager_names
from src.core.work import file_refs, tables
from src.core.work.import_rows import import_rows

logger = structlog.get_logger()

CAP_TASK_FILES_PLAN = "pack.task_files_plan"
MAX_PROBED_PARTS = 20000
MAX_PART_CHARS = 65536
PROBE_ITEM = 0


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
    files = file_refs.FileHome(Path(state_dir), roots=file_refs.configured_roots())
    committed = False
    try:
        with closing(storage.connect(True)) as conn, conn:
            undo_record = import_rows(conn, list_key, data, agent_map, replace_existing=True, files=files)
        committed = True
    finally:
        if not committed:
            file_refs.remove_copies(Path(state_dir), files.copied)
    undo_record["task_files"] = dict(files.copied)
    undo_record["task_files_dropped"] = list(files.dropped)
    _notify(list_key)
    return undo_record


def task_file_parts(data: Mapping[str, Any]) -> Tuple[List[str], int]:
    named = [m["parts"] for m in data.get("messages", []) if file_refs.names_files(m.get("parts"))]
    fitting = [text for text in named if len(text) <= MAX_PART_CHARS]
    sent = fitting[:MAX_PROBED_PARTS]
    return sent, len(named) - len(sent)


def dropped_task_files(state_dir: str, parts: List[str]) -> Tuple[List[str], bool]:
    files = file_refs.FileHome(Path(state_dir), roots=file_refs.configured_roots(), decide_only=True)
    try:
        for text in parts:
            files.rewrite_message(text, "", PROBE_ITEM, PROBE_ITEM)
    except (OSError, ValueError, TypeError, AttributeError, RecursionError) as exc:
        logger.warning("pack_plan_task_files_look_failed", error=type(exc).__name__)
        return list(files.dropped), True
    return list(files.dropped), False


def undo(state_dir: str, list_key: str, record: Mapping[str, Any]) -> None:
    storage = _storage(state_dir)
    if not storage.db_path.is_file():
        file_refs.remove_copies(Path(state_dir), record.get("task_files") or {})
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
    file_refs.remove_copies(Path(state_dir), record.get("task_files") or {})
    _notify(list_key)


def counts(state_dir: str, list_key: str) -> Dict[str, int]:
    data = export_list(state_dir, list_key)
    return {"items": len(data["items"]), "messages": len(data["messages"]), "groups": len(data["groups"])}
