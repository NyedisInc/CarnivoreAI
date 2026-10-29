"""What this server process and its tmux socket currently look like.

Companion to :mod:`src.core.host_metrics`, which answers the same kind of
question about the BOX. Split in two because the two halves have nothing
in common except the panel that renders them, and one file holding both
would be the junk drawer the code standards forbid.

OWNERSHIP IS NOT COMPUTED HERE. Whether the app created a tmux session is
decided in exactly one place, ``TmuxBackend.list_attachable_sessions()``,
by membership of the SessionManager's persisted ``owned_tmux_sessions``
set. This module reads tmux for the fields that path does not carry
(working directory, pane size, attached clients) and the caller merges the
authoritative ``created_by_cloude`` onto it by NAME. Re-deriving ownership
from the ``adopted:`` id prefix is wrong and has already shipped as a bug
twice: after a server restart the app re-attaches to its own still-running
sessions through the adopt path, so an app-created session ends up with an
``adopted:`` id while still being in ``owned_tmux_sessions``. The NAME is
the stable key; the id is not.

NO UNTRUSTED STRING EVER REACHES A COMMAND. Session names come from tmux
and from user input. Nothing in this module interpolates one into a
subprocess: the only tmux calls made here are ``list-sessions`` and
``show-options``, both of which take a fixed argv and read names OUT.
Killing a session is not done here at all - that is the SessionManager's
existing job.

THREE OUTCOMES. Every section carries ``available`` and ``error``. A probe
that could not run says so; it never renders as a healthy zero.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

from src.core.dev_tools import git_guard
from src.core.host_metrics import PROBE_TIMEOUT_SECONDS, unavailable
from src.core.sessions.agent_update import CLAUDE_INSTALL_CANDIDATES
from src.core.tmux_discovery import TmuxVersionSkewError, tmux_argv_prefix
from src.core.tmux_listing_parse import is_plumbing_session

logger = structlog.get_logger()

_TMUX_FIELD_SEP = "\x1f"

_TMUX_FORMAT = _TMUX_FIELD_SEP.join([
    "#{session_name}",
    "#{session_created}",
    "#{session_attached}",
    "#{window_width}",
    "#{window_height}",
    "#{session_windows}",
    "#{session_path}",
])

_CLAUDE_CANDIDATES = CLAUDE_INSTALL_CANDIDATES


def _run_full(argv: List[str]) -> Optional[tuple]:
    if not argv or not shutil.which(argv[0]):
        return None
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            check=False,
            timeout=PROBE_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug("server_status_probe_failed", argv=argv[0], error=str(exc))
        return None
    return (
        proc.returncode,
        proc.stdout.decode("utf-8", errors="replace"),
        proc.stderr.decode("utf-8", errors="replace"),
    )


def _run(argv: List[str]) -> Optional[str]:
    result = _run_full(argv)
    if result is None or result[0] != 0:
        return None
    return result[1]


def parse_etime(raw: str) -> Optional[int]:
    text = (raw or "").strip()
    if not text:
        return None
    days = 0
    if "-" in text:
        day_part, _, text = text.partition("-")
        if not day_part.isdigit():
            return None
        days = int(day_part)
    parts = text.split(":")
    if not 2 <= len(parts) <= 3:
        return None
    try:
        numbers = [int(p) for p in parts]
    except ValueError:
        return None
    if len(numbers) == 2:
        numbers.insert(0, 0)
    hours, minutes, seconds = numbers
    return days * 86400 + hours * 3600 + minutes * 60 + seconds


def collect_process(host: str, port: int, repo_root: Optional[Path] = None) -> Dict[str, Any]:
    pid = os.getpid()
    root = repo_root or Path(__file__).resolve().parents[2]
    return {
        "available": True,
        "error": None,
        "pid": pid,
        "uptime_seconds": process_uptime_seconds(pid),
        "host": host,
        "port": port,
        "lan_reachable": host in ("0.0.0.0", "::", ""),
        "python_version": platform.python_version(),
        "platform": f"{platform.system()} {platform.machine()}".strip(),
        "commit": collect_commit(root),
    }


def process_uptime_seconds(pid: int) -> Optional[int]:
    out = _run(["ps", "-p", str(int(pid)), "-o", "etime="])
    if out is None:
        return None
    return parse_etime(out)


def collect_commit(repo_root: Path) -> Dict[str, Any]:
    if not (repo_root / ".git").exists():
        return unavailable("not a git checkout")
    if not git_guard.git_available():
        return unavailable("git is not installed")
    sha = _run(["git", "-C", str(repo_root), "rev-parse", "--short", "HEAD"])
    if sha is None:
        return unavailable("git rev-parse failed")
    status = _run(["git", "-C", str(repo_root), "status", "--porcelain"])
    return {
        "available": True,
        "error": None,
        "sha": sha.strip(),
        "dirty": bool(status and status.strip()),
    }


def collect_claude_cli() -> Dict[str, Any]:
    found = shutil.which("claude")
    candidates = [found] if found else []
    candidates += [str(Path(p).expanduser()) for p in _CLAUDE_CANDIDATES]

    for candidate in candidates:
        if not candidate or not os.path.exists(candidate):
            continue
        out = _run([candidate, "--version"])
        if not out:
            continue
        return {
            "available": True,
            "error": None,
            "version": out.strip().splitlines()[0],
            "path": candidate,
        }
    return unavailable("claude cli not found on any known path")


def collect_tmux(socket_name: str) -> Dict[str, Any]:
    try:
        base = tmux_argv_prefix(socket_name)
    except TmuxVersionSkewError as exc:
        return dict(unavailable(str(exc)), socket=socket_name, server_running=None, history_limit=None, sessions=[])
    if not shutil.which(base[0]):
        return dict(unavailable("tmux is not installed"), socket=socket_name,
                    server_running=None, history_limit=None, sessions=[])

    result = _run_full(base + ["list-sessions", "-F", _TMUX_FORMAT])
    if result is None:
        return dict(unavailable("tmux could not be run"), socket=socket_name,
                    server_running=None, history_limit=None, sessions=[])

    rc, out, err = result
    if rc != 0:
        lowered = err.lower()
        if "no server running" in lowered or "no such file or directory" in lowered:
            return {
                "available": True,
                "error": None,
                "socket": socket_name,
                "server_running": False,
                "history_limit": None,
                "sessions": [],
            }
        return dict(unavailable(f"tmux list-sessions failed: {err.strip()[:120]}"),
                    socket=socket_name, server_running=None,
                    history_limit=None, sessions=[])

    return {
        "available": True,
        "error": None,
        "socket": socket_name,
        "server_running": True,
        "history_limit": _history_limit(base),
        "sessions": parse_sessions(out),
    }


def _history_limit(base: List[str]) -> Optional[int]:
    out = _run(base + ["show-options", "-gv", "history-limit"])
    if out is None:
        return None
    try:
        return int(out.strip())
    except ValueError:
        return None


def parse_sessions(raw: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        parts = line.split(_TMUX_FIELD_SEP, 6)
        if len(parts) < 7:
            logger.debug("server_status_unparseable_session_row", raw=line)
            continue
        name, created, attached, cols, rows_, windows, path = parts
        if is_plumbing_session(name):
            continue
        rows.append({
            "name": name,
            "created_at_epoch": _as_int(created),
            "attached_clients": _as_int(attached),
            "pane_cols": _as_int(cols),
            "pane_rows": _as_int(rows_),
            "window_count": _as_int(windows),
            "working_dir": path,
        })
    return rows


def _as_int(raw: str) -> int:
    try:
        return int(raw.strip())
    except (ValueError, AttributeError):
        return 0


def merge_ownership(
    sessions: List[Dict[str, Any]],
    ownership_by_name: Dict[str, bool],
    open_ids_by_name: Dict[str, str],
) -> List[Dict[str, Any]]:
    for row in sessions:
        name = row.get("name", "")
        row["created_by_cloude"] = ownership_by_name.get(name)
        session_id = open_ids_by_name.get(name)
        row["session_id"] = session_id
        row["open_in_app"] = session_id is not None
    return sessions


def collect(
    host: str,
    port: int,
    socket_name: str,
    ownership_by_name: Dict[str, bool],
    open_ids_by_name: Dict[str, str],
) -> Dict[str, Any]:
    from src.core import host_metrics

    tmux = collect_tmux(socket_name)
    tmux["sessions"] = merge_ownership(
        tmux.get("sessions", []), ownership_by_name, open_ids_by_name
    )
    snapshot: Dict[str, Any] = {
        "collected_at": int(time.time()),
        "server": collect_process(host, port),
        "tmux": tmux,
        "claude_cli": collect_claude_cli(),
    }
    snapshot.update(host_metrics.collect())
    return snapshot
