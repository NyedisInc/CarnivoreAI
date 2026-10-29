
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple, TypedDict

from src.core.server_log import traceback_fold as fold
from src.core.server_log.tail import LEVEL_ALIASES, LEVELS, MAX_BYTES, parse_line
from src.core.stream_redactor import redact_whole

BACKUP_COUNT = 5
MAX_CONTINUATION_LINES = 400
MAX_CONTINUATION_BYTES = 64 * 1024
MAX_FIELD_CHARS = 2000
EXCEPTION_KEY = "exception"
_OWN_KEYS = frozenset({"event", "timestamp", "level"})
_PREFIX = re.compile(r"^\[(STDOUT|STDERR)\] ?")
_TRACEBACK_START = "Traceback (most recent call last)"
_FRAME_LINE = re.compile(r"^\s+File \"")
_CURSOR = re.compile(r"^(\d{1,20})-(\d{1,20})$")


class LogRecordOut(TypedDict):

    id: str
    timestamp: str
    level: str
    source: str
    event: str
    fields: Dict[str, str]
    lines: List[str]
    dropped_lines: int
    traceback: bool
    continues: bool
    approx_time: bool


class LogPageOut(TypedDict):

    records: List[LogRecordOut]
    head: Optional[str]
    before: Optional[str]
    gap: bool
    reset: bool


@dataclass(frozen=True)
class Cursor:

    ino: int
    offset: int

    def text(self) -> str:
        return f"{self.ino}-{self.offset}"


def parse_cursor(raw: Optional[str]) -> Optional[Cursor]:
    if raw is None or raw == "":
        return None
    match = _CURSOR.match(raw)
    if not match:
        raise ValueError("cursor must be <inode>-<offset>")
    return Cursor(int(match.group(1)), int(match.group(2)))


@dataclass
class _Draft:

    ino: int
    offset: int
    level: str
    source: str
    record: Optional[Dict[str, Any]]
    first: str = ""
    lines: List[str] = field(default_factory=list)
    size: int = 0
    dropped: int = 0
    traceback: bool = False
    continues: bool = False
    time_hint: str = ""
    block: str = ""
    summary: str = ""
    blanks: int = 0

    def add(self, text: str) -> None:
        if _FRAME_LINE.match(text) or text.startswith(_TRACEBACK_START):
            self.traceback = True
        if len(self.lines) >= MAX_CONTINUATION_LINES or self.size + len(text) > MAX_CONTINUATION_BYTES:
            self.dropped += 1
            return
        self.lines.append(text)
        self.size += len(text) + 1


def _siblings(path: Path) -> List[Path]:
    return [path, *(path.with_name(f"{path.name}.{i}") for i in range(1, BACKUP_COUNT + 1))]


def _stat(path: Path) -> Optional[Tuple[int, int]]:
    try:
        info = path.stat()
    except FileNotFoundError:
        return None
    return (info.st_ino, info.st_size)


def _find(path: Path, ino: int) -> Optional[Tuple[int, Path, int]]:
    for index, candidate in enumerate(_siblings(path)):
        info = _stat(candidate)
        if info is not None and info[0] == ino:
            return (index, candidate, info[1])
    return None


def _read(path: Path, start: int, end: int) -> bytes:
    if end <= start:
        return b""
    with path.open("rb") as handle:
        handle.seek(start)
        return handle.read(max(0, end - start))


def _lines(data: bytes, ino: int, start: int, aligned: bool) -> Tuple[List[Tuple[int, int, str]], int]:
    out: List[Tuple[int, int, str]] = []
    pos = 0
    if not aligned:
        newline = data.find(b"\n")
        if newline < 0:
            return out, start
        pos = newline + 1
    while True:
        newline = data.find(b"\n", pos)
        if newline < 0:
            break
        out.append((ino, start + pos, data[pos:newline].decode("utf-8", errors="replace").rstrip("\r")))
        pos = newline + 1
    return out, start + pos


def _block_draft(ino: int, offset: int, text: str, state: str, hint: str) -> _Draft:
    draft = _Draft(ino, offset, "error", "stderr", None, first=text, traceback=True, time_hint=hint, block=state)
    draft.add(text)
    return draft


def _join_block(draft: _Draft, text: str) -> bool:
    state = fold.advance(draft.block, text)
    if state is None:
        draft.block = ""
        return False
    for _ in range(draft.blanks):
        draft.add("")
    draft.blanks = 0
    draft.add(text)
    draft.block = state
    if state == fold.EXCEPTION:
        draft.summary = text
    return True


def group(lines: Iterable[Tuple[int, int, str]]) -> List[_Draft]:
    drafts: List[_Draft] = []
    hint = ""
    for ino, offset, raw in lines:
        record = parse_line(raw) if raw.strip() else None
        prefix = _PREFIX.match(raw)
        stream = prefix.group(1).lower() if prefix else ""
        text = raw[prefix.end():] if prefix else raw
        last = drafts[-1] if drafts else None
        if not text.strip():
            if last is not None and last.block:
                last.blanks += 1
            continue
        if record is not None:
            if isinstance(record.get("timestamp"), str) and record["timestamp"]:
                hint = record["timestamp"]
            level = LEVEL_ALIASES.get(str(record.get("level", "info")).lower(), "info")
            logger_name = record.get("logger")
            source = "stderr" if stream == "stderr" else logger_name if isinstance(logger_name, str) and logger_name else "server"
            drafts.append(_Draft(ino, offset, level, source, record, traceback=EXCEPTION_KEY in record, time_hint=hint))
            continue
        if last is not None and last.block and _join_block(last, text):
            continue
        if fold.is_header(text):
            drafts.append(_block_draft(ino, offset, text, fold.HEADER, hint))
            continue
        if fold.is_traceback_start(text):
            drafts.append(_block_draft(ino, offset, text, fold.FRAMES, hint))
            continue
        closed = last is not None and bool(last.summary) and not last.block and last.record is None
        if last is None or closed:
            level = fold.uvicorn_level(text) if closed else None
            drafts.append(_Draft(ino, offset, level or "error", "stderr", None, first=text, continues=last is None, time_hint=hint))
            continue
        last.add(text)
    return drafts


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "~"


