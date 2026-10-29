
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, List, Mapping, Optional, Sequence, Tuple

import structlog

from src.core.hosts.identity import REMOTE_ID_PREFIX

logger = structlog.get_logger()


@dataclass(frozen=True)
class RegistrationSnapshot:

    session_id: str
    backend: Any
    tmux_name: str
    socket: Optional[str]


def snapshot_registrations(
    backends: Mapping[str, Any],
) -> Tuple[RegistrationSnapshot, ...]:
    from src.core.hosts.identity import is_remote_backend

    out: List[RegistrationSnapshot] = []
    for sid, backend in list(backends.items()):
        name = getattr(backend, "tmux_session", None)
        if not name or is_remote_backend(backend):
            continue
        out.append(
            RegistrationSnapshot(
                session_id=sid,
                backend=backend,
                tmux_name=str(name),
                socket=getattr(backend, "socket_name", None) or None,
            )
        )
    return tuple(out)


def measured_gone(
    snapshot: Sequence[RegistrationSnapshot],
    current_backends: Mapping[str, Any],
    status_map: Any,
) -> List[RegistrationSnapshot]:
    if not getattr(status_map, "complete", False):
        return []
    listing_socket = getattr(status_map, "socket", None)
    if not listing_socket:
        return []
    gone: List[RegistrationSnapshot] = []
    for reg in snapshot:
        if reg.socket != listing_socket:
            continue
        if reg.tmux_name in status_map:
            continue
        current = current_backends.get(reg.session_id)
        if current is not reg.backend:
            continue
        if getattr(current, "tmux_session", None) != reg.tmux_name:
            continue
        gone.append(reg)
    return gone


async def drop_registration(
    manager: Any,
    session_id: str,
    *,
    reason: str,
    tmux_name: Optional[str] = None,
    release_token: bool = False,
) -> None:
    backend = manager._registry.backends.get(session_id)
    task = getattr(backend, "_reader_task", None) if backend else None
    if task is not None:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except (OSError, RuntimeError, ValueError) as exc:
            logger.warning(
                "registration_reader_task_ended_with_error",
                session_id=session_id,
                error=str(exc),
            )
    if backend is not None and hasattr(backend, "_reader_task"):
        backend._reader_task = None
        backend._running = False
    manager._wipe_session_state(session_id)
    logger.debug("registration_dropped", session_id=session_id, reason=reason)
    if release_token and tmux_name:
        manager.hook_tokens.release(session_id, tmux_name=tmux_name)


async def reap_after_listing(
    manager: Any,
    snapshot: Sequence[RegistrationSnapshot],
    status_map: Any,
) -> List[str]:
    reaped: List[str] = []
    gone_names: List[str] = []
    for reg in measured_gone(snapshot, manager._registry.backends, status_map):
        await drop_registration(
            manager,
            reg.session_id,
            reason="tmux_session_measured_gone",
            tmux_name=reg.tmux_name,
            release_token=True,
        )
        reaped.append(reg.session_id)
        if reg.tmux_name and not reg.session_id.startswith(REMOTE_ID_PREFIX):
            gone_names.append(reg.tmux_name)
        logger.info(
            "session_registration_reaped",
            session_id=reg.session_id,
            tmux_name=reg.tmux_name,
            tmux_socket=reg.socket,
            listed=len(status_map),
            note=(
                "a complete list-panes -a on this socket does not name "
                "this session; the in-memory registration is dropped. The "
                "row is moved by the lifecycle reaper, not here"
            ),
        )
    if gone_names:
        from src.core.companion_shell import reconcile

        reconcile.request(gone_names)
    return reaped
