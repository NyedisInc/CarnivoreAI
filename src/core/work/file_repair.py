
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Sequence, Tuple

import structlog

from src.core.db import transaction
from src.core.work import file_refs
from src.core.work.storage import storage_for
from src.cplugs.sdk import task_folders

logger = structlog.get_logger()


@dataclass
class RepairReport:

    messages: int = 0
    skipped: int = 0
    copies: List[Tuple[str, str]] = field(default_factory=list)
    unresolved: List[str] = field(default_factory=list)
    applied: bool = False


def names_other_item(item_id: int) -> Callable[[Dict[str, Any]], bool]:
    def select(entry: Dict[str, Any]) -> bool:
        path = str(entry.get("path") or "")
        if path.startswith("/"):
            marked = task_folders.task_item_of(Path(path).parent.parent)
            return marked is not None and marked != item_id
        found = file_refs._RELATIVE.match(path)
        return found is not None and int(found.group(1)) != item_id

    return select


def _next_seq(conn: sqlite3.Connection) -> int:
    conn.execute("UPDATE work_meta SET v = v + 1 WHERE k = 'seq'")
    return int(conn.execute("SELECT v FROM work_meta WHERE k = 'seq'").fetchone()[0])


def repair(state: Path, roots: Sequence[Path] = (), apply: bool = False) -> RepairReport:
    storage = storage_for(Path(state))
    report = RepairReport(applied=apply)
    if not storage.db_path.is_file():
        return report
    home = file_refs.FileHome(Path(state), roots=roots, local_files=None, keep_unresolved=True, dry_run=not apply)
    home.local_files = home.files_root
    committed = False
    try:
        with closing(storage.connect(apply)) as conn:
            conn.row_factory = sqlite3.Row
            if apply:
                with transaction(conn):
                    changes = _changes(conn, home)
                    report.skipped = _write(conn, changes)
                committed = True
            else:
                changes = _changes(conn, home)
    finally:
        if apply and not committed:
            file_refs.remove_copies(Path(state), home.copied)
    report.messages, report.copies, report.unresolved = len(changes) - report.skipped, list(home.actions), list(home.unresolved)
    return report


def _write(conn: sqlite3.Connection, changes: List[Tuple[int, int, str, str]]) -> int:
    skipped = 0
    for message_id, item_id, old_parts, new_parts in changes:
        seq = _next_seq(conn)
        if conn.execute("UPDATE work_messages SET parts = ?, seq = ? WHERE id = ? AND parts = ?", (new_parts, seq, message_id, old_parts)).rowcount == 0:
            skipped += 1
            logger.warning("task_file_repair_message_changed", message=message_id)
            continue
        conn.execute("UPDATE work_items SET seq = ? WHERE id = ?", (seq, item_id))
    return skipped


def _changes(conn: sqlite3.Connection, home: file_refs.FileHome) -> List[Tuple[int, int, str, str]]:
    out: List[Tuple[int, int, str, str]] = []
    for row in conn.execute("SELECT id, item_id, text, parts FROM work_messages WHERE parts LIKE '%\"files\"%' ORDER BY id").fetchall():
        item_id = int(row["item_id"])
        new_parts, _text = home.rewrite_message(row["parts"], row["text"], item_id, item_id, names_other_item(item_id))
        try:
            same = json.loads(new_parts) == json.loads(row["parts"])
        except ValueError:
            same = True
        if not same:
            out.append((int(row["id"]), item_id, row["parts"], new_parts))
    return out
