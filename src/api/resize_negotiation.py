
from __future__ import annotations

import asyncio
import json
import weakref
from typing import Any, Hashable, Optional, Tuple

import structlog

from src.api.attach_settle import NO_RESIZE_ATTEMPTED, ResizeOutcome, read_pane_geometry
from src.core.terminal_size import TerminalSizeNegotiator
from src.models import WSMessageType

logger = structlog.get_logger()


def get_negotiator(session_manager: Any) -> TerminalSizeNegotiator:
    negotiator = getattr(session_manager, "_terminal_size_negotiator", None)
    if negotiator is None:
        negotiator = TerminalSizeNegotiator()
        try:
            session_manager._terminal_size_negotiator = negotiator
        except (AttributeError, TypeError):
            logger.debug("negotiator_cache_unavailable")
    return negotiator


class _ResizeSlot:

    __slots__ = ("lock", "last_applied", "__weakref__")

    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.last_applied: Optional[Tuple[int, int]] = None


_RESIZE_SLOTS: "weakref.WeakValueDictionary[str, _ResizeSlot]" = weakref.WeakValueDictionary()

_IN_FLIGHT_RESIZES: "set[asyncio.Task[Any]]" = set()


def _resize_slot(session_id: str) -> _ResizeSlot:
    slot = _RESIZE_SLOTS.get(session_id)
    if slot is None:
        slot = _RESIZE_SLOTS[session_id] = _ResizeSlot()
    return slot


async def _resize_under_lock(
    session_manager: Any,
    session_id: str,
    negotiator: Optional[TerminalSizeNegotiator],
    effective: Tuple[int, int],
) -> None:
    slot = _resize_slot(session_id)
    async with slot.lock:
        target = (negotiator.effective_size(session_id) if negotiator is not None else None) or effective
        if target == slot.last_applied:
            logger.debug("negotiated_resize_coalesced", session_id=session_id, cols=target[0], rows=target[1])
            return
        await asyncio.to_thread(session_manager.resize_terminal, target[0], target[1], session_id=session_id)
        slot.last_applied = target


async def _run_resize_shielded(
    session_manager: Any,
    session_id: str,
    negotiator: Optional[TerminalSizeNegotiator],
    effective: Tuple[int, int],
) -> None:
    task = asyncio.ensure_future(_resize_under_lock(session_manager, session_id, negotiator, effective))
    _IN_FLIGHT_RESIZES.add(task)
    task.add_done_callback(_IN_FLIGHT_RESIZES.discard)
    await asyncio.shield(task)


async def apply_effective_size(
    session_manager: Any,
    session_id: str,
    negotiator: TerminalSizeNegotiator,
    effective: Optional[Tuple[int, int]],
    connection_manager: Any,
    known_pane_size: Optional[Tuple[int, int]] = None,
    departed: bool = False,
) -> Tuple[bool, bool]:
    if effective is None:
        return (False, False)
    eff_cols, eff_rows = effective
    issued = False
    failed = False
    if known_pane_size is not None and tuple(known_pane_size) == (eff_cols, eff_rows):
        logger.debug(
            "negotiated_resize_skipped_pane_already_sized",
            session_id=session_id,
            cols=eff_cols,
            rows=eff_rows,
        )
    else:
        issued = True
        try:
            await _run_resize_shielded(session_manager, session_id, negotiator, (eff_cols, eff_rows))
        except Exception as exc:
            failed = True
            logger.error("negotiated_resize_failed", error=str(exc), error_type=type(exc).__name__, exc_info=True, session_id=session_id)

    await broadcast_size(
        session_id, negotiator, connection_manager, departed=departed)
    return (issued, failed)


async def broadcast_size(
    session_id: str,
    negotiator: TerminalSizeNegotiator,
    connection_manager: Any,
    departed: bool = False,
) -> None:
    client_count = negotiator.client_count(session_id)
    effective = negotiator.effective_size(session_id)
    if effective is None or client_count == 0:
        return
    if (client_count == 1 and not departed and negotiator.master(session_id) is None
            and negotiator.voter_count(session_id) == 1):
        return
    message = json.dumps({
        "type": WSMessageType.TERMINAL_SIZE,
        "cols": effective[0],
        "rows": effective[1],
        "clients": client_count,
        "constrained": client_count > 1,
    })
    await connection_manager.broadcast_to_session(session_id, message)


async def measured_size_frame(backend: Any) -> Optional[str]:
    grid = await read_pane_geometry(backend)
    if grid is None:
        return None
    return json.dumps({
        "type": WSMessageType.TERMINAL_SIZE, "cols": grid[0], "rows": grid[1], "measured": True})


def adopt_grid(
    session_manager: Any,
    session_ids: Any,
    cols: Optional[int],
    rows: Optional[int],
) -> Tuple[Optional[int], Optional[int]]:
    negotiator = get_negotiator(session_manager)
    for session_id in session_ids:
        if negotiator.client_count(session_id):
            held = negotiator.effective_size(session_id)
            return held if held is not None else (None, None)
    return (cols, rows)


async def apply_negotiated_resize(
    session_manager: Any,
    session_id: Optional[str],
    client_key: Hashable,
    cols: int,
    rows: int,
    connection_manager: Any,
    known_pane_size: Optional[Tuple[int, int]] = None,
    hidden: bool = False,
) -> ResizeOutcome:
    if not session_id:
        return NO_RESIZE_ATTEMPTED
    negotiator = get_negotiator(session_manager)
    effective = negotiator.set_client_size(
        session_id, client_key, cols, rows, voting=not hidden)
    if hidden and known_pane_size is not None:
        negotiator.note_pane_size(session_id, *known_pane_size)
    if effective is None and not hidden and known_pane_size is not None:
        held = negotiator.effective_size(session_id)
        if held is not None and tuple(known_pane_size) != tuple(held):
            effective = held
    issued, failed = await apply_effective_size(
        session_manager, session_id, negotiator, effective, connection_manager,
        known_pane_size=known_pane_size,
    )
    target = negotiator.effective_size(session_id)
    if effective is None:
        await broadcast_size(session_id, negotiator, connection_manager)
    return ResizeOutcome(
        target=target,
        issued=issued,
        failed=failed,
    )


async def release_client_resize(
    session_manager: Any,
    session_id: Optional[str],
    client_key: Hashable,
    connection_manager: Any,
) -> None:
    if not session_id:
        return
    negotiator = get_negotiator(session_manager)
    effective = negotiator.remove_client(session_id, client_key)
    if effective is None:
        await broadcast_size(session_id, negotiator, connection_manager, departed=True)
        return
    await apply_effective_size(
        session_manager, session_id, negotiator, effective, connection_manager,
        departed=True,
    )
