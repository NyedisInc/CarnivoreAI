
from __future__ import annotations

import threading
from pathlib import Path
from typing import Dict, Optional

import structlog

from src.core.claude_rename_retry import RenameMark
from src.core.json_artifact import atomic_write_json, read_json_object

logger = structlog.get_logger(__name__)

LEDGER_DIRNAME: str = "rename-retry"

LEDGER_FILENAME: str = "marks.json"

LEDGER_VERSION: int = 1

MAX_ENTRIES: int = 500

_LOCK = threading.Lock()
_MARKS: Optional[Dict[str, RenameMark]] = None
_LOADED_FROM: Optional[Path] = None


def ledger_path(state_dir: Path) -> Path:
    return Path(state_dir) / LEDGER_DIRNAME / LEDGER_FILENAME


def resolve_state_dir() -> Optional[Path]:
    try:
        from src.config import settings

        return Path(settings.get_state_dir())
    except (ImportError, AttributeError, OSError, RuntimeError, ValueError) as exc:
        logger.debug("rename_retry_state_dir_unresolved", error=str(exc))
        return None


def _decode(payload: dict) -> Dict[str, RenameMark]:
    if payload.get("version") != LEDGER_VERSION:
        return {}
    raw = payload.get("marks")
    if not isinstance(raw, dict):
        return {}
    marks: Dict[str, RenameMark] = {}
    for key, entry in raw.items():
        if not isinstance(key, str) or not isinstance(entry, dict):
            continue
        agreed = entry.get("agreed_title")
        label = entry.get("attempted_label")
        attempts = entry.get("attempts")
        last = entry.get("last_attempt_at")
        if agreed is not None and not isinstance(agreed, str):
            continue
        if label is not None and not isinstance(label, str):
            continue
        if not isinstance(attempts, int) or attempts < 0:
            continue
        if last is not None and not isinstance(last, (int, float)):
            continue
        marks[key] = RenameMark(
            agreed_title=agreed,
            attempted_label=label,
            attempts=attempts,
            last_attempt_at=float(last) if last is not None else None,
        )
    return marks


def _encode(marks: Dict[str, RenameMark]) -> dict:
    return {
        "version": LEDGER_VERSION,
        "marks": {
            key: {
                "agreed_title": mark.agreed_title,
                "attempted_label": mark.attempted_label,
                "attempts": int(mark.attempts or 0),
                "last_attempt_at": mark.last_attempt_at,
            }
            for key, mark in marks.items()
        },
    }


def _evict(marks: Dict[str, RenameMark]) -> Dict[str, RenameMark]:
    if len(marks) <= MAX_ENTRIES:
        return marks
    ordered = sorted(
        marks.items(),
        key=lambda item: (
            item[1].attempted_label is not None,
            item[1].last_attempt_at or 0.0,
        ),
        reverse=True,
    )
    return dict(ordered[:MAX_ENTRIES])


def load_marks(state_dir: Optional[Path]) -> Dict[str, RenameMark]:
    global _MARKS, _LOADED_FROM
    resolved = Path(state_dir) if state_dir is not None else None
    with _LOCK:
        if _MARKS is not None and _LOADED_FROM == resolved:
            return _MARKS
        if resolved is None:
            _MARKS, _LOADED_FROM = {}, None
            return _MARKS
        payload = read_json_object(
            ledger_path(resolved), log_event="rename_retry_ledger_unreadable"
        )
        _MARKS = _decode(payload) if isinstance(payload, dict) else {}
        _LOADED_FROM = resolved
        return _MARKS


def save_mark(
    state_dir: Optional[Path], key: str, mark: RenameMark
) -> bool:
    marks = load_marks(state_dir)
    with _LOCK:
        if marks.get(key) == mark:
            return False
        marks[key] = mark
        trimmed = _evict(marks)
        if trimmed is not marks:
            marks.clear()
            marks.update(trimmed)
        if state_dir is None:
            return False
        payload = _encode(marks)
    return atomic_write_json(
        ledger_path(Path(state_dir)),
        payload,
        log_event="rename_retry_ledger_write_failed",
    )


def mark_for(state_dir: Optional[Path], key: str) -> Optional[RenameMark]:
    return load_marks(state_dir).get(key)


def reset_cache() -> None:
    global _MARKS, _LOADED_FROM
    with _LOCK:
        _MARKS, _LOADED_FROM = None, None
