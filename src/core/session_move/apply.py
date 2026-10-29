
from __future__ import annotations

import asyncio
import os
import sqlite3
import threading
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional

import structlog

from src.core.session_move import files as move_files
from src.core.session_move.plan import SessionMovePlan, build_plan, read_row
from src.core.session_move.record import MovedRow, SessionMoveRecordError, write_moved_row
from src.core.session_move.source import SOURCE_TEMP

logger = structlog.get_logger()

_MOVE_LOCK = threading.Lock()

LIVE_NEEDS_CONFIRM = "live_needs_confirm"
BUSY = "busy"


class SessionMoveError(Exception):
    pass


class SessionNotFound(SessionMoveError):
    pass


class SessionMoveRefused(SessionMoveError):

    def __init__(self, plan: Optional[SessionMovePlan], code: str, message: str) -> None:
        super().__init__(message)
        self.plan, self.code = plan, code


class SessionMoveFailed(SessionMoveError):

    def __init__(self, step: str, message: str, *, undo_errors: Optional[List[str]] = None,
                 backup: Optional[str] = None) -> None:
        super().__init__(message)
        self.step, self.undo_errors, self.backup = step, list(undo_errors or []), backup


@contextmanager
def one_session_move() -> Iterator[None]:
    from src.core.project_move.apply import MoveBusy, one_move_at_a_time

    if not _MOVE_LOCK.acquire(blocking=False):
        raise SessionMoveRefused(None, BUSY, "another move is running; try again when it has finished")
    try:
        try:
            with one_move_at_a_time():
                yield
        except MoveBusy as exc:
            raise SessionMoveRefused(None, BUSY, "a project move is running; try again when it has finished") from exc
    finally:
        _MOVE_LOCK.release()


def _plan_now(open_conn: Callable[[], sqlite3.Connection], session_uuid: str, *, project_id: Optional[int],
              new_folder: Optional[str], settings: Any, preview: Any) -> SessionMovePlan:
    with closing(open_conn()) as conn:
        row = read_row(conn, session_uuid)
        if row is None:
            raise SessionNotFound(session_uuid)
        return build_plan(conn, row, project_id=project_id, new_folder=new_folder, settings=settings, preview=preview)


def _row_tmux(open_conn: Callable[[], sqlite3.Connection], session_uuid: str) -> Dict[str, Any]:
    with closing(open_conn()) as conn:
        row = read_row(conn, session_uuid)
    if row is None:
        raise SessionNotFound(session_uuid)
    return row


async def plan_move(manager: Any, open_conn: Callable[[], sqlite3.Connection], session_uuid: str, *,
                    project_id: Optional[int], new_folder: Optional[str], settings: Any) -> SessionMovePlan:
    row = await asyncio.to_thread(_row_tmux, open_conn, session_uuid)
    preview = await _preview(manager, row)
    return await asyncio.to_thread(_plan_now, open_conn, session_uuid, project_id=project_id,
                                   new_folder=new_folder, settings=settings, preview=preview)


async def _preview(manager: Any, row: Dict[str, Any]) -> Any:
    """``SessionManager.restart_preview`` for the row, None when it could not be taken (the plan then refuses)."""
    if not row.get("tmux_name"):
        return None
    try:
        return await manager.restart_preview(row["tmux_name"], socket_name=row.get("tmux_socket") or None)
    except (ValueError, OSError, RuntimeError) as exc:
        logger.warning("session_move_preview_failed", tmux_name=row.get("tmux_name"), error=str(exc))
        return None


def pane_folder(tmux_name: str, socket_name: str) -> Optional[str]:
    """Measure the folder the session's pane runs in now, canonical; None when it could not be read. BLOCKING.
    """
    from src.core.tmux_session_cwd import PANE_PATH_FORMAT, probe_session_working_dir

    found = probe_session_working_dir(tmux_name, socket=socket_name, fmt=PANE_PATH_FORMAT)
    return os.path.realpath(found) if found else None


def _carry_files(plan: SessionMovePlan, state_dir: Path) -> Dict[str, Any]:
    dest = Path(plan.destination or "")
    try:
        dest.mkdir(parents=False, exist_ok=True)
    except OSError as exc:
        raise SessionMoveFailed("create_folder", f"could not create {dest}: {exc}") from exc
    if plan.source_kind != SOURCE_TEMP:
        return {"files_moved": [], "backup": None}
    source, inv = Path(plan.source or ""), plan.inventory()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup_dir = state_dir / move_files.BACKUP_DIRNAME / plan.session_uuid / stamp
    try:
        move_files.backup(source, inv, backup_dir, {"session_uuid": plan.session_uuid, "source": str(source),
                                                    "destination": str(dest)})
        moved = move_files.move_files(source, dest, inv)
    except move_files.SessionMoveFilesError as exc:
        raise SessionMoveFailed("move_files", str(exc), undo_errors=exc.undo_errors, backup=str(backup_dir)) from exc
    bad = move_files.verify_moved(source, dest, inv)
    if bad:
        undo = move_files.undo_moves(source, dest, moved)
        raise SessionMoveFailed("verify", f"{len(bad)} file(s) did not arrive intact, first {bad[0]}; moved files put back",
                                undo_errors=undo, backup=str(backup_dir))
    return {"files_moved": moved, "backup": str(backup_dir)}


