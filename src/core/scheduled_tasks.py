
from __future__ import annotations

import glob
import json
import os
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import structlog

from src.core.claude_config.transcript_roots import claude_transcript_roots
from src.core.subagents.parent_index import parse_timestamp
from src.core.timers.redact import summary
from src.models.scheduled_tasks import ScheduledTask, ScheduledTasksList

logger = structlog.get_logger(__name__)

SCHEDULED_TASKS_DIR: Path = Path.home() / ".claude" / "scheduled-tasks"

TASK_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

MAX_TASKS: int = 200
MAX_SKILL_BYTES: int = 64 * 1024
MAX_TRANSCRIPTS: int = 20000
HEAD_BYTES: int = 8192
TTL_SECONDS: float = 60.0
DESCRIPTION_CHARS: int = 300

_RUN_TAG_RE = re.compile(rb'<scheduled-task name=\\"([^"\\]{1,200})\\"')
_SCHEDULE_KEYS = ("schedule", "cron")


def parse_frontmatter(text: str) -> Optional[Dict[str, str]]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        return None
    pairs: Dict[str, str] = {}
    key: Optional[str] = None
    block: List[str] = []
    for line in lines[1:end]:
        if key is not None and (line.startswith((" ", "\t")) or not line.strip()):
            block.append(line.strip())
            continue
        if key is not None:
            pairs[key] = " ".join(part for part in block if part)
            key, block = None, []
        match = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if not match:
            continue
        name, value = match.group(1), match.group(2).strip()
        if value in (">", "|", ">-", "|-"):
            key, block = name, []
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        pairs[name] = value
    if key is not None:
        pairs[key] = " ".join(part for part in block if part)
    return pairs


def _read_skill(path: str) -> Tuple[Optional[str], str]:
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except FileNotFoundError:
        return None, "missing"
    except OSError as exc:
        logger.debug("scheduled_task_unreadable", error_type=type(exc).__name__)
        return None, "unreadable"
    with os.fdopen(fd, "rb") as handle:
        data = handle.read(MAX_SKILL_BYTES + 1)
    if len(data) > MAX_SKILL_BYTES:
        return None, "too_large"
    return data.decode("utf-8", errors="replace"), "ok"


@dataclass(frozen=True)
class _Head:

    size: int
    mtime_ns: int
    task: Optional[str]
    at: Optional[datetime]


def _head_fact(path: str, size: int, mtime_ns: int) -> _Head:
    try:
        with open(path, "rb") as handle:
            head = handle.read(HEAD_BYTES)
    except OSError:
        return _Head(size, mtime_ns, None, None)
    for line in head.split(b"\n"):
        match = _RUN_TAG_RE.search(line)
        if not match:
            continue
        try:
            record = json.loads(line)
        except (ValueError, UnicodeDecodeError):
            return _Head(size, mtime_ns, None, None)
        at = parse_timestamp(record.get("timestamp")) if isinstance(record, dict) else None
        return _Head(size, mtime_ns, match.group(1).decode("utf-8", "replace"), at)
    return _Head(size, mtime_ns, None, None)


class ScheduledTaskReader:

    def __init__(self, *, tasks_dir: Optional[Path] = None,
                 projects_dir: Optional[Path] = None, clock=None) -> None:
        self._tasks_dir = tasks_dir
        self._projects_dir = projects_dir
        self._clock = clock or time.monotonic
        self._lock = threading.Lock()
        self._heads: Dict[str, _Head] = {}
        self._cached: Optional[Tuple[float, ScheduledTasksList]] = None

    def read(self) -> ScheduledTasksList:
        with self._lock:
            at = self._clock()
            if self._cached is not None and at - self._cached[0] < TTL_SECONDS:
                return self._cached[1]
            answer = self._read()
            self._cached = (at, answer)
            return answer

    def _runs(self) -> Tuple[Dict[str, Tuple[int, Optional[datetime]]], bool]:
        roots = (
            [str(self._projects_dir)] if self._projects_dir
            else [str(r) for r in claude_transcript_roots()]
        )
        paths = sorted({
            found
            for root in roots
            for found in glob.glob(os.path.join(glob.escape(root), "*", "*.jsonl"))
        })
        truncated = len(paths) > MAX_TRANSCRIPTS
        seen: Dict[str, _Head] = {}
        for path in paths[:MAX_TRANSCRIPTS]:
            try:
                stat = os.stat(path)
            except OSError:
                continue
            head = self._heads.get(path)
            if head is None or (head.size, head.mtime_ns) != (stat.st_size, stat.st_mtime_ns):
                head = _head_fact(path, stat.st_size, stat.st_mtime_ns)
            seen[path] = head
        self._heads = seen
        runs: Dict[str, Tuple[int, Optional[datetime]]] = {}
        for head in seen.values():
            if head.task is None:
                continue
            count, newest = runs.get(head.task, (0, None))
            if head.at is not None and (newest is None or head.at > newest):
                newest = head.at
            runs[head.task] = (count + 1, newest)
        return runs, truncated

    def _read(self) -> ScheduledTasksList:
        now = datetime.now(timezone.utc)
        stamp = now.isoformat().replace("+00:00", "Z")
        root = self._tasks_dir or SCHEDULED_TASKS_DIR
        try:
            entries = sorted(
                (entry for entry in os.scandir(root)
                 if entry.is_dir(follow_symlinks=False) and TASK_NAME_RE.match(entry.name)),
                key=lambda entry: entry.name,
            )
        except FileNotFoundError:
            return ScheduledTasksList(state="absent", as_of=stamp,
                                      detail="no scheduled-tasks folder exists")
        except OSError as exc:
            logger.debug("scheduled_tasks_unreadable", error_type=type(exc).__name__)
            return ScheduledTasksList(state="unreadable", as_of=stamp,
                                      detail="the scheduled-tasks folder could not be read")
        runs, runs_truncated = self._runs()
        tasks: List[ScheduledTask] = []
        for entry in entries[:MAX_TASKS]:
            tasks.append(self._task(entry, runs))
        return ScheduledTasksList(
            state="ok", tasks=tasks, total=len(entries),
            truncated=len(entries) > MAX_TASKS, runs_truncated=runs_truncated,
            as_of=stamp,
            detail="schedules are kept by the claude desktop app and are not recorded "
                   "on disk here; last run is read from each run's transcript",
        )

    @staticmethod
    def _task(entry: os.DirEntry, runs: Dict[str, Tuple[int, Optional[datetime]]]) -> ScheduledTask:
        skill = os.path.join(entry.path, "SKILL.md")
        text, file_state = _read_skill(skill)
        meta = parse_frontmatter(text) if text is not None else None
        if text is not None and meta is None:
            file_state = "no_frontmatter"
        meta = meta or {}
        name = meta.get("name") or entry.name
        schedule = next((meta[key] for key in _SCHEDULE_KEYS if meta.get(key)), None)
        count, last = runs.get(entry.name, runs.get(name, (0, None)))
        try:
            updated = datetime.fromtimestamp(os.stat(skill).st_mtime, tz=timezone.utc)
        except OSError:
            updated = None
        return ScheduledTask(
            id=entry.name, name=summary(name, 120) or entry.name,
            description=summary(meta.get("description"), DESCRIPTION_CHARS),
            file_state=file_state,
            schedule=summary(schedule, 120),
            schedule_source="frontmatter" if schedule else "not_recorded",
            next_run_at=None,
            last_run_at=last.isoformat().replace("+00:00", "Z") if last else None,
            runs_recorded=count,
            updated_at=updated.isoformat().replace("+00:00", "Z") if updated else None,
        )


READER = ScheduledTaskReader()
