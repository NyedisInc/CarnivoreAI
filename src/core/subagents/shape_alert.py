
from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import structlog

from src.core import debug_trace
from src.core.subagents.contract import (
    MEASURED_AGAINST_CLAUDE_CODE,
    ShapeCheck,
)

logger = structlog.get_logger(__name__)

NOTE_FILENAME: str = "shape-alerts.md"

MAX_RECORDED: int = 64

_VERSION_RE = re.compile(r"^[0-9]+(\.[0-9]+){0,3}$")


@dataclass(frozen=True)
class ContractSource:

    contract_path: str
    inventory: str
    measured_against: str


_SUBAGENT_SOURCE = ContractSource(
    "src/core/subagents/contract.py",
    'docs/jsonl-shape-inventory.md, addendum "subagent files"',
    MEASURED_AGAINST_CLAUDE_CODE,
)

_sources: Dict[str, ContractSource] = {}
_seen: Set[Tuple[str, int, Tuple[str, ...]]] = set()
_recorded: List[Dict[str, Any]] = []
_listener: Optional[Callable[[Dict[str, Any]], None]] = None
_lock = threading.Lock()


def register_contract_source(file_kind: str, contract_path: str, inventory: str,
                             measured_against: str) -> None:
    with _lock:
        _sources[file_kind] = ContractSource(contract_path, inventory, measured_against)


def source_for(file_kind: str) -> ContractSource:
    with _lock:
        return _sources.get(file_kind, _SUBAGENT_SOURCE)


def safe_version(value: Any) -> Optional[str]:
    if isinstance(value, str) and _VERSION_RE.match(value.strip()):
        return value.strip()
    return None


def set_listener(listener: Optional[Callable[[Dict[str, Any]], None]]) -> None:
    global _listener
    with _lock:
        _listener = listener


def recorded() -> List[Dict[str, Any]]:
    with _lock:
        return [dict(entry, problems=list(entry["problems"])) for entry in _recorded]


def _payload(check: ShapeCheck, version: Optional[str]) -> Dict[str, Any]:
    return {
        "file_kind": check.file_kind,
        "contract_version": check.version,
        "problems": list(check.problems),
        "claude_code_version": version,
        "first_seen": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def _default_debug_dir() -> Optional[Path]:
    try:
        from src.config import settings

        return Path(settings.get_state_dir()) / "debug"
    except (OSError, RuntimeError, ValueError) as exc:
        logger.debug("shape_alert_state_dir_unavailable", error=str(exc))
        return None


def render_note(check: ShapeCheck, claude_code_version: Optional[str]) -> str:
    when = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    problems = "\n".join(f"- {problem}" for problem in check.problems) or "- (none)"
    source = source_for(check.file_kind)
    version = safe_version(claude_code_version)
    return (
        f"## Claude Code file shape changed: {check.file_kind}\n\n"
        f"- first seen: {when}\n"
        f"- contract: {check.file_kind} v{check.version}, measured against "
        f"Claude Code {source.measured_against}\n"
        f"- Claude Code version seen: {version or 'not determinable'}\n\n"
        f"What broke (field names and types only):\n\n{problems}\n\n"
        f"Contract: {source.contract_path}. Inventory: {source.inventory}.\n\n"
    )


def report_unrecognized(
    check: ShapeCheck,
    *,
    claude_code_version: Optional[str] = None,
    enabled: Optional[Callable[[], bool]] = None,
    debug_dir: Optional[Path] = None,
) -> bool:
    if check.recognized:
        return False
    signature = (check.file_kind, check.version, check.problems)
    version = safe_version(claude_code_version)
    payload = _payload(check, version)
    with _lock:
        if signature in _seen:
            return False
        _seen.add(signature)
        _recorded.append(payload)
        del _recorded[:-MAX_RECORDED]
        listener = _listener
    logger.warning(
        "claude_code_shape_unrecognized",
        file_kind=check.file_kind,
        contract_version=check.version,
        problems=list(check.problems),
        claude_code_version=version,
    )
    if listener is not None:
        try:
            listener(dict(payload))
        except (RuntimeError, TypeError, ValueError, OSError) as exc:
            logger.debug("shape_alert_listener_failed", error=str(exc))
    switch = enabled if enabled is not None else debug_trace.enabled
    if not switch():
        return False
    directory = debug_dir if debug_dir is not None else _default_debug_dir()
    if directory is None:
        return False
    try:
        directory.mkdir(parents=True, exist_ok=True)
        with open(directory / NOTE_FILENAME, "a", encoding="utf-8") as handle:
            handle.write(render_note(check, claude_code_version))
    except OSError as exc:
        logger.debug("shape_alert_note_unwritable", error=str(exc))
        return False
    return True


def reset_for_tests() -> None:
    with _lock:
        _seen.clear()
        _recorded.clear()
