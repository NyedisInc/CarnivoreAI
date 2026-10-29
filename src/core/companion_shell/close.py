
from __future__ import annotations

import asyncio
import sqlite3
from contextlib import closing
from typing import Any, Mapping

import structlog

from src.config import settings
from src.core import session_sleep
from src.core.companion_shell.ddl import COMPANION_OF_COLUMN
from src.core.companion_shell.ensure import LIFECYCLE_SOURCE_CLOSED_WITH_AGENT
from src.core.db import DatastoreError, connect, db_path_for
from src.core.db_models import SESSION_LIFECYCLE_STOPPED
from src.core.trail_entry import utc_now

logger = structlog.get_logger()


def _write_closed(shell_row: int) -> None:
    with closing(connect(db_path_for(settings.get_state_dir()), create=False)) as conn:
        conn.execute(
            "UPDATE sessions SET lifecycle = ?, lifecycle_source = ?, updated_at = ?, "
            f"activity_state = NULL, activity_state_at = NULL WHERE id = ? AND {COMPANION_OF_COLUMN} IS NOT NULL",
            (SESSION_LIFECYCLE_STOPPED, LIFECYCLE_SOURCE_CLOSED_WITH_AGENT, utc_now(), shell_row))
        conn.commit()


def _delete_row(shell_row: int) -> bool:
    try:
        with closing(connect(db_path_for(settings.get_state_dir()), create=False)) as conn:
            deleted = conn.execute(
                f"DELETE FROM sessions WHERE id = ? AND {COMPANION_OF_COLUMN} IS NOT NULL "
                f"AND NOT EXISTS (SELECT 1 FROM sessions a WHERE a.id = sessions.{COMPANION_OF_COLUMN})",
                (shell_row,)).rowcount
            conn.commit()
            if deleted:
                return True
            left = conn.execute(f"SELECT {COMPANION_OF_COLUMN} FROM sessions WHERE id = ?", (shell_row,)).fetchone()
        if left is None:
            return True
        logger.warning("companion_row_purge_refused", shell_row=shell_row, agent_row=left[0],
                       reason="agent_row_exists" if left[0] is not None else "not_a_companion")
        return False
    except (DatastoreError, sqlite3.Error) as exc:
        logger.warning("companion_row_purge_refused", shell_row=shell_row, reason="database_error",
                       error=type(exc).__name__)
        return False


async def purge_row(index: Any, shell: Mapping[str, Any]) -> bool:
    if not await asyncio.to_thread(_delete_row, int(shell["id"])):
        return False
    index.unlink(int(shell["companion_of"]))
    logger.info("companion_closed", shell_row=shell["id"], agent_row=shell["companion_of"], purged=True)
    return True


async def close_shell(manager: Any, index: Any, shell: Mapping[str, Any], *, purge: bool = False,
                      local_servers: Any = None) -> bool:
    from src.api import recreate_routes as rr
    from src.core.session_recreate_presence import TMUX_GONE

    name, socket = shell.get("tmux_name"), shell.get("tmux_socket")
    try:
        if name and socket:
            if local_servers is not None:
                await local_servers.clear_session(name)
            await session_sleep.close_for_sleep(manager, name=name, socket=socket)
            after = await asyncio.to_thread(rr._measure_presence, name, socket)
            if after.outcome != TMUX_GONE:
                logger.error("companion_close_still_present", shell_row=shell["id"], presence=after.outcome)
                return False
        await asyncio.to_thread(_write_closed, int(shell["id"]))
    except (RuntimeError, OSError, DatastoreError, sqlite3.Error) as exc:
        logger.warning("companion_close_failed", shell_row=shell["id"], error=type(exc).__name__)
        return False
    purged = False
    if purge and await asyncio.to_thread(_delete_row, int(shell["id"])):
        index.unlink(int(shell["companion_of"]))
        purged = True
    logger.info("companion_closed", shell_row=shell["id"], agent_row=shell["companion_of"], purged=purged)
    return True
