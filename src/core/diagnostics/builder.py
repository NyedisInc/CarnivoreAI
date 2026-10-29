
from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import structlog

from src.config.session import SessionConfig
from src.core.diagnostics import launchd_facts, log_tails, tmux_facts
from src.core.stream_redactor import redact_whole
from src.core.tmux_discovery import TmuxVersionSkewError, resolve_tmux_path, select_tmux

logger = structlog.get_logger()

SCHEMA = 2
MAX_LOG_ENTRIES = 20
MAX_BANNER_BYTES = 4096
STARTUP_ERROR_FILE = Path("/tmp/cloude-code-startup-error.log")
CHILD_TIMEOUT_S = 3

_SECTION_ERRORS = (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError, ImportError)

CONFIG_KEY_ALLOWLIST = frozenset({
    "config_version", "session", "auth_rate_limits", "agents", "uploads", "providers", "workspace", "server_prefs",
    "ui", "catalog", "provider_accounts", "relay", "browser", "mcp", "swarm_switch", "byoai", "launch_profiles",
    "common_slash_commands",
})

Redactor = Callable[[str], str]


def _tilde(text: str) -> str:
    home = str(Path.home())
    return text.replace(home, "~") if home and home != "/" else text


def redact_tree(value: Any, redact: Redactor) -> Any:
    if isinstance(value, str):
        return redact(_tilde(value))
    if isinstance(value, dict):
        return {redact_tree(str(k), redact): redact_tree(v, redact) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_tree(v, redact) for v in value]
    return value


def _run(argv: List[str]) -> Optional[str]:
    try:
        done = subprocess.run(  # noqa: S603
            argv, capture_output=True, text=True, timeout=CHILD_TIMEOUT_S, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


def parse_etime(text: str) -> Optional[int]:
    match = re.fullmatch(r"\s*(?:(?:(\d+)-)?(\d+):)?(\d+):(\d+)\s*", text or "")
    if not match:
        return None
    days, hours, minutes, seconds = (int(g or 0) for g in match.groups())
    return ((days * 24 + hours) * 60 + minutes) * 60 + seconds


def _process(mode: str) -> Dict[str, Any]:
    if mode != "server":
        return {"pid": None, "uptime_s": None, "note": "server not running in this process"}
    pid = os.getpid()
    out = _run(["ps", "-o", "etime=", "-p", str(pid)])
    return {"pid": pid, "uptime_s": parse_etime(out) if out else None}


def _network() -> Dict[str, Any]:
    from src.config import settings

    return {"bind": settings.host, "port": settings.port}


def _tmux_for(socket_name: str) -> str:
    try:
        return select_tmux(socket_name) or "tmux"
    except TmuxVersionSkewError:
        return resolve_tmux_path() or "tmux"


def _tmux() -> Dict[str, Any]:
    socket_name = SessionConfig().tmux_socket_name
    try:
        session_block = _read_config().get("session")
    except (FileNotFoundError, ValueError):
        session_block = None
    if isinstance(session_block, dict) and isinstance(session_block.get("tmux_socket_name"), str):
        socket_name = session_block["tmux_socket_name"]
    sockets = tmux_facts.collect(lambda argv: _run(argv), _tmux_for, socket_name)
    configured = next((s for s in sockets if s["socket"] == socket_name), None)
    count = None
    if configured is not None and configured["sessions"] is not None:
        count = len(configured["sessions"]) + configured["other_session_count"]
    return {"socket": socket_name, "session_count": count, "sockets": sockets}


def _launchd() -> Dict[str, Any]:
    return launchd_facts.collect(lambda argv: _run(argv))


def _startup_errors() -> Dict[str, Any]:
    from src.core.server_log.locate import server_log_path
    from src.core.server_log.tail import read_entries

    entries = read_entries(server_log_path(), ("error", "warn"), MAX_LOG_ENTRIES)
    banner: Optional[str] = None
    try:
        if STARTUP_ERROR_FILE.is_file() and not STARTUP_ERROR_FILE.is_symlink():
            banner = STARTUP_ERROR_FILE.read_bytes()[-MAX_BANNER_BYTES:].decode("utf-8", errors="replace")
    except OSError:
        banner = None
    return {"log_entries": [dict(e) for e in entries], "banner_tail": banner}


def _log_location() -> Dict[str, Any]:
    from src.core.server_log.locate import server_log_path

    path = server_log_path()
    return {"path": str(path), "exists": path.exists()}


def locate_state_dir() -> Optional[Path]:
    """Description: where the state directory is, READ-ONLY: creates and renames nothing.

    Order: the explicit override, then the current-named directory, then the legacy-named one (which the
    server renames forward at boot; the CLI must not). Output: Path | None - None when none exists yet.
    """
    from src.config import settings
    from src.core import product_identity

    if settings.state_dir_override:
        return Path(settings.state_dir_override).expanduser()
    base = Path.home() / "Library" / "Application Support"
    for name in (product_identity.STATE_DIR_NAME, *product_identity.LEGACY_STATE_DIR_NAMES):
        if (base / name).is_dir():
            return base / name
    return None


def _disk() -> Dict[str, Any]:
    state = locate_state_dir()
    if state is None:
        raise FileNotFoundError("no state directory yet")
    probe = state
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    usage = shutil.disk_usage(probe)
    return {"path": str(state), "free_bytes": usage.free, "total_bytes": usage.total}


def _runtime() -> Dict[str, Any]:
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "venv": sys.prefix != getattr(sys, "base_prefix", sys.prefix),
        "prefix": sys.prefix,
    }


