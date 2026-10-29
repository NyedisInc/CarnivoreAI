
from __future__ import annotations

import asyncio
import sqlite3
import uuid as uuid_module
from typing import Any, Callable, Optional

import structlog

from src.core.bookmarks import rows, service
from src.core.bookmarks.copy_writer import remove_copy
from src.core.bookmarks.errors import RewindRefused
from src.core.db import DatastoreUnreadableError
from src.core.lineage import constants as LK

logger = structlog.get_logger()

BRANCH_SUFFIX = "(branch)"


def branch_label(title: Optional[str], tmux_name: Optional[str]) -> str:
    from src.core.session_label import label_from_tmux_name

    base = (title or label_from_tmux_name(tmux_name) or "").strip()
    return f"{base}{BRANCH_SUFFIX}" if base else BRANCH_SUFFIX


async def branch(manager: Any, *, session_uuid: str, entry_uuid: str, conversation: Optional[str] = None,
                 preflight: Optional[Callable[[rows.SessionRow], None]] = None) -> dict:
    from src.core.session_fork import stamp_fork_child
    from src.core.session_label import sanitize_tmux_name
    from src.core.session_restart import resume_arguments

    row = await asyncio.to_thread(rows.read_row, session_uuid)
    current = rows.require_bookmarkable(row)
    if preflight is not None:
        preflight(row)
    new_uuid, path = await asyncio.to_thread(service.cut_copy, conversation or current, entry_uuid, row.working_dir)
    label = branch_label(row.title, row.tmux_name)
    try:
        child = await manager.create_session(
            session_id=f"ses_{uuid_module.uuid4().hex[:8]}",
            working_dir=row.working_dir,
            project_name=sanitize_tmux_name(label) or label,
            agent_type=row.agent_type,
            model=row.model,
            agent_extra_args=resume_arguments(new_uuid, family="claude"),
            label=label,
        )
    except Exception:
        remove_copy(path)
        raise
    child_tmux = getattr(child, "tmux_session", None) or ""
    recorded = False
    try:
        recorded = await asyncio.to_thread(
            stamp_fork_child, rows.db_path(), socket=row.tmux_socket or manager.tmux_socket_name(),
            child_tmux=child_tmux, parent_id=row.id, label=label)
    except (DatastoreUnreadableError, sqlite3.Error) as exc:
        logger.warning("bookmark_branch_lineage_failed", session_uuid=session_uuid, error=str(exc))
    source = conversation or current
    cut_recorded = await asyncio.to_thread(
        _record_cut, LK.KIND_FORK, _child_session_uuid(row.tmux_socket or manager.tmux_socket_name(), child_tmux),
        source, new_uuid, entry_uuid)
    logger.info("bookmark_branched", session_uuid=session_uuid, entry=entry_uuid, conversation=new_uuid,
                child=child_tmux, lineage=recorded, split_recorded=cut_recorded)
    return {
        "session": child.model_dump() if hasattr(child, "model_dump") else {},
        "claude_session_uuid": new_uuid,
        "label": label,
        "parent_session_id": row.id,
        "lineage_recorded": bool(recorded),
        "split_recorded": cut_recorded,
    }


async def rewind(manager: Any, *, session_uuid: str, entry_uuid: str, confirm: bool,
                 conversation: Optional[str] = None) -> dict:
    """Restart THIS session's live pane on a copy of its conversation cut at ``entry_uuid``.

    Inputs: manager (SessionManager); session_uuid (str); entry_uuid (str); confirm (bool) - the
      ticked arm box, carried by the request; conversation (str | None) - as :func:`branch`.
    Output: dict - ``claude_session_uuid`` (the copy), ``previous_claude_session_uuid``,
      ``killed_live_pane``, ``resumed_copy`` (the command really carried the copy's uuid),
      ``identity_status``, ``kind``, ``ok``, ``detail``.
    Raises: RewindRefused - no confirm (400), not measured live, a restart already running, the
      row moved, or the ladder refused; the BookmarkError family for the copy.
    """
    from src.core import restart_inflight

    if confirm is not True:
        raise RewindRefused("rewind replaces what is running; tick the arm box to confirm",
                            code="confirm_required", status=400)
    row = await asyncio.to_thread(rows.read_row, session_uuid)
    current = rows.require_bookmarkable(row)
    await _require_live(manager, row)
    try:
        with restart_inflight.claim(row.session_uuid):
            return await _rewind_claimed(manager, row, current, entry_uuid, conversation or current)
    except restart_inflight.RestartInFlightError as exc:
        raise RewindRefused(str(exc), code="restart_in_flight") from exc


