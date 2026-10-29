
from __future__ import annotations

import copy
import json
import re
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Dict, Iterable, List, Optional, Tuple

import structlog

from src.core.timers.redact import summary
from src.models.session_tasks import TaskCounts, TaskItem

logger = structlog.get_logger(__name__)

MAX_BYTES: int = 2 * 1024 * 1024 * 1024
MAX_REFUSALS: int = 64
TEXT_CHARS: int = 240
MAX_ENTRIES: int = 64
HEAD_BYTES: int = 256
MAX_TASKS: int = 200

_MARKS = (b"TodoWrite", b"TaskCreate", b"TaskUpdate", b"Task #")
_STATUSES = frozenset({"pending", "in_progress", "completed"})
_CREATED_RE = re.compile(r"Task #(\w+)")


TOO_LARGE = "transcript too large"


class TranscriptUnreadable(Exception):

    def __init__(self, message: str, *, repeat: bool = False) -> None:
        super().__init__(message)
        self.repeat = repeat


def _status(value: Any) -> str:
    return value if value in _STATUSES else "pending"


def _text(value: Any) -> Optional[str]:
    return summary(value, TEXT_CHARS)


def _blocks(record: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    content = (record.get("message") or {}).get("content")
    return [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []


class _Fold:

    def __init__(self) -> None:
        self.tasks: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
        self.pending_create: Dict[str, Dict[str, Any]] = {}

    def todo_write(self, todos: Any) -> None:
        self.tasks.clear()
        self.pending_create.clear()
        if not isinstance(todos, list):
            return
        for at, todo in enumerate(todos, start=1):
            if isinstance(todo, dict) and _text(todo.get("content")):
                self.tasks[str(at)] = {"subject": _text(todo.get("content")), "active_form": _text(todo.get("activeForm")),
                                       "status": _status(todo.get("status"))}

    def task_update(self, args: Dict[str, Any]) -> None:
        key = str(args.get("taskId", ""))
        task = self.tasks.get(key)
        if task is None:
            return
        if args.get("status") == "deleted":
            del self.tasks[key]
            return
        if "status" in args:
            task["status"] = _status(args["status"])
        for field, name in (("subject", "subject"), ("activeForm", "active_form")):
            if _text(args.get(field)):
                task[name] = _text(args[field])

    def task_result(self, record: Dict[str, Any], block: Dict[str, Any]) -> None:
        args = self.pending_create.pop(str(block.get("tool_use_id", "")), None)
        if args is None or not _text(args.get("subject")):
            return
        made = (record.get("toolUseResult") or {}).get("task") if isinstance(record.get("toolUseResult"), dict) else None
        key = str(made.get("id")) if isinstance(made, dict) and made.get("id") is not None else None
        if key is None:
            found = _CREATED_RE.search(json.dumps(block.get("content")))
            key = found.group(1) if found else str(len(self.tasks) + 1)
        self.tasks[key] = {"subject": _text(args.get("subject")), "active_form": _text(args.get("activeForm")),
                           "status": "pending"}

    def feed(self, record: Dict[str, Any]) -> None:
        for block in _blocks(record):
            kind = block.get("type")
            args = block.get("input") if isinstance(block.get("input"), dict) else {}
            if kind == "tool_use" and block.get("name") == "TodoWrite":
                self.todo_write(args.get("todos"))
            elif kind == "tool_use" and block.get("name") == "TaskCreate":
                self.pending_create[str(block.get("id", ""))] = args
            elif kind == "tool_use" and block.get("name") == "TaskUpdate":
                self.task_update(args)
            elif kind == "tool_result":
                self.task_result(record, block)

    def items(self) -> Tuple[List[TaskItem], int]:
        items = [TaskItem(id=key, subject=t["subject"], active_form=t["active_form"], status=t["status"])
                 for key, t in self.tasks.items()]
        return items[:MAX_TASKS], max(0, len(items) - MAX_TASKS)


def _feed_line(fold: _Fold, line: bytes) -> None:
    if not any(mark in line for mark in _MARKS):
        return
    try:
        record = json.loads(line)
    except ValueError:
        return
    if isinstance(record, dict) and not record.get("isSidechain"):
        fold.feed(record)


def _advance(handle: BinaryIO, fold: _Fold) -> Tuple[int, List[TaskItem]]:
    offset = handle.tell()
    tail: Optional[bytes] = None
    for line in handle:
        if line.endswith(b"\n"):
            offset += len(line)
            _feed_line(fold, line)
        else:
            tail = line
    if tail is None or not any(mark in tail for mark in _MARKS):
        return offset, fold.items()[0]
    tentative = copy.deepcopy(fold)
    _feed_line(tentative, tail)
    return offset, tentative.items()[0]


def fold_transcript(path: Path) -> List[TaskItem]:
    try:
        if path.stat().st_size > MAX_BYTES:
            raise TranscriptUnreadable(TOO_LARGE)
        with path.open("rb") as handle:
            return _advance(handle, _Fold())[1]
    except OSError as exc:
        raise TranscriptUnreadable(str(exc)) from exc


def count(items: Iterable[TaskItem]) -> TaskCounts:
    counts = TaskCounts()
    for item in items:
        setattr(counts, item.status, getattr(counts, item.status) + 1)
    return counts


@dataclass
class _Memo:

    ident: Tuple[int, int]
    signature: Tuple[int, int]
    offset: int
    head: bytes
    fold: _Fold
    items: List[TaskItem]


class TaskReader:

    def __init__(self, *, max_entries: int = MAX_ENTRIES) -> None:
        self._max = max_entries
        self._lock = threading.Lock()
        self._entries: "OrderedDict[Path, _Memo]" = OrderedDict()
        self._refusals: "OrderedDict[Path, Tuple[Optional[Tuple[int, int]], int, str]]" = OrderedDict()

    def _store(self, path: Path, memo: _Memo) -> None:
        with self._lock:
            self._entries[path] = memo
            self._entries.move_to_end(path)
            while len(self._entries) > self._max:
                self._entries.popitem(last=False)

    def _refuse(self, path: Path, ident: Optional[Tuple[int, int]], size: int, message: str) -> TranscriptUnreadable:
        key = (ident, size.bit_length(), message)
        with self._lock:
            repeat = self._refusals.get(path) == key
            self._refusals[path] = key
            self._refusals.move_to_end(path)
            while len(self._refusals) > MAX_REFUSALS:
                self._refusals.popitem(last=False)
        return TranscriptUnreadable(message, repeat=repeat)

    def read(self, path: Path) -> List[TaskItem]:
        try:
            stat = path.stat()
        except OSError as exc:
            with self._lock:
                self._entries.pop(path, None)
            raise self._refuse(path, None, 0, str(exc)) from exc
        ident = (stat.st_dev, stat.st_ino)
        signature = (stat.st_mtime_ns, stat.st_size)
        if stat.st_size > MAX_BYTES:
            with self._lock:
                self._entries.pop(path, None)
            raise self._refuse(path, ident, stat.st_size, TOO_LARGE)
        with self._lock:
            memo = self._entries.pop(path, None)
        if memo is not None and memo.ident == ident and memo.signature == signature:
            self._store(path, memo)
            return memo.items
        try:
            fresh = self._advance_from(path, memo, ident, signature, stat.st_size)
        except TranscriptUnreadable as exc:
            raise self._refuse(path, ident, stat.st_size, str(exc)) from exc
        with self._lock:
            self._refusals.pop(path, None)
        self._store(path, fresh)
        return fresh.items

    @staticmethod
    def _advance_from(path: Path, memo: Optional[_Memo], ident: Tuple[int, int],
                      signature: Tuple[int, int], size: int) -> _Memo:
        try:
            with path.open("rb") as handle:
                head = handle.read(HEAD_BYTES)
                resume = (memo is not None and memo.ident == ident and size >= memo.offset
                          and head[:len(memo.head)] == memo.head and len(head) >= len(memo.head))
                if resume:
                    handle.seek(memo.offset)
                    fold = memo.fold
                else:
                    handle.seek(0)
                    fold = _Fold()
                offset, items = _advance(handle, fold)
        except OSError as exc:
            raise TranscriptUnreadable(str(exc)) from exc
        return _Memo(ident, signature, offset, head, fold, items)