def _value_text(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, default=str, ensure_ascii=False)


def finish(draft: _Draft) -> LogRecordOut:
    fields: Dict[str, str] = {}
    timestamp, event = "", draft.summary or draft.first
    if draft.record is not None:
        timestamp = str(draft.record.get("timestamp", ""))
        event = str(draft.record.get("event", ""))
        for key, value in draft.record.items():
            if key in _OWN_KEYS:
                continue
            limit = MAX_CONTINUATION_BYTES if key == EXCEPTION_KEY else MAX_FIELD_CHARS
            fields[_clip(str(key), 80)] = _clip(redact_whole(_value_text(value)), limit)
    block = redact_whole("\n".join(draft.lines)) if draft.lines else ""
    lines = block.split("\n") if block else []
    if len(lines) != len(draft.lines):
        lines = ["[redacted]"] * len(draft.lines)
    return LogRecordOut(
        id=Cursor(draft.ino, draft.offset).text(),
        timestamp=_clip(timestamp or draft.time_hint, 40),
        level=draft.level,
        source=_clip(draft.source, 80),
        event=_clip(redact_whole(event), MAX_FIELD_CHARS),
        fields=fields,
        lines=lines,
        dropped_lines=draft.dropped,
        traceback=draft.traceback,
        continues=draft.continues,
        approx_time=not timestamp and bool(draft.time_hint),
    )


@dataclass
class _Window:

    lines: List[Tuple[int, int, str]]
    head: Optional[Cursor]
    before: Optional[Cursor]
    gap: bool = False
    reset: bool = False


def _older(path: Path, index: int) -> Optional[Cursor]:
    siblings = _siblings(path)
    if index + 1 >= len(siblings):
        return None
    info = _stat(siblings[index + 1])
    return Cursor(info[0], info[1]) if info else None


def _back(path: Path, index: int, file: Path, ino: int, end: int, max_bytes: int) -> _Window:
    start = max(0, end - max_bytes)
    lines, _ = _lines(_read(file, start, end), ino, start, start == 0)
    before = Cursor(ino, lines[0][1]) if lines and lines[0][1] > 0 else _older(path, index)
    return _Window(lines=lines, head=None, before=before)


def _tail(path: Path, max_bytes: int, reset: bool = False) -> _Window:
    info = _stat(path)
    if info is None:
        return _Window(lines=[], head=None, before=None, reset=reset)
    ino, size = info
    start = max(0, size - max_bytes)
    lines, end = _lines(_read(path, start, size), ino, start, start == 0)
    before = Cursor(ino, lines[0][1]) if lines and lines[0][1] > 0 else (_older(path, 0) if start == 0 else Cursor(ino, start))
    return _Window(lines=lines, head=Cursor(ino, end), before=before, reset=reset)


def _since(path: Path, cursor: Cursor, max_bytes: int) -> _Window:
    info = _stat(path)
    if info is None:
        return _Window(lines=[], head=None, before=None, reset=True)
    ino, size = info
    segments: List[Tuple[Path, int, int, int]] = []
    if cursor.ino == ino:
        if cursor.offset > size:
            return _tail(path, max_bytes, reset=True)
        segments.append((path, ino, cursor.offset, size))
    else:
        found = _find(path, cursor.ino)
        if found is None or cursor.offset > found[2]:
            return _tail(path, max_bytes, reset=True)
        segments += [(found[1], cursor.ino, cursor.offset, found[2]), (path, ino, 0, size)]
    if sum(end - start for _, _, start, end in segments) > max_bytes:
        window = _tail(path, max_bytes)
        window.gap = True
        return window
    lines: List[Tuple[int, int, str]] = []
    head = cursor
    for file, file_ino, start, end in segments:
        got, stop = _lines(_read(file, start, end), file_ino, start, True)
        lines += got
        head = Cursor(file_ino, stop)
    return _Window(lines=lines, head=head, before=None)


def read_page(
    path: Path,
    *,
    since: Optional[Cursor] = None,
    before: Optional[Cursor] = None,
    levels: Iterable[str] = LEVELS,
    limit: int = 300,
    max_bytes: int = MAX_BYTES,
) -> LogPageOut:
    if since is not None:
        window = _since(path, since, max_bytes)
    elif before is not None:
        found = _find(path, before.ino)
        if found is None or before.offset > found[2]:
            window = _Window(lines=[], head=None, before=None)
        else:
            window = _back(path, found[0], found[1], before.ino, before.offset, max_bytes)
    else:
        window = _tail(path, max_bytes)
    wanted = set(levels)
    drafts = [d for d in group(window.lines) if d.level in wanted]
    gap = window.gap
    if len(drafts) > limit:
        drafts = drafts[-limit:]
        gap = gap or since is not None
        if since is None:
            window.before = Cursor(drafts[0].ino, drafts[0].offset)
    return LogPageOut(
        records=[finish(d) for d in drafts],
        head=window.head.text() if window.head else None,
        before=window.before.text() if window.before else None,
        gap=gap,
        reset=window.reset,
    )
