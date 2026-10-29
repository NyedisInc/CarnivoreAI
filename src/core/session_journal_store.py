
from __future__ import annotations

import calendar
import json
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import structlog

from src.core.json_artifact import atomic_write_json

logger = structlog.get_logger()

JOURNAL_DIR_NAME: str = "session-journal"
JOURNAL_FILENAME: str = "journal.json"
JOURNAL_BACKUP_SUFFIX: str = ".bak"
HUMAN_LOG_FILENAME: str = "journal.log"
JOURNAL_SCHEMA: int = 1

LOAD_OK: str = "ok"
LOAD_ABSENT: str = "absent"
LOAD_UNREADABLE: str = "unreadable"


@dataclass(frozen=True)
class JournalLoad:

    outcome: str
    journal: Dict[str, Any]
    detail: str = ""


def journal_dir(state_dir: Path) -> Path:
    return Path(state_dir) / JOURNAL_DIR_NAME


def journal_path(state_dir: Path) -> Path:
    return journal_dir(state_dir) / JOURNAL_FILENAME


def human_log_path(state_dir: Path) -> Path:
    return journal_dir(state_dir) / HUMAN_LOG_FILENAME


def empty_journal() -> Dict[str, Any]:
    return {
        "schema": JOURNAL_SCHEMA,
        "boot": None,
        "socket": None,
        "sessions": {},
        "offer": None,
        "declined": {},
        "updated_at": None,
    }


def load_journal(state_dir: Path) -> JournalLoad:
    path = journal_path(state_dir)
    if not path.exists():
        return JournalLoad(LOAD_ABSENT, empty_journal(), "no journal has been written yet")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return JournalLoad(LOAD_UNREADABLE, {}, f"{type(exc).__name__}: {exc}")
    if not isinstance(data, dict) or data.get("schema") != JOURNAL_SCHEMA:
        return JournalLoad(LOAD_UNREADABLE, {}, "not a schema-1 journal object")
    base = empty_journal()
    base.update(data)
    return JournalLoad(LOAD_OK, base)


def save_journal(state_dir: Path, journal: Dict[str, Any]) -> bool:
    path = journal_path(state_dir)
    if path.exists():
        try:
            shutil.copy2(path, path.with_name(path.name + JOURNAL_BACKUP_SUFFIX))
        except OSError as exc:
            logger.warning("session_journal_backup_failed", error=str(exc))
            return False
    journal = dict(journal)
    journal["updated_at"] = now_iso()
    return atomic_write_json(path, journal, log_event="session_journal_write_failed")


def append_human_log(state_dir: Path, event: str, text: str) -> None:
    line = f"{now_iso()}  {event}  {' '.join(str(text).split())}\n"
    path = human_log_path(state_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(line)
    except OSError as exc:
        logger.warning("session_journal_log_write_failed", error=str(exc))


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def iso_to_epoch(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    try:
        return float(calendar.timegm(time.strptime(value, "%Y-%m-%dT%H:%M:%SZ")))
    except (ValueError, OverflowError):
        return None


def ensure_private(state_dir: Path) -> None:
    path = journal_dir(state_dir)
    try:
        path.mkdir(parents=True, exist_ok=True)
        os.chmod(path, 0o700)
    except OSError as exc:
        logger.debug("session_journal_chmod_failed", error=str(exc))