async def _require_live(manager: Any, row: rows.SessionRow) -> None:
    from src.core.restart_live_gate import bound_instance_running

    if not row.tmux_name:
        raise RewindRefused("this session has no pane to rewind; branch from here instead", code="not_live")
    live = await asyncio.to_thread(bound_instance_running, rows.db_path(), row.session_uuid,
                                   row.tmux_socket or manager.tmux_socket_name())
    if live is not True:
        raise RewindRefused("this session is not running, so there is nothing to rewind in place; "
                            "branch from here instead", code="not_live")


async def _rewind_claimed(manager: Any, row: rows.SessionRow, current: str, entry_uuid: str, source: str) -> dict:
    from src.core.session_respawn import resume_uuid_in

    new_uuid, path = await asyncio.to_thread(service.cut_copy, source, entry_uuid, row.working_dir)
    if not await asyncio.to_thread(rows.swap_conversation, row.id, current, new_uuid):
        remove_copy(path)
        raise RewindRefused("this session moved to another conversation while the rewind was prepared; "
                            "nothing was restarted", code="row_moved")
    try:
        result = await manager.respawn_session(row.tmux_name, live_restart_confirmed=True)
    except Exception:
        await _undo(row, current, new_uuid, path)
        raise
    killed = bool(result.get("killed_live_pane"))
    if not result.get("ok") and not killed:
        await _undo(row, current, new_uuid, path)
        raise RewindRefused(result.get("detail") or "the restart was refused; nothing changed",
                            code="restart_refused")
    resumed = resume_uuid_in(result.get("command")) == new_uuid
    if not resumed:
        logger.warning("bookmark_rewind_resumed_other", session_uuid=row.session_uuid, expected=new_uuid,
                       command_uuid=resume_uuid_in(result.get("command")))
    recorded = await asyncio.to_thread(_record_cut, LK.KIND_REWIND, row.session_uuid, source, new_uuid, entry_uuid)
    logger.info("bookmark_rewound", session_uuid=row.session_uuid, entry=entry_uuid, conversation=new_uuid,
                previous=current, killed=killed, ok=result.get("ok"), identity=result.get("identity_status"))
    return {
        "claude_session_uuid": new_uuid,
        "previous_claude_session_uuid": current,
        "killed_live_pane": killed,
        "resumed_copy": resumed,
        "identity_status": result.get("identity_status"),
        "kind": result.get("kind"),
        "ok": bool(result.get("ok")),
        "detail": result.get("detail"),
        "lineage_recorded": recorded,
    }


def _child_session_uuid(socket: str, child_tmux: str) -> Optional[str]:
    from contextlib import closing

    from src.core.db import connect
    from src.core.session_fork import newest_anchor_uuid

    if not child_tmux:
        return None
    try:
        with closing(connect(rows.db_path(), create=False)) as conn:
            return newest_anchor_uuid(conn, socket=socket, tmux_name=child_tmux)
    except (DatastoreUnreadableError, sqlite3.Error, OSError) as exc:
        logger.warning("bookmark_branch_child_unresolved", child=child_tmux, error=str(exc))
        return None


def _record_cut(kind: str, session_uuid: Optional[str], source: str, copy: str, entry_uuid: str) -> bool:
    from src.core.lineage import cuts

    via = LK.VIA_BOOKMARK_REWIND if kind == LK.KIND_REWIND else LK.VIA_BOOKMARK_BRANCH
    try:
        return cuts.record_cut(rows.db_path(), kind=kind, source_conversation=source, copy_conversation=copy,
                               session_uuid=session_uuid, entry_uuid=entry_uuid, via=via) == cuts.CUT_WRITTEN
    except (DatastoreUnreadableError, sqlite3.Error, OSError) as exc:
        logger.warning("bookmark_lineage_failed", kind=kind, source=source, copy=copy, error=str(exc))
        return False


async def _undo(row: rows.SessionRow, previous: str, new_uuid: str, path) -> None:
    await asyncio.to_thread(rows.swap_conversation, row.id, new_uuid, previous, None, row.claude_session_uuid_source)
    remove_copy(path)
