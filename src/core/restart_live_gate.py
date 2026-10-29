"""Refuse a restart of a row whose own tmux instance is MEASURED running.

THE RULE. Before spawning, read the row's CURRENT instance triple
``(tmux_socket, tmux_name, tmux_created_epoch)`` and probe that exact
tmux session. Only a probe that RAN, found that exact name, a matching
creation epoch and ``#{pane_dead}`` = ``0`` refuses. Everything else,
including a probe that could not run, proceeds exactly as before: the
restart route deliberately does not refuse on a stale stored lifecycle
(``session_restart.resolve_restart_source``), and not having looked is
not evidence the session is running.

THE TARGET IS ``=name:``, NEVER A BARE NAME. tmux resolves a bare ``-t``
session name by PREFIX when there is no exact match, so probing
``carnivore_Storefront`` after it is gone answers for ``carnivore_Storefront-2``,
which is precisely the shape this module exists for. ``=`` forces an exact
match, and a missing session then prints an empty line, which reads as
could not determine.
"""

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
    """Read one probe line as running, not running, or could not tell. PURE.

    Description: True only for the exact name, a live pane and (when the
      row records one) the same creation epoch. A different epoch is a
      different instance that merely reuses the name, so it is False: the
      row's own instance is gone. A dead pane is False. Anything
      malformed, empty or naming another session is None.
    Inputs: raw (str) - one ``PROBE_FORMAT`` line. name (str) - the row's
      tmux name. epoch (int | None) - the row's ``tmux_created_epoch``.
    Output: bool | None.
    Example: classify_probe('0|17|cloude_a', 'cloude_a', 17)  # True
    """
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
