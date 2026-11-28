from __future__ import annotations

from typing import Any, Awaitable, Callable, Optional

import structlog
from fastapi.concurrency import run_in_threadpool

from src.config import settings
from src.core.hosts.ddl import LOCAL_HOST_KEY
from src.core.session_ops import close_intent

logger = structlog.get_logger()


async def instance_epoch(backend: Any) -> Optional[int]:
    reader = getattr(backend, "session_created_epoch", None) if backend else None
    if reader is None:
        return None
    try:
        return await reader()
    except (OSError, RuntimeError, ValueError) as exc:
        logger.warning("close_instance_epoch_unread", error=str(exc))
        return None


async def mark_closed_in_datastore(
    socket: Optional[str], name: Optional[str], epoch: Optional[int] = None,
    host_key: str = LOCAL_HOST_KEY,
) -> int:
    from contextlib import closing

    from src.core import session_close_lifecycle
    from src.core.db import DatastoreUnreadableError, connect, db_path_for

    if not socket or not name:
        return 0
    db_path = db_path_for(settings.get_state_dir())
    if not db_path.exists():
        return 0

    def _write() -> int:
        with closing(connect(db_path, create=False)) as conn:
            moved = session_close_lifecycle.mark_closed(
                conn, socket=socket, name=name, epoch=epoch, host_key=host_key
            )
            conn.commit()
            return moved

    try:
        return await run_in_threadpool(_write)
    except DatastoreUnreadableError as exc:
        logger.warning(
            "close_lifecycle_not_recorded",
            tmux_socket=socket,
            tmux_name=name,
            error=str(exc),
            note=(
                "the session WAS destroyed; only the row's lifecycle "
                "write did not land, and the reconciler still covers it"
            ),
        )
        return 0


async def read_external_epoch(name: str, socket: str) -> Optional[int]:
    from pathlib import Path

    from src.core.tmux_backend import TmuxBackend

    try:
        probe = TmuxBackend.for_external(session_name=name, working_dir=Path(settings.default_working_dir).expanduser(),
                                         on_output=None, socket_name=socket)
    except (OSError, RuntimeError, ValueError) as exc:
        logger.warning("close_external_epoch_unread", tmux_name=name, error=str(exc))
        return None
    return await instance_epoch(probe)


async def stop_and_record(kill: Callable[[], Awaitable[Any]], *, socket: Optional[str], name: Optional[str],
                          epoch: Optional[int], host: str = LOCAL_HOST_KEY) -> int:
    with close_intent.stopping(host, socket, name, epoch) as mark:
        await kill()
        moved = await mark_closed_in_datastore(socket, name, epoch, host)
        mark.settled = moved > 0
        return moved
