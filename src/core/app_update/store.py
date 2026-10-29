
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

from src.config import settings
from src.core import config_writer, resource_push
from src.core.resource_push import topics
from src.core.version import resolve_version

STATES = frozenset({
    "not_configured", "invalid_feed", "idle", "checking", "available", "downloading", "ready", "current", "unknown",
    "error", "update_refused",
})
INSTALLABLE = frozenset({"available", "downloading", "ready"})
ACTIONS = frozenset({"check", "install", "config"})

_lock = threading.Lock()
_report: Optional[Dict[str, Any]] = None
_command_seq = 0
_command: Optional[str] = None


def _config_path() -> Path:
    return Path(settings.auth_config_file).expanduser()


def auto_update_enabled() -> bool:
    try:
        block = config_writer.read_config(_config_path()).get("updates")
    except (OSError, ValueError):
        return False
    return isinstance(block, dict) and block.get("auto_update") is True


def write_auto_update(enabled: bool) -> None:
    def mutate(doc: dict) -> Optional[dict]:
        block = doc.get("updates")
        block = dict(block) if isinstance(block, dict) else {}
        if block.get("auto_update") is enabled:
            return None
        block["auto_update"] = enabled
        return {**doc, "updates": block}

    config_writer.commit(_config_path(), mutate)
    request("config")


def record_report(report: Dict[str, Any]) -> bool:
    global _report
    if report.get("state") not in STATES:
        raise ValueError(f"unknown update state {report.get('state')!r}")
    with _lock:
        previous = None if _report is None else {k: v for k, v in _report.items() if k != "reported_at"}
        _report = {**report, "reported_at": time.time()}
        changed = previous != report
    if changed:
        resource_push.notify(topics.APP_UPDATE)
    return changed


def request(action: str) -> int:
    global _command_seq, _command
    if action not in ACTIONS:
        raise ValueError(f"unknown update action {action!r}")
    with _lock:
        _command_seq += 1
        _command = action
        seq = _command_seq
    resource_push.notify(topics.APP_UPDATE)
    return seq


def status() -> Dict[str, Any]:
    with _lock:
        report = dict(_report) if _report else None
        seq, command = _command_seq, _command
    return {
        "attached": report is not None,
        "state": report["state"] if report else "unavailable",
        "current_version": (report or {}).get("current_version") or resolve_version(),
        "latest_version": (report or {}).get("latest_version") or "",
        "percent": (report or {}).get("percent"),
        "detail": (report or {}).get("detail"),
        "checked_at": (report or {}).get("checked_at"),
        "auto_update": auto_update_enabled(),
        "command_seq": seq,
        "command": command,
    }


def reset_for_tests() -> None:
    global _report, _command_seq, _command
    with _lock:
        _report, _command_seq, _command = None, 0, None
