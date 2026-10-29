
from __future__ import annotations

import json
from typing import Any, Hashable, Optional, Tuple

import structlog

from src.api.attach_settle import NO_RESIZE_ATTEMPTED, ResizeOutcome
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
            session_manager.resize_terminal(eff_cols, eff_rows, session_id=session_id)
        except Exception as exc:
            failed = True
            logger.error("negotiated_resize_failed", error=str(exc))

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