def _read_config() -> Dict[str, Any]:
    from src.config import settings
    from src.core import config_writer

    return config_writer.read_config(Path(settings.auth_config_file).expanduser())


def _config_keys() -> Dict[str, Any]:
    names = [str(key) for key in _read_config()]
    kept = sorted(n for n in names if n in CONFIG_KEY_ALLOWLIST)
    return {"keys": kept, "dropped_key_count": len(names) - len(kept)}


def _version() -> str:
    from src.core.version import resolve_version

    return resolve_version()


_SECTIONS: Dict[str, Callable[[], Dict[str, Any]]] = {
    "network": _network,
    "tmux": _tmux,
    "launchd": _launchd,
    "startup_errors": _startup_errors,
    "log": _log_location,
    "disk": _disk,
    "runtime": _runtime,
    "config": _config_keys,
}


def build_bundle(*, mode: str = "server", redact: Redactor = redact_whole) -> Dict[str, Any]:
    raw: Dict[str, Any] = {"schema": SCHEMA, "mode": mode, "generated_at": int(time.time())}
    notes: List[str] = []
    try:
        raw["version"] = _version()
    except _SECTION_ERRORS as exc:
        raw["version"] = None
        notes.append(f"version: not measured ({type(exc).__name__})")
    raw["process"] = _process(mode)
    for name, measure in _SECTIONS.items():
        try:
            raw[name] = measure()
        except _SECTION_ERRORS as exc:
            raw[name] = None
            notes.append(f"{name}: not measured ({type(exc).__name__})")
    bundle: Dict[str, Any] = {}
    for name, value in raw.items():
        try:
            bundle[name] = redact_tree(value, redact)
        except Exception as exc:  # noqa: BLE001
            logger.error("diagnostics_redaction_failed", section=name, error_type=type(exc).__name__)
            bundle[name] = None
            notes.append(f"{name}: dropped, redaction failed ({type(exc).__name__})")
    try:
        bundle["logs"] = log_tails.collect(mode, locate_state_dir(), redact, _tilde)
    except _SECTION_ERRORS as exc:
        bundle["logs"] = None
        notes.append(f"logs: not measured ({type(exc).__name__})")
    notes.extend(f"logs: {e['name']} dropped, redaction failed" for e in (bundle["logs"] or {}).get("logs", [])
                 if e["status"] == "dropped_redaction_failed")
    bundle["notes"] = notes
    return bundle
