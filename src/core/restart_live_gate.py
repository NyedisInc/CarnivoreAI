
from __future__ import annotations

import re
import sqlite3
import subprocess
from contextlib import closing
from pathlib import Path
from typing import Any, Optional, Tuple

import structlog

logger = structlog.get_logger()

ALREADY_RUNNING_CODE = "session_already_running"

PROBE_FORMAT = "#{pane_dead}|#{session_created}|#{session_name}|#{session_id}"


_SESSION_ID = re.compile(r"\$\d+")


def parse_probe(raw: Optional[str]) -> Optional[Tuple[str, str, str, Optional[str]]]:
    body = (raw or "").strip()
    head, sep, tail = body.rpartition("|")
    session_id = tail if sep and _SESSION_ID.fullmatch(tail) else None
    parts = (head if session_id else body).split("|", 2)
    if len(parts) != 3 or parts[0] not in ("0", "1"):
        return None
    return parts[0], parts[1], parts[2], session_id


def probe_session_id(raw: Optional[str], name: str) -> Optional[str]:
    parsed = parse_probe(raw)
    return parsed[3] if parsed and parsed[2] == name else None


def classify_probe(raw: str, name: str, epoch: Optional[int]) -> Optional[bool]:
    parts = parse_probe(raw)
    if parts is None or parts[2] != name:
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


def probe_epoch(raw: Optional[str], name: str) -> Optional[int]:
    parts = parse_probe(raw)
    if parts is None or parts[2] != name:
        return None
    try:
        return int(parts[1])
    except ValueError:
        return None


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


async def nothing_running(manager: Any, tmux_name: str) -> bool:
    from src.core.auto_sleep.live_work import hold_for
    from src.core.hosts.identity import is_remote_backend
    from src.models.activity_status import RESTING

    try:
        session_id = next(
            (sid for sid, b in manager._registry.backends.items()
             if getattr(b, "tmux_session", None) == tmux_name and not is_remote_backend(b)), None)
        info = await manager.get_session_info(session_id) if session_id else None
        if info is None or info.activity_status not in RESTING or info.activity_hint is not None:
            return False
        if info.background_open or info.subagents_running or info.timers_live:
            return False
        read = getattr(manager, "_fresh_evidence", None)
        evidence = await read(session_id) if read else None
        return evidence is not None and hold_for(evidence, require_measured=True) is None
    except Exception as exc:  # noqa: BLE001
        logger.warning("restart_nothing_running_unmeasured", tmux_name=tmux_name, error_type=type(exc).__name__)
        return False
