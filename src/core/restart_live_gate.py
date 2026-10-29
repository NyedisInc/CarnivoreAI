
from __future__ import annotations

import sqlite3
import subprocess
from contextlib import closing
from pathlib import Path
from typing import Optional

import structlog

logger = structlog.get_logger()

ALREADY_RUNNING_CODE = "session_already_running"

PROBE_FORMAT = "#{pane_dead}|#{session_created}|#{session_name}"


def classify_probe(raw: str, name: str, epoch: Optional[int]) -> Optional[bool]:
    parts = (raw or "").strip().split("|", 2)
    if len(parts) != 3 or parts[2] != name or parts[0] not in ("0", "1"):
        return None
    if parts[0] == "1":
        return False
    if epoch is None:
        return True
    try:
        created = int(parts[1])
    except ValueError:
        return None
    return created == int(epoch)


def probe_line(name: str, socket: str) -> Optional[str]:
    from src.core.tmux_backend import LIST_TIMEOUT_SECONDS, TmuxBackend

    try:
        backend = TmuxBackend.for_external(
            session_name=name,
            working_dir=Path.home(),
            on_output=None,
            socket_name=socket,
        )
        rc, out, _err = backend._run_tmux_sync(
            "display-message",
            "-p",
            "-t",
            f"={name}:",
            PROBE_FORMAT,
            check=False,
            timeout=LIST_TIMEOUT_SECONDS,
        )
    except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
        logger.warning(
            "restart_live_probe_failed", tmux_name=name, tmux_socket=socket,
            error=str(exc),
        )
        return None
    if rc != 0:
        return None
    return out.decode("utf-8", errors="replace")


def _probe(name: str, epoch: Optional[int], socket: str) -> Optional[bool]:
    raw = probe_line(name, socket)
    return None if raw is None else classify_probe(raw, name, epoch)


def bound_instance_running(
    db_path: Path, session_uuid: str, default_socket: str
) -> Optional[bool]:
    from src.core.db import DatastoreUnreadableError, connect

    try:
        with closing(connect(db_path, create=False)) as conn:
            row = conn.execute(
                "SELECT tmux_socket, tmux_name, tmux_created_epoch FROM sessions "
                "WHERE session_uuid = ? LIMIT 1",
                (session_uuid,),
            ).fetchone()
    except (DatastoreUnreadableError, sqlite3.Error, OSError) as exc:
        logger.warning("restart_live_row_unreadable", session_uuid=session_uuid, error=str(exc))
        return None
    if row is None or not (row["tmux_name"] or "").strip():
        return None
    epoch = row["tmux_created_epoch"]
    return _probe(
        row["tmux_name"].strip(),
        int(epoch) if epoch is not None else None,
        (row["tmux_socket"] or "").strip() or default_socket,
    )
