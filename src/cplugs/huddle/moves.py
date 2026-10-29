
from __future__ import annotations

import os
import shutil
import sqlite3
import stat
from pathlib import Path
from typing import Any, FrozenSet, Mapping, Optional, Tuple

import structlog

from src.cplugs.sdk import ports, task_folders

from src.cplugs.sdk.work import tables
from src.cplugs.huddle import actor_log, blockers, files, lane, lineage, rules, triggers
from src.cplugs.huddle.cards import state_log

logger = structlog.get_logger()

BORN_STATES = (rules.OPEN, rules.TODO)
_BLOCK_EXEMPT = (rules.WAITING, rules.TODO)
BLOCKED, REPEAT_TICK, SUPERSEDED = "blocked", "repeat_tick", "superseded"


def born_state(value: object) -> str:
    state = rules.canonical_state(value) if value not in (None, "") else rules.OPEN
    if state not in BORN_STATES:
        raise rules.TaskManagerInvalid(f"an item is born {' or '.join(BORN_STATES)}, not {value!r}; move it after adding")
    return str(state)


def is_swarm_lane(row: Mapping[str, Any]) -> bool:
    return row["lane"] == lane.SWARM


def checkpoint(conn: sqlite3.Connection, row: Mapping[str, Any], new_state: str, actor: str, act: Optional[Any],
               decided: Optional[lineage.Decided], now: float) -> Tuple[str, Optional[lineage.Decided]]:
    if (actor != rules.CLAUDE or act is not None or decided is not None or is_swarm_lane(row)
            or new_state == row["state"] or new_state in _BLOCK_EXEMPT or not blockers.is_held(conn, row["id"], now)):
        return new_state, decided
    return rules.WAITING, lineage.Decided(lineage.CARNIVORE, BLOCKED)


def was_stopped(decided: Optional[lineage.Decided]) -> bool:
    return decided is not None and decided.by == lineage.CARNIVORE and decided.detail == BLOCKED


def record_stop(conn: sqlite3.Connection, row: Mapping[str, Any], new_state: str, decided: Optional[lineage.Decided], now: float) -> None:
    if was_stopped(decided) and new_state == row["state"]:
        lineage.record(conn, row["id"], row["list_key"], row["state"], new_state, by=lineage.CARNIVORE, now=now, detail=BLOCKED)


def repeating(row: Mapping[str, Any]) -> bool:
    return triggers.rule_of(row["trigger_repeat"], row["id"]) is not None


def repeat_tick(row: Mapping[str, Any], actor: str, new_state: str, decided: Optional[lineage.Decided],
                act: Optional[Any]) -> Tuple[str, Optional[lineage.Decided]]:
    if (actor != rules.JOE or act is not None or decided is not None or new_state not in rules.APPROVED_STATES
            or is_swarm_lane(row) or not repeating(row)):
        return new_state, decided
    return rules.OPEN, lineage.Decided(actor_log.by_for(actor), REPEAT_TICK)


def reply_reopens(row: Mapping[str, Any], *, wait_on_owner: bool = False) -> bool:
    if row["state"] == rules.WAITING:
        return wait_on_owner
    if row["state"] == rules.REVIEW:
        return True
    return row["state"] in rules.APPROVED_STATES and not is_swarm_lane(row)


def supersede_questions(conn: sqlite3.Connection, item_id: int, keep_id: int, seq: int) -> int:
    return conn.execute("UPDATE work_messages SET answered = ?, seq = ? WHERE item_id = ? AND kind = 'question' AND answered = 0 AND id != ?",
                        (rules.ANSWERED_SUPERSEDED, seq, item_id, keep_id)).rowcount


def purge(conn: sqlite3.Connection, item_id: int) -> None:
    for table in (tables.MESSAGES, tables.ITEM_LINEAGE, tables.BLOCKERS, tables.WRITE_ACTORS, tables.ITEM_NUDGES, tables.ITEM_WAITS):
        conn.execute(f"DELETE FROM {table} WHERE item_id = ?", (item_id,))
    state_log.purge(conn, item_id)
    conn.execute("UPDATE work_items SET text = '', note = '', title = NULL, perceived_ask = NULL, review_description = NULL, review_summary = NULL, "
                 "review_link = NULL, review_where = NULL, flag_color = NULL, flag_reason = NULL WHERE id = ?", (item_id,))


def remove_folder(folder: Path) -> bool:
    if not folder.is_dir():
        return False
    try:
        shutil.rmtree(folder)
    except OSError as exc:
        logger.warning("task_manager_item_folder_left", folder=str(folder), error=str(exc)[:200])
        return False
    return True


def thread_file_names(conn: sqlite3.Connection, item_id: int) -> FrozenSet[str]:
    rows = conn.execute(f"SELECT parts FROM work_messages WHERE item_id = ? AND {files.PARTS_SQL}", (item_id,)).fetchall()
    return frozenset(Path(e["path"]).name for r in rows for e in files.entries_of(r["parts"]) if isinstance(e.get("path"), str))


def _unlink_regular(path: Path) -> int:
    try:
        if not stat.S_ISREG(path.lstat().st_mode):
            return 0
        path.unlink()
    except FileNotFoundError:
        return 0
    except OSError as exc:
        logger.warning("task_manager_item_file_left", file=path.name, error=type(exc).__name__)
        return 0
    return 1


def _rmdir_if_empty(folder: Path) -> int:
    ignore = folder / task_folders.GITIGNORE
    aside = folder.with_name(f".{folder.name}.gitignore.removing")
    try:
        left = sorted(p.name for p in folder.iterdir())
        if left not in ([], [task_folders.GITIGNORE]) or (left and ignore.read_bytes() != task_folders.GITIGNORE_BODY):
            return 0
        if left:
            os.rename(ignore, aside)
        try:
            folder.rmdir()
        except OSError:
            if left:
                os.rename(aside, ignore)
            raise
        if left:
            aside.unlink()
    except OSError as exc:
        logger.warning("task_manager_item_folder_left", folder=str(folder), error=type(exc).__name__)
        return 0
    return 1


def _remove_named(root_real: Path, task: Path, named: FrozenSet[str]) -> int:
    removed = 0
    for kind in (task_folders.PASTES, task_folders.ARTIFACTS):
        folder = task / kind
        if not (task_folders.is_real_dir(folder) and task_folders.within(root_real, folder)):
            continue
        removed += sum(_unlink_regular(folder / name) for name in named)
        removed += _rmdir_if_empty(folder)
    return removed


def remove_task_files(item_id: int, store_id: Optional[str] = None, named: FrozenSet[str] = frozenset()) -> int:
    port = ports.get(task_folders.ROOT_PORT)
    root = port.root() if port is not None else None
    if root is None:
        return 0
    root_real, removed = root.resolve(), 0
    for task in task_folders.tasks_for(root, item_id):
        stamp = task_folders.task_store_of(task)
        if stamp is None:
            removed += _remove_named(root_real, task, named)
        elif store_id and stamp == store_id:
            removed += sum(remove_folder(task / kind) for kind in (task_folders.PASTES, task_folders.ARTIFACTS) if not (task / kind).is_symlink())
    return removed
