
from __future__ import annotations

import os
import plistlib
import re
import stat
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import structlog

from src.core import product_identity

logger = structlog.get_logger()

Runner = Callable[[List[str]], Optional[str]]

MAX_PLIST_BYTES = 64 * 1024
_PRINT_FIELDS = ("state", "pid", "last exit code", "runs", "path", "program", "stdout path", "stderr path")
_PRINT_LINE = re.compile(r"^\t(" + "|".join(re.escape(f) for f in _PRINT_FIELDS) + r") = (.+?)\s*$")
_PLIST_ERRORS = (OSError, plistlib.InvalidFileException, ValueError, KeyError, TypeError)


def _launch_agents_dir() -> Path:
    return Path.home() / "Library" / "LaunchAgents"


def parse_launchctl_print(text: str) -> Dict[str, Any]:
    found: Dict[str, str] = {}
    for line in text.splitlines():
        match = _PRINT_LINE.match(line)
        if match and match.group(1) not in found:
            found[match.group(1)] = match.group(2)
    out: Dict[str, Any] = {}
    for key, value in found.items():
        name = key.replace(" ", "_")
        out[name] = int(value) if key in ("pid", "runs") and value.isdigit() else value
    return out


def read_plist_summary(plist_path: Path) -> Dict[str, Any]:
    try:
        fd = os.open(plist_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except OSError:
        return {"present": False}
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid():
            return {"present": False}
        raw = os.read(fd, MAX_PLIST_BYTES + 1)
    except OSError:
        return {"present": False}
    finally:
        os.close(fd)
    if len(raw) > MAX_PLIST_BYTES:
        return {"present": False}
    try:
        data = plistlib.loads(raw)
    except _PLIST_ERRORS as exc:
        logger.warning("diagnostics_plist_unreadable", error_type=type(exc).__name__)
        return {"present": True, "program": None, "stdout_path": None, "stderr_path": None}
    args = data.get("ProgramArguments") if isinstance(data, dict) else None
    program = args[0] if isinstance(args, list) and args and isinstance(args[0], str) else None
    out_path = data.get("StandardOutPath") if isinstance(data, dict) else None
    err_path = data.get("StandardErrorPath") if isinstance(data, dict) else None
    return {
        "present": True,
        "program": program,
        "stdout_path": out_path if isinstance(out_path, str) else None,
        "stderr_path": err_path if isinstance(err_path, str) else None,
    }


def collect(run: Runner, *, uid: Optional[int] = None) -> Dict[str, Any]:
    label = product_identity.BUNDLE_ID
    agents = _launch_agents_dir()
    legacy = any((agents / f"{old}.plist").exists() for old in product_identity.LEGACY_BUNDLE_IDS)
    printed = run(["launchctl", "print", f"gui/{os.getuid() if uid is None else uid}/{label}"])
    return {
        "label": label,
        "plist": read_plist_summary(agents / f"{label}.plist"),
        "legacy_plist_present": legacy,
        "loaded": printed is not None,
        "job": parse_launchctl_print(printed) if printed else {},
    }
