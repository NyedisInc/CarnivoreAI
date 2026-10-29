
from __future__ import annotations

import asyncio
import sqlite3
import threading
from contextlib import closing
from typing import TYPE_CHECKING, Callable, Literal, Optional

import structlog

from src.core import setup_state
from src.core.computers import store

if TYPE_CHECKING:
    from src.core.computers.join_job import JoinJob

FirstRunState = Literal["unpaired", "join_pending", "joined", "paired", "undetermined"]

log = structlog.get_logger(__name__)

_lock = threading.Lock()
_join_running = False
_rebind_requested = False


def set_join_running(running: bool) -> None:
    global _join_running
    with _lock:
        _join_running = running


def request_rebind() -> None:
    global _rebind_requested
    with _lock:
        _rebind_requested = True


def rebind_requested() -> bool:
    with _lock:
        return _rebind_requested


def has_provisional_main() -> bool:
    return any(r.role == "main" and r.provisional for r in store.CACHE.rows())


def is_member() -> bool:
    return setup_state.current_setup_state().joined is True


def first_run_state() -> FirstRunState:
    state = setup_state.current_setup_state()
    if state.joined is True:
        return "joined"
    if state.joined is None:
        return "undetermined"
    with _lock:
        running = _join_running
    if running or has_provisional_main():
        return "join_pending"
    for check in state.checks:
        if check.key == "totp_paired":
            if check.passed is None:
                return "undetermined"
            return "paired" if check.passed or state.pack_left else "unpaired"
    return "undetermined"


def start_join(code: Optional[str], link: Optional[str], candidate_fid: Optional[str] = None, *, origin: str,
               totp_ok: bool) -> "JoinJob":
    from src.core.computers import join_job  # noqa: PLC0415

    return join_job.start_join(code, link, candidate_fid, origin=origin, totp_ok=totp_ok)


async def forget(iid: str, *, notify_peer: bool) -> bool:
    from src.core.computers import runtime  # noqa: PLC0415

    rt = runtime.active()
    if rt is None:
        raise RuntimeError("the computers runtime is not running")
    return await rt.forget(iid, notify_peer=notify_peer)


_REMOVED_LISTENERS: list[Callable[[str], None]] = []


def add_removed_listener(listener: Callable[[str], None]) -> None:
    _REMOVED_LISTENERS.append(listener)


async def _forget_pairing_removed(iid: str) -> None:
    await _drop_pairing_row(iid)
    for listener in list(_REMOVED_LISTENERS):
        try:
            await asyncio.to_thread(listener, iid)
        except (OSError, RuntimeError, ValueError) as exc:
            log.warning("computers_removed_listener_failed", error_type=type(exc).__name__)


async def _drop_pairing_row(iid: str) -> None:
    from src.core.computers import runtime  # noqa: PLC0415

    rt = runtime.active()
    if rt is None:
        from src.api import peer_auth  # noqa: PLC0415

        def drop() -> None:
            with closing(peer_auth.open_db()) as conn:
                store.delete(conn, iid)

        try:
            await asyncio.to_thread(drop)
        except sqlite3.Error as exc:
            log.warning("computers_forget_fallback_failed", error_type=type(exc).__name__)
        return
    if await asyncio.to_thread(_has_row, rt.open_db, iid):
        await rt.forget(iid, notify_peer=False)


def _has_row(open_db, iid: str) -> bool:
    with closing(open_db()) as conn:
        return store.get(conn, iid) is not None


async def on_peer_unpaired(iid: str) -> None:
    await _forget_pairing_removed(iid)


async def on_peer_removed(iid: str) -> None:
    await _forget_pairing_removed(iid)
