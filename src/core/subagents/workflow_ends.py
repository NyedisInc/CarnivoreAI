
from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import structlog

logger = structlog.get_logger(__name__)

WORKFLOWS_DIR: str = "workflows"
WORKFLOW_PREFIX: str = "wf_"
JOURNAL_NAME: str = "journal.jsonl"

TERMINAL_STATUSES: frozenset = frozenset({"completed", "failed", "killed", "stopped"})

STATUS_COMPLETED: str = "completed"
STATUS_FAILED: str = "failed"

LAUNCH_MARK: bytes = b"Workflow launched in background"

_WF_FOLDER = r"wf_[A-Za-z0-9_-]+"
_DIAGNOSTICS_RE = re.compile(rf"/{WORKFLOWS_DIR}/({_WF_FOLDER})/{re.escape(JOURNAL_NAME)}")
_LAUNCH_TASK_RE = re.compile(r"Workflow launched in background\.\s*Task ID:\s*(\S+)")
_LAUNCH_DIR_RE = re.compile(rf"Transcript dir:\s*\S*/{WORKFLOWS_DIR}/({_WF_FOLDER})(?=\s|$)")


def workflow_id_of(folder: Path) -> Optional[str]:
    if folder.name.startswith(WORKFLOW_PREFIX) and folder.parent.name == WORKFLOWS_DIR:
        return folder.name
    return None


def journal_workflow_ids(text: str) -> List[str]:
    return list(dict.fromkeys(_DIAGNOSTICS_RE.findall(text)))


def launch_pair(text: str) -> Optional[Tuple[str, str]]:
    task = _LAUNCH_TASK_RE.search(text)
    folder = _LAUNCH_DIR_RE.search(text)
    if task is None or folder is None:
        return None
    return task.group(1), folder.group(1)


@dataclass
class _JournalState:

    size: int
    mtime_ns: int
    offset: int
    ends: Dict[str, str]


_lock = threading.Lock()
_journals: Dict[str, _JournalState] = {}


def reset_journal_cache_for_tests() -> None:
    with _lock:
        _journals.clear()


def _fold(path: str, start: int, ends: Dict[str, str]) -> int:
    offset = start
    with open(path, "rb") as handle:
        handle.seek(start)
        for raw in handle:
            if not raw.endswith(b"\n"):
                break
            offset += len(raw)
            if b'"result"' not in raw:
                continue
            try:
                record = json.loads(raw)
            except ValueError:
                continue
            agent = record.get("agentId") if isinstance(record, dict) else None
            if record.get("type") == "result" and isinstance(agent, str) and agent:
                ends[agent] = STATUS_FAILED if record.get("result") is None else STATUS_COMPLETED
    return offset


def read_journal_ends(folder: Path) -> Tuple[Dict[str, str], Optional[datetime]]:
    path = str(folder / JOURNAL_NAME)
    try:
        stat = os.stat(path)
    except OSError:
        return {}, None
    at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
    with _lock:
        state = _journals.get(path)
    if state is not None and (state.size, state.mtime_ns) == (stat.st_size, stat.st_mtime_ns):
        return state.ends, at
    grown = state is not None and stat.st_size >= state.offset
    ends: Dict[str, str] = dict(state.ends) if grown else {}
    start = state.offset if grown else 0
    try:
        offset = _fold(path, start, ends)
    except OSError as exc:
        logger.debug("subagents_workflow_journal_unreadable", error=str(exc))
        return {}, None
    with _lock:
        _journals[path] = _JournalState(stat.st_size, stat.st_mtime_ns, offset, ends)
    return ends, at
