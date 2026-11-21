
from __future__ import annotations

import json
import os
import shlex
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

from src.core.approvals import beast_grid
from src.core.mcp import beast_mode
from src.core.pack.jobs.launch_line import HOOK_SCRIPT as DELEGATE_SCRIPT

log = structlog.get_logger(__name__)

SETTINGS_FLAG = "--settings"
PERMISSION_SCRIPT = Path(__file__).with_name("permission_hook.py")


def permission_hook_wanted() -> bool:
    try:
        return any(beast_mode.ticked_in(beast_grid.ROW_CLAUDE_PERMISSION, mode) for mode in beast_grid.MODES)
    except Exception as exc:  # noqa: BLE001
        log.warning("permission_hook_policy_failed", error_type=type(exc).__name__)
        return False


def _command(script: Path) -> str:
    return f"{shlex.quote(sys.executable or 'python3')} -I {shlex.quote(str(script))}"


def _entries(delegate: bool, permission: bool) -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = {}
    if delegate:
        block = [{"matcher": "Bash", "hooks": [{"type": "command", "command": _command(DELEGATE_SCRIPT), "timeout": 2}]}]
        agents = [{"matcher": "Agent|Task", "hooks": [{"type": "command", "command": _command(DELEGATE_SCRIPT), "timeout": 2}]}]
        out["PreToolUse"], out["PostToolUse"] = [*block, *agents], block
    if permission:
        out["PermissionRequest"] = [{"hooks": [{"type": "command", "command": _command(PERMISSION_SCRIPT), "timeout": 3}]}]
    return out


def _readable(path: Path) -> bool:
    return path.is_file() and os.access(path, os.R_OK)


def _theirs(args: List[str]) -> Optional[tuple]:
    for i, a in enumerate(args):
        if a == SETTINGS_FLAG and i + 1 < len(args):
            return i, i + 1, args[i + 1], False
        if a.startswith(SETTINGS_FLAG + "="):
            return i, i, a[len(SETTINGS_FLAG) + 1:], True
    return None


def _load(value: str) -> Optional[Dict[str, Any]]:
    try:
        text = value if value.lstrip().startswith("{") else Path(value).expanduser().read_text(encoding="utf-8")
        doc = json.loads(text)
    except (OSError, ValueError):
        return None
    hooks = doc.get("hooks", {}) if isinstance(doc, dict) else None
    return doc if isinstance(hooks, dict) and all(isinstance(v, list) for v in hooks.values()) else None


def add_hooks(args: List[str], *, delegate: bool, permission: bool) -> List[str]:
    if not (delegate or permission):
        return list(args)
    scripts = ([DELEGATE_SCRIPT] if delegate else []) + ([PERMISSION_SCRIPT] if permission else [])
    if not all(_readable(s) for s in scripts):
        log.warning("launch_hooks_script_unreadable", scripts=[str(s) for s in scripts])
        return list(args)
    theirs = _theirs(args)
    doc: Dict[str, Any] = {}
    if theirs is not None:
        loaded = _load(theirs[2])
        if loaded is None:
            log.warning("launch_hooks_settings_unreadable")
            return list(args)
        doc = loaded
    hooks = {k: list(v) for k, v in (doc.get("hooks") or {}).items()}
    for event, blocks in _entries(delegate, permission).items():
        hooks[event] = [*hooks.get(event, []), *blocks]
    merged = {**doc, "hooks": hooks}
    try:
        text = json.dumps(merged, separators=(",", ":"))
        round_trips = json.loads(text) == merged
    except (TypeError, ValueError):
        round_trips = False
    if not round_trips:
        log.warning("launch_hooks_document_invalid")
        return list(args)
    if theirs is None:
        return [*args, SETTINGS_FLAG, text]
    flag_i, val_i, _value, joined = theirs
    out = list(args)
    out[val_i] = f"{SETTINGS_FLAG}={text}" if joined else text
    return out
