"""Record that a session was CLOSED, at the moment it was closed.

THE DEFECT. ``SessionManager.destroy_session`` kills tmux, tears down the
watchers and sets ``sess.status`` on an in-memory object it then throws
away. It writes NOTHING to ``sessions.lifecycle``. The only thing that
ever moves a row from ``running`` to ``stopped`` is
``session_lifecycle.reconcile_from_listing``, which runs on a poll, so for
one whole poll interval after a close the row still reads ``running``.

IT NEVER TOUCHES ``archived_at`` AND THE COLUMN IS NOT IN THE UPDATE.
Closing a session and DELETING its record are two different verbs with two
different controls, and only ``session_store.archive_session`` (reached
from ``DELETE /sessions/records/{uuid}``) writes that column. A close that
archived would take the row off every screen instead of moving it to
Recent, which is the complaint this module exists to fix, not to cause.
The same rule, and the same wording, as ``session_lifecycle``'s reaper.

IT RESOLVES THE ROW THROUGH ``session_store.identity_for_instance`` (the
exact ``(socket, name, epoch)`` key, when the route could read the epoch
before the kill) OR ``identity_for_live_name`` (when it could not), AND
THEN UPDATES BY ``id``, rather than matching on the tmux name itself. A
name is reused every time a session is recreated after its pane dies, so
"the row with this name" is a guess and two anchor rows can differ only by
creation epoch - which is what ``tests/test_no_name_keyed_session_identity.py``
exists to forbid, and it caught the first draft of this module doing
exactly that. With a NAME and no epoch, the name helper is the case it
was written for and already carries the argument for: for a session
that was live until a moment ago, the newest instance of its name IS the
one that was just killed. Reusing it keeps that reasoning in one place
instead of restating it here.
"""

from __future__ import annotations

import sqlite3
from typing import Optional

import structlog

from src.core.db_models import (
    SESSION_LIFECYCLE_RUNNING,
    SESSION_LIFECYCLE_SOURCE_TMUX_MISSING,
    SESSION_LIFECYCLE_STOPPED,
)
from src.core.hosts.ddl import LOCAL_HOST_KEY
from src.core.session_store import (
    identity_for_instance,
    identity_for_live_name,
    sessions_table_ready,
)

logger = structlog.get_logger()

LIFECYCLE_SOURCE_CLOSED = "closed_by_user"

SUPERSEDABLE_STOPPED_SOURCE = SESSION_LIFECYCLE_SOURCE_TMUX_MISSING


def mark_closed(
    conn: sqlite3.Connection,
    *,
    socket: str,
    name: str,
    epoch: Optional[int] = None,
    now: Optional[str] = None,
    host_key: str = LOCAL_HOST_KEY,
) -> int:
    from src.core.trail_entry import utc_now

    if not sessions_table_ready(conn):
        return 0
    if not socket or not name:
        return 0

    stamp = now or utc_now()

    exact = epoch is not None
    identity = (
        identity_for_instance(conn, socket=socket, name=name, epoch=epoch, host_key=host_key)
        if exact
        else identity_for_live_name(conn, socket=socket, name=name, host_key=host_key)
    )
    if identity is None:
        logger.info(
            "session_closed_lifecycle_no_row",
            tmux_socket=socket,
            tmux_name=name,
            note="no stored session describes this tmux name; nothing written",
        )
        return 0

    cursor = conn.execute(
        "UPDATE sessions SET lifecycle = ?, lifecycle_source = ?, "
        "lifecycle_checked_at = ?, updated_at = ?, "
        "activity_state = NULL, activity_state_at = NULL "
        "WHERE id = ? AND (lifecycle = ? "
        "OR (lifecycle = ? AND lifecycle_source = ?))",
        (
            SESSION_LIFECYCLE_STOPPED,
            LIFECYCLE_SOURCE_CLOSED,
            stamp,
            stamp,
            int(identity["id"]),
            SESSION_LIFECYCLE_RUNNING,
            SESSION_LIFECYCLE_STOPPED,
            SUPERSEDABLE_STOPPED_SOURCE if exact else None,
        ),
    )
    moved = int(cursor.rowcount or 0)
    logger.info(
        "session_closed_lifecycle_written",
        tmux_socket=socket,
        tmux_name=name,
        tmux_created_epoch=epoch,
        rows_moved=moved,
        note=(
            "close writes lifecycle itself so the row reaches RECENT "
            "without waiting for a reconcile pass; archived_at is "
            "deliberately not written"
        ),
    )
    return moved
