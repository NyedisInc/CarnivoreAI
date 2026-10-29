
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Sequence, Tuple

import structlog

from src.cplugs.huddle import files as item_files
from src.cplugs.huddle.rules import TaskManagerFileShared

logger = structlog.get_logger()

TOMBSTONE_LINE = "\n[{name} was removed]"
BYTES_DELETED, BYTES_MISSING, BYTES_FAILED = "deleted", "missing", "failed"


def _without_file(raw: str, file_id: str) -> str:
    doc = json.loads(raw)
    doc["files"] = [e for e in doc.get("files", []) if e.get("id") != file_id]
    if not doc["files"]:
        del doc["files"]
    return json.dumps(doc, ensure_ascii=False) if doc else ""


def _set_aside(path: Path, item_id: int, file_id: str) -> Tuple[Optional[str], Optional[Path]]:
    target = item_files.aside_name(path)
    try:
        os.utime(path)
        os.rename(path, target)
    except FileNotFoundError:
        return BYTES_MISSING, None
    except OSError as exc:
        logger.warning("reviewboard_file_aside_failed", item=item_id, file=file_id, error=type(exc).__name__)
        return BYTES_FAILED, None
    return None, target


def _put_back(aside: Path, path: Path, item_id: int, file_id: str) -> None:
    try:
        os.rename(aside, path)
    except OSError as exc:
        logger.error("task_manager_file_restore_failed", item=item_id, file=file_id, error=type(exc).__name__)


def _unlink(path: Path, item_id: int, file_id: str) -> str:
    try:
        path.unlink()
    except FileNotFoundError:
        return BYTES_MISSING
    except OSError as exc:
        logger.warning("reviewboard_file_unlink_failed", item=item_id, file=file_id, error=type(exc).__name__)
        return BYTES_FAILED
    logger.info("reviewboard_file_deleted", item=item_id, file=file_id)
    return BYTES_DELETED


def _settle(first: Optional[str], unlinks: List[str]) -> Optional[str]:
    if first == BYTES_FAILED or BYTES_FAILED in unlinks:
        return BYTES_FAILED
    if BYTES_DELETED in unlinks:
        return BYTES_DELETED
    return BYTES_MISSING if unlinks else first


class Located(NamedTuple):

    path: Optional[Path] = None
    kept: Optional[str] = None
    leftovers: Tuple[Path, ...] = ()


class StoreFiles:

    def forget_file(self, item_id: int, message_id: Optional[int], file_id: str, resolve: Optional[Callable[[], Located]] = None,
                    refuse_shared: bool = False) -> Dict[str, Any]:
        moved: Optional[Path] = None
        committed = False
        with closing(self._connect(True)) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                with conn:
                    row = self._row(conn, item_id)
                    found = resolve() if resolve is not None else Located()
                    rows = conn.execute(f"SELECT id, item_id, text, parts FROM work_messages WHERE {item_files.PARTS_SQL}").fetchall()
                    named = {r["id"]: {e.get("id"): e for e in item_files.entries_of(r["parts"])} for r in rows if r["item_id"] == item_id}
                    targets = [mid for mid, entries in named.items() if file_id in entries and (message_id is None or mid == message_id)]
                    shared = (message_id is not None and any(file_id in entries for mid, entries in named.items() if mid != message_id)) \
                        or self._named_elsewhere(rows, item_id, file_id, found.path)
                    entry = named[targets[0]][file_id] if targets else None
                    if shared and refuse_shared:
                        raise TaskManagerFileShared("another task still names this file, so nothing was deleted")
                    for mid in targets:
                        mine = next(r for r in rows if r["id"] == mid)
                        seq = self._next_seq(conn)
                        conn.execute("UPDATE work_messages SET parts = ?, text = ?, seq = ? WHERE id = ?",
                                     (_without_file(mine["parts"], file_id), mine["text"] + TOMBSTONE_LINE.format(name=named[mid][file_id].get("name", file_id)), seq, mid))
                        conn.execute("UPDATE work_items SET seq = ? WHERE id = ?", (seq, item_id))
                    outcome: Optional[str] = None
                    if not shared and found.kept is None and found.path is not None:
                        outcome, moved = _set_aside(found.path, item_id, file_id)
                committed = True
            finally:
                if moved is not None and not committed:
                    _put_back(moved, found.path, item_id, file_id)
        asides = [*([moved] if moved is not None else []), *(found.leftovers if not shared and found.kept is None else ())]
        outcome = _settle(outcome, [_unlink(a, item_id, file_id) for a in asides])
        if entry is None and outcome is None:
            return {"redacted": False, "shared": shared, "name": None, "bytes": None, "located": found}
        if entry is not None:
            self._commit_notify(row["list_key"])
            logger.info("task_manager_file_forgotten", item=item_id, message=message_id, file=file_id, shared=shared)
        return {"redacted": entry is not None, "shared": shared, "name": entry.get("name") if entry else None, "bytes": outcome, "located": found}

    def _named_elsewhere(self, rows: Sequence[sqlite3.Row], item_id: int, file_id: str, path: Optional[Path]) -> bool:
        if path is None:
            return False
        here = path.resolve()
        base = self._storage.path
        return any((base / e["path"]).resolve() == here for r in rows if r["item_id"] != item_id
                   for e in item_files.entries_of(r["parts"]) if e.get("id") == file_id and isinstance(e.get("path"), str))
