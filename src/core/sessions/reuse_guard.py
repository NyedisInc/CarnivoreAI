
from __future__ import annotations

import sqlite3

import structlog

from src.core.tmux_listing import TmuxListing

logger = structlog.get_logger()


class ReuseRowTakenError(RuntimeError):

    def __init__(self, row_id: int, held_tmux_name: str) -> None:
        super().__init__(
            f"session row {row_id} is already live in tmux session {held_tmux_name!r}, so it was not restarted"
        )
        self.row_id = row_id
        self.held_tmux_name = held_tmux_name


def refuse_if_row_live_elsewhere(
    conn: sqlite3.Connection,
    *,
    row_id: int,
    listing: TmuxListing,
    socket: str,
    name: str,
    epoch: int,
) -> None:
    if not listing.ok:
        return
    row = conn.execute(
        "SELECT tmux_socket, tmux_name, tmux_created_epoch FROM sessions WHERE id = ?", (int(row_id),)
    ).fetchone()
    if row is None or (row[0] or "") != socket or row[2] is None:
        return
    held_name, held_epoch = row[1], int(row[2])
    if (held_name, held_epoch) == (name, int(epoch)):
        return
    for live in listing.sessions:
        if isinstance(live, dict) and live.get("name") == held_name and live.get("created_at_epoch") == held_epoch:
            logger.warning(
                "recreate_reuse_refused_row_live_elsewhere", reused_session_id=int(row_id),
                held_tmux_name=held_name, held_tmux_epoch=held_epoch, new_tmux_name=name,
                note="an adoption took this row over while the recreate was spawning; the recreate is refused and its own pane stopped",
            )
            raise ReuseRowTakenError(int(row_id), str(held_name))


def refuse_reuse_before_register(
    conn: sqlite3.Connection,
    *,
    row_id: int,
    listing: TmuxListing,
    socket: str,
    name: str,
) -> None:
    if not listing.ok:
        return
    for live in listing.sessions:
        if isinstance(live, dict) and live.get("name") == name and live.get("created_at_epoch") is not None:
            refuse_if_row_live_elsewhere(
                conn, row_id=row_id, listing=listing, socket=socket, name=name, epoch=int(live["created_at_epoch"])
            )
            return
