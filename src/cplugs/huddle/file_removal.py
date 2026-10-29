
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional

import structlog

from src.cplugs.huddle import files, store_identity, task_files, task_sweep
from src.cplugs.huddle import service
from src.cplugs.huddle.rules import (OWNER_KEY, TaskManagerBytesNotRemoved, TaskManagerFileOnBoard, TaskManagerFileShared, TaskManagerFileUnsafe,
                                     TaskManagerNotAttacher, TaskManagerNotFound)
from src.cplugs.huddle.store_files import BYTES_DELETED, BYTES_FAILED, Located
from src.cplugs.sdk import CplugContext, board_files, task_folders

logger = structlog.get_logger()

DELETED, MISSING = "deleted", "missing"


class Naming(NamedTuple):

    message_id: int
    author_key: str
    entry: Dict[str, Any]


def naming_messages(ctx: CplugContext, item_id: int, file_id: str) -> List[Naming]:
    with closing(ctx.storage.connect(False)) as conn:
        if not files.has_messages(conn):
            return []
        rows = conn.execute(f"SELECT id, author_key, parts FROM work_messages WHERE item_id = ? AND {files.PARTS_SQL} ORDER BY id", (int(item_id),)).fetchall()
    return [Naming(r["id"], r["author_key"] or "", e) for r in rows for e in files.entries_of(r["parts"]) if e.get("id") == file_id]


def require_attacher(named: List[Naming], agent_key: str) -> None:
    attacher = named[0].author_key if named else ""
    if not agent_key or agent_key == OWNER_KEY or attacher != agent_key:
        raise TaskManagerNotAttacher("only the owner or the agent that attached this file may delete it, because deleting removes the file")


def require_sole_author(named: List[Naming], agent_key: str) -> None:
    if any(n.author_key != agent_key for n in named):
        raise TaskManagerFileShared("the owner or another author also names this file on the task, so only the owner can delete it")


def require_not_on_board(item_id: int, file_id: str) -> None:
    port = board_files.port()
    if port is None:
        return
    try:
        listed = port.lists_file(item_id, file_id)
    except OSError as exc:
        raise _unsafe("a review board's attachment list could not be read to check it") from exc
    if listed:
        raise TaskManagerFileOnBoard("a review board lists this file. Remove it from the board with task_manager_board_attachment_remove (or the board's remove key); that deletes the file too")


def _unsafe(why: str) -> TaskManagerFileUnsafe:
    return TaskManagerFileUnsafe(f"the file was not deleted and nothing changed: {why}")


def _check_task_folder(path: Path, item_id: int, own_store: Optional[str]) -> None:
    root = task_files.root_now()
    kind_dir, task = path.parent, path.parent.parent
    if root is None or kind_dir.name not in task_sweep.SWEPT_KINDS:
        raise _unsafe("it is not in this task's own pastes or artifacts folder under the Task Manager folder")
    if not (task_folders.is_real_dir(kind_dir) and task_folders.is_real_dir(task) and task_folders.within(root.resolve(), path)):
        raise _unsafe("its folder is a link or lies outside the Task Manager folder")
    if task_folders.task_item_of(task) != item_id:
        raise _unsafe("its folder belongs to another task")
    stamp = task_folders.task_store_of(task)
    if stamp is not None and stamp != own_store:
        raise _unsafe("its folder was made by another Task Manager store")


def _the_file(ctx: CplugContext, item_id: int, file_id: str, folders: List[Path]) -> Optional[Path]:
    found = files.candidates(ctx.storage, item_id, file_id, folders)
    if any(p.is_symlink() or not p.is_file() for p in found):
        raise _unsafe("a link or something that is not a regular file has its name")
    if len(found) > 1:
        raise _unsafe("more than one stored file has this id")
    return found[0] if found else None


def _located(ctx: CplugContext, item_id: int, file_id: str, record: Optional[Dict[str, Any]], agent_key: Optional[str] = None) -> Located:
    if agent_key is not None:
        require_sole_author(naming_messages(ctx, item_id, file_id), agent_key)
    folders = task_files.search_dirs(item_id)
    path = _the_file(ctx, item_id, file_id, folders)
    own_store = store_identity.of(ctx.storage)
    if path is not None:
        if path.parent != files.item_dir(ctx.storage, item_id):
            _check_task_folder(path, item_id, own_store)
        if record is None and not task_sweep.STORED_NAME.match(path.name):
            raise _unsafe("it does not have the name the Task Manager gives a stored file")
        try:
            wrong = files.mismatch(path, file_id, record["name"], record["size"], None) if record is not None else None
        except OSError as exc:
            raise _unsafe("it could not be read to check it") from exc
        if wrong:
            raise _unsafe(wrong)
    aside = files.leftovers(ctx.storage, item_id, file_id, folders)
    for left in aside:
        if left.parent != files.item_dir(ctx.storage, item_id):
            _check_task_folder(left, item_id, own_store)
    return Located(path, None, tuple(aside))


def remove(ctx: CplugContext, item_id: int, file_id: str, *, agent_key: Optional[str] = None) -> Dict[str, Any]:
    if not files.ID_PATTERN.match(file_id or ""):
        raise TaskManagerNotFound("no such file")
    named = naming_messages(ctx, item_id, file_id)
    if agent_key is not None:
        require_attacher(named, agent_key)
        require_sole_author(named, agent_key)
    require_not_on_board(item_id, file_id)
    record = named[0].entry if named else None
    try:
        outcome = service.store(ctx).forget_file(item_id, None, file_id, lambda: _located(ctx, item_id, file_id, record, agent_key), refuse_shared=True)
    except (sqlite3.Error, OSError) as exc:
        logger.warning("task_manager_file_remove_failed", item=item_id, file=file_id, error=type(exc).__name__)
        raise TaskManagerBytesNotRemoved("the file could not be removed because the Task Manager could not be written; try again") from exc
    return _answer(item_id, file_id, record, outcome)


def _answer(item_id: int, file_id: str, record: Optional[Dict[str, Any]], outcome: Dict[str, Any]) -> Dict[str, Any]:
    located: Located = outcome["located"]
    if outcome["bytes"] == BYTES_FAILED:
        raise TaskManagerBytesNotRemoved("the file was taken off the thread but could not be removed from disk; call again to finish")
    if not outcome["redacted"] and outcome["bytes"] is None and located.path is None and not located.leftovers:
        raise TaskManagerNotFound("no such file")
    state = DELETED if outcome["bytes"] == BYTES_DELETED else MISSING
    logger.info("task_manager_file_removed_by_request", item=item_id, file=file_id, bytes=state, redacted=outcome["redacted"])
    return {"item": item_id, "file": file_id, "name": (record or {}).get("name"), "redacted": outcome["redacted"], "bytes": state}


__all__ = ["DELETED", "MISSING", "Naming", "naming_messages", "remove", "require_attacher", "require_not_on_board", "require_sole_author"]