def _sweep_stragglers(plan: SessionMovePlan) -> Dict[str, List[str]]:
    if plan.source_kind != SOURCE_TEMP:
        return {"moved": [], "left": []}
    source, dest = Path(plan.source or ""), Path(plan.destination or "")
    try:
        late = move_files.inventory(source)
    except OSError as exc:
        logger.warning("session_move_sweep_unread", source=str(source), error=str(exc))
        return {"moved": [], "left": []}
    clashes = set(move_files.collisions(late, dest))
    carry = move_files.Inventory(files={k: v for k, v in late.files.items() if k not in clashes},
                                 dirs=tuple(d for d in late.dirs if d not in clashes))
    try:
        moved = move_files.move_files(source, dest, carry) if carry.files else []
    except move_files.SessionMoveFilesError as exc:
        logger.warning("session_move_sweep_failed", error=str(exc))
        moved = []
    return {"moved": moved, "left": sorted(set(late.files) - set(moved))}


def _follow_in_memory(manager: Any, tmux_name: str, destination: str) -> None:
    registry = getattr(manager, "_registry", None)
    for sid, backend in list(getattr(registry, "backends", {}).items()):
        if getattr(backend, "tmux_session", None) != tmux_name:
            continue
        backend.working_dir = Path(destination)
        session = registry.sessions.get(sid)
        if session is not None:
            session.working_dir = destination


async def apply_move(manager: Any, open_conn: Callable[[], sqlite3.Connection], session_uuid: str, *,
                     project_id: Optional[int], new_folder: Optional[str], settings: Any,
                     confirm_restart_live: bool) -> Dict[str, Any]:
    with one_session_move():
        plan = await plan_move(manager, open_conn, session_uuid, project_id=project_id, new_folder=new_folder,
                               settings=settings)
        if not plan.ok:
            raise SessionMoveRefused(plan, plan.refusals[0]["code"], plan.refusals[0]["message"])
        if plan.kills_live_pane and not confirm_restart_live:
            raise SessionMoveRefused(plan, LIVE_NEEDS_CONFIRM,
                                     "the session is running; confirm that its agent is stopped and resumed in the new folder")
        state_dir = Path(settings.get_state_dir())
        carried = await asyncio.to_thread(_carry_files, plan, state_dir)
        try:
            result = await manager.respawn_session(
                plan.tmux_name, socket_name=plan.tmux_socket or None, live_restart_confirmed=bool(confirm_restart_live),
                require_agent_resume=True, start_directory=plan.destination)
        except Exception:  # noqa: BLE001
            await asyncio.to_thread(move_files.undo_moves, Path(plan.source or ""), Path(plan.destination or ""),
                                    carried["files_moved"])
            raise
        now_in = await asyncio.to_thread(pane_folder, str(plan.tmux_name), str(plan.tmux_socket or ""))
        if now_in != plan.destination:
            undo = await asyncio.to_thread(move_files.undo_moves, Path(plan.source or ""), Path(plan.destination or ""),
                                           carried["files_moved"])
            logger.warning("session_move_respawn_not_in_destination", session_uuid=session_uuid, pane_folder=now_in,
                           ok=result.get("ok"), detail=result.get("detail"))
            raise SessionMoveFailed("restart", f"the session did not restart in the new folder: {result.get('detail')}; "
                                    "files put back", undo_errors=undo, backup=carried["backup"])
        swept = await asyncio.to_thread(_sweep_stragglers, plan)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            moved_row: MovedRow = await asyncio.to_thread(_write_row, open_conn, plan, stamp)
        except (SessionMoveRecordError, sqlite3.Error) as exc:
            raise SessionMoveFailed("record", f"the session runs in {plan.destination} but its row was not updated: {exc}",
                                    backup=carried["backup"]) from exc
        _follow_in_memory(manager, str(plan.tmux_name), str(plan.destination))
    logger.info("session_moved", session_uuid=session_uuid, destination=plan.destination,
                files=len(carried["files_moved"]), late=len(swept["moved"]), project_id=moved_row.project_id)
    return {**plan.to_wire(), "applied": True, "done": {
        "files_moved": len(carried["files_moved"]) + len(swept["moved"]), "left_behind": swept["left"],
        "backup": carried["backup"], "restart_ok": bool(result.get("ok")), "restart_detail": result.get("detail"),
        "conversation": result.get("conversation"), "killed_live_pane": bool(result.get("killed_live_pane")),
        "working_dir": moved_row.working_dir, "project_id": moved_row.project_id,
        "project_created": moved_row.project_created, "conversation_index_rows": moved_row.conversation_rows}}


def _write_row(open_conn: Callable[[], sqlite3.Connection], plan: SessionMovePlan, now: str) -> MovedRow:
    with closing(open_conn()) as conn:
        return write_moved_row(conn, row_id=plan.row_id, destination=str(plan.destination),
                               stored_project_id=None, claude_session_uuid=plan.claude_session_uuid, now=now)
