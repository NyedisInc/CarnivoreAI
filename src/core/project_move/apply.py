"""Run a passing move plan: folder, transcript folders, one transaction, the journal.

ORDER AND UNDO. Filesystem first (with ``move_folder``, any missing parent
the plan listed under ``create_parents``, then the folder; then each
transcript folder, renamed whole or merged file by file), then ONE sqlite
transaction. If any of those fails, every filesystem step already done
(renames, folders created, emptied folders removed) is reversed, newest first, and the failure names what was
undone and anything that could not be. The session journal comes last, through
its own writer (``session_journal_task.mutate_journal``); a journal that could
not be updated is reported, never a reason to unwind a committed move.

UPDATE IN PLACE, NEVER RE-CREATE. ``projects.id`` carries sessions, the Task Manager
list, the company and the color, so the row keeps its id and only ``root`` and
``raw_path`` change (runbook gotcha 7).

A RENAME NEVER LANDS ON SOMETHING. POSIX ``rename`` silently replaces an empty
directory, so each target is checked again immediately before its rename.

TRANSCRIPT ROWS FOLLOW THE FOLDER (``transcript_rekey.py``): ``transcript_files`` and
``session_search_live`` (the older index, serving while the cache builds) are re-keyed in the same transaction;
the deep search cache's files under the moved folders are deleted after it commits and re-indexed at the new paths.

THE SWARM'S AGENTS FOLLOW THE FOLDER (``swarm_rows.py``, #1789): ``swarm_agents.repo_dir`` is prefix-rebased in the same transaction.

LEFT ALONE ON PURPOSE (history): plugin cursors, ``time-machine/`` and the retired archive tables.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Mapping, Tuple

import structlog

from src.config import settings
from src.core import resource_push
from src.core.db import table_exists, transaction
from src.core.project_move import carried_trust
from src.core.project_move.claude_side import files_under
from src.core.project_move.ledgers import rewrite_install_rows
from src.core.project_move.swarm_rows import rewrite_agent_dirs
from src.core.project_move.paths import JOURNAL_PATH_KEYS, is_within, prefix_params, prefix_where, rebase
from src.core.project_move.transcript_rekey import forget_moved_in_cache, rekey_transcript_rows
from src.core.project_move.plan import LOCAL_HOST, MovePlan
from src.core.resource_push import topics as resource_topics
from src.core.pack.trust_carry import store as trust_store
from src.core.trail_entry import utc_now

logger = structlog.get_logger()


class ProjectMoveError(Exception):
    pass


class MoveRefused(ProjectMoveError):

    def __init__(self, plan: MovePlan) -> None:
        super().__init__("; ".join(plan.failed()) or "the move plan did not pass")
        self.plan = plan


class MoveBusy(ProjectMoveError):
    pass


_MOVE_LOCK = threading.Lock()


@contextmanager
def one_move_at_a_time() -> Iterator[None]:
    if not _MOVE_LOCK.acquire(blocking=False):
        raise MoveBusy("another project move is running; ask for a new plan when it has finished")
    try:
        yield
    finally:
        _MOVE_LOCK.release()


class MoveFailed(ProjectMoveError):

    def __init__(self, step: str, cause: BaseException, undone: List[Dict[str, str]], undo_errors: List[str]) -> None:
        super().__init__(f"{step} failed: {cause}")
        self.step, self.undone, self.undo_errors = step, undone, undo_errors


def _rename(source: str, target: str) -> None:
    if os.path.lexists(target):
        raise FileExistsError(f"{target} appeared after the plan was made")
    os.rename(source, target)


class UndoLog:

    def __init__(self) -> None:
        self.steps: List[Tuple[str, str, str]] = []

    def rename(self, source: str, target: str) -> None:
        _rename(source, target)
        self.steps.append(("rename", source, target))

    def mkdir(self, folder: str) -> None:
        os.mkdir(folder)
        self.steps.append(("mkdir", folder, ""))

    def makedirs(self, folder: str) -> None:
        missing: List[str] = []
        while folder and not os.path.isdir(folder):
            missing.append(folder)
            folder = os.path.dirname(folder)
        for path in reversed(missing):
            self.mkdir(path)

    def remove_empty_tree(self, folder: str) -> None:
        for dirpath, _dirs, _files in os.walk(folder, topdown=False):
            os.rmdir(dirpath)
            self.steps.append(("rmdir", dirpath, ""))

    def undo(self) -> Tuple[List[Dict[str, str]], List[str]]:
        undone: List[Dict[str, str]] = []
        errors: List[str] = []
        for kind, first, second in reversed(self.steps):
            try:
                if kind == "rename":
                    _rename(second, first)
                    undone.append({"step": kind, "from": second, "to": first})
                elif kind == "mkdir":
                    os.rmdir(first)
                    undone.append({"step": "rmdir", "from": first, "to": ""})
                else:
                    os.mkdir(first)
                    undone.append({"step": "mkdir", "from": first, "to": ""})
            except OSError as exc:
                logger.error("project_move_undo_failed", step=kind, path=first, error=str(exc))
                errors.append(f"could not undo {kind} of {first}: {exc}")
        return undone, errors


def _merge(source: str, target: str, log: UndoLog) -> None:
    for rel in files_under(Path(source)):
        destination = os.path.join(target, rel)
        log.makedirs(os.path.dirname(destination))
        log.rename(os.path.join(source, rel), destination)
    log.remove_empty_tree(source)


def _rewrite_db(conn: sqlite3.Connection, plan: MovePlan) -> Dict[str, int]:
    old, new, stamp = plan.old_root, plan.new_root, utc_now()
    moved = [(plan.project["id"], old, new)] + [(c["id"], c["old_root"], c["new_root"]) for c in plan.children]
    params = {**prefix_params(old), "new": new, "old_len": len(prefix_params(old)["old"])}
    rebased = ":new || substr({col}, :old_len + 1)"
    counts = {"projects": 0, "sessions": 0, "conversation_index": 0, "transcript_files": 0, "search_live": 0, "swarm_agents": 0}
    with transaction(conn):
        for project_id, old_root, new_root in moved:
            trust_store.forget_project(conn, project_id)
            cur = conn.execute(
                "UPDATE projects SET root = ?, raw_path = ?, updated_at = ? WHERE id = ? AND root = ?",
                (new_root, new_root, stamp, project_id, old_root))
            if cur.rowcount != 1:
                raise ProjectMoveError(f"project {project_id} no longer has root {old_root}")
            counts["projects"] += 1
        counts["sessions"] = conn.execute(
            f"UPDATE sessions SET working_dir = {rebased.format(col='working_dir')} "
            f"WHERE host_key = '{LOCAL_HOST}' AND {prefix_where('working_dir')}", params).rowcount
        if table_exists(conn, "conversation_index"):
            counts["conversation_index"] = conn.execute(
                f"UPDATE conversation_index SET working_dir = {rebased.format(col='working_dir')} "
                f"WHERE {prefix_where('working_dir')}", params).rowcount
        counts.update(rewrite_install_rows(conn, old, new))
        counts["swarm_agents"] = rewrite_agent_dirs(conn, old, new)
        counts.update(rekey_transcript_rows(conn, plan.transcript_moves))
    return counts


def rebase_journal(journal: Any, old_root: str, new_root: str) -> int:
    changed = 0
    if isinstance(journal, dict):
        for key, value in journal.items():
            if key in JOURNAL_PATH_KEYS and isinstance(value, str) and value and is_within(value, old_root):
                journal[key] = rebase(value, old_root, new_root)
                changed += 1
            else:
                changed += rebase_journal(value, old_root, new_root)
    elif isinstance(journal, list):
        for item in journal:
            changed += rebase_journal(item, old_root, new_root)
    return changed


def _rewrite_journal(state_dir: Path, old_root: str, new_root: str) -> Dict[str, Any]:
    from src.core.session_journal_task import mutate_journal

    def change(journal: Mapping[str, Any]) -> Tuple[int, bool]:
        count = rebase_journal(journal, old_root, new_root)
        return count, count > 0

    try:
        count = mutate_journal(state_dir, change)
    except OSError as exc:
        logger.warning("project_move_journal_failed", error=str(exc))
        return {"state": "failed", "rewritten": 0, "detail": str(exc)}
    if count is None:
        return {"state": "unreadable", "rewritten": 0}
    return {"state": "updated" if count else "nothing_to_change", "rewritten": count}


def reverse_call(plan: MovePlan) -> Dict[str, Any]:
    notes = ["plan it first (apply false) and quote its fingerprint, as for any move."]
    if not plan.move_folder:
        notes.append("move_folder is false, as it was: move the folder back by hand first.")
    notes.append("sessions run at the new folder since are carried back too, with their transcripts.")
    if any(m["mode"] == "merge" for m in plan.transcript_moves):
        notes.append("a short ~/Development transcript folder merged into the long one stays merged; "
                     "the reverse renames the merged folder whole.")
    if plan.folders_to_create:
        notes.append(f"the folders this move created stay: {', '.join(plan.folders_to_create)}.")
    return {"project": plan.project["id"], "new_root": plan.old_root, "move_folder": plan.move_folder,
            "create_parents": False, "note": " ".join(notes)}


def apply_plan(conn: sqlite3.Connection, plan: MovePlan, *, state_dir: Path) -> Dict[str, Any]:
    if not plan.ok or not plan.new_root:
        raise MoveRefused(plan)
    log = UndoLog()
    step = "folder rename"
    try:
        if plan.move_folder:
            step = "parent folder creation"
            for folder in plan.folders_to_create:
                log.mkdir(folder)
            step = "folder rename"
            log.rename(plan.old_root, plan.new_root)
        step = "transcript folder move"
        for move in plan.transcript_moves:
            if move["mode"] == "merge":
                _merge(move["from"], move["to"], log)
            else:
                log.rename(move["from"], move["to"])
        step = "database update"
        carried = carried_trust.read_carried(
            conn, [(plan.project["id"], plan.old_root, plan.new_root)]
            + [(c["id"], c["old_root"], c["new_root"]) for c in plan.children])
        counts = _rewrite_db(conn, plan)
    except (OSError, sqlite3.Error, ProjectMoveError) as exc:
        undone, undo_errors = log.undo()
        logger.error("project_move_failed", project_id=plan.project["id"], step=step, error=str(exc),
                     undone=len(undone), undo_errors=len(undo_errors))
        raise MoveFailed(step, exc, undone, undo_errors) from exc
    journal = _rewrite_journal(state_dir, plan.old_root, plan.new_root)
    try:
        counts["search_cache"] = forget_moved_in_cache(state_dir, plan.transcript_moves)
    except (OSError, sqlite3.Error) as exc:
        logger.warning("project_move_cache_forget_failed", error=str(exc))
        counts["search_cache"] = 0
    recorded = carried_trust.record_carried(conn, carried, projects_dir=str(settings.get_working_dir()))
    resource_push.notify(resource_topics.PROJECTS)
    result = {"folder_moved": plan.move_folder, "folders_created": list(plan.folders_to_create),
              "transcripts_moved": len(plan.transcript_moves), **counts,
              "journal": journal, "carried_trust": recorded, "reverse": reverse_call(plan)}
    logger.info("project_moved", project_id=plan.project["id"], child_ids=[c["id"] for c in plan.children],
                folder_moved=plan.move_folder, transcripts_moved=len(plan.transcript_moves),
                projects=counts["projects"], sessions=counts["sessions"],
                conversation_index=counts["conversation_index"],
                skill_install_items=counts["skill_install_items"], journal=journal["state"])
    return result
