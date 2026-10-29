
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any, BinaryIO, Dict, List, Optional, Tuple

import structlog

from src.core.session_token_usage.cache import HEAD_BYTES, IncrementalCache
from src.core.session_token_usage.persist_spec import PersistSpec, decode_instant, encode_instant
from src.core.subagents.parent_index import parse_timestamp
from src.core.timers.contract import TIMER_TOOLS, TOOL_WAKEUP

logger = structlog.get_logger(__name__)

MAX_COLD_BYTES: int = 256 * 1024 * 1024

MAX_WAKEUPS: int = 200

MAX_TEXT: int = 2000

_TOOL_MARKS = tuple(('"name":"' + name + '"').encode() for name in TIMER_TOOLS)
_RESULT_MARK = b'"tool_result"'
_BASH_MARK = b'"name":"Bash"'
_BACKGROUND_MARK = b'"run_in_background":true'

_SLEEP_RE = re.compile(r"^\s*sleep\s+(\d+)\s*([smh]?)\b")
_SLEEP_UNIT_SECONDS: Dict[str, int] = {"": 1, "s": 1, "m": 60, "h": 3600}
_USER_MARK = b'"type":"user"'


@dataclass(frozen=True)
class TimerCall:

    tool: str
    tool_use_id: str
    created_at: datetime
    input: Any
    answered: bool = False
    result: Any = None
    result_text: Optional[str] = None


@dataclass(frozen=True)
class SleepCall:

    tool_use_id: str
    created_at: datetime
    delay_seconds: int
    command: str


@dataclass
class TimerIndex:

    calls: List[TimerCall] = field(default_factory=list)
    last_turn_start: Optional[datetime] = None
    pending: set = field(default_factory=set)
    sleeps: List[SleepCall] = field(default_factory=list)

    def copy(self) -> "TimerIndex":
        return TimerIndex(list(self.calls), self.last_turn_start, set(self.pending),
                          list(self.sleeps))


def _clip(value: Any) -> Any:
    return value[:MAX_TEXT] if isinstance(value, str) else value


def _clip_input(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _clip(item) for key, item in value.items()}
    return value


def _result_text(block: Dict[str, Any]) -> str:
    content = block.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            part.get("text", "") for part in content
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        )
    return ""


def _content(record: Dict[str, Any]) -> Any:
    message = record.get("message")
    return message.get("content") if isinstance(message, dict) else None


def _fold_calls(record: Dict[str, Any], at: datetime, index: TimerIndex) -> None:
    content = _content(record)
    if not isinstance(content, list):
        return
    for block in content:
        if not (isinstance(block, dict) and block.get("type") == "tool_use"):
            continue
        name = block.get("name")
        tool_use_id = block.get("id")
        if name in TIMER_TOOLS and isinstance(tool_use_id, str) and tool_use_id:
            index.calls.append(TimerCall(name, tool_use_id, at,
                                         _clip_input(block.get("input"))))
            index.pending.add(tool_use_id)
    _trim_wakeups(index)


def _trim_wakeups(index: TimerIndex) -> None:
    wakeups = [call for call in index.calls if call.tool == TOOL_WAKEUP]
    excess = len(wakeups) - MAX_WAKEUPS
    if excess <= 0:
        return
    dropped = {id(call) for call in wakeups[:excess]}
    for call in wakeups[:excess]:
        index.pending.discard(call.tool_use_id)
    index.calls = [call for call in index.calls if id(call) not in dropped]


def _fold_sleep_calls(record: Dict[str, Any], at: datetime, index: TimerIndex) -> None:
    content = _content(record)
    if not isinstance(content, list):
        return
    for block in content:
        if not (isinstance(block, dict) and block.get("type") == "tool_use"
                and block.get("name") == "Bash"):
            continue
        inputs = block.get("input")
        if not isinstance(inputs, dict) or inputs.get("run_in_background") is not True:
            continue
        command = inputs.get("command")
        tool_use_id = block.get("id")
        if not isinstance(command, str) or not isinstance(tool_use_id, str) or not tool_use_id:
            continue
        match = _SLEEP_RE.match(command)
        if not match:
            continue
        delay = int(match.group(1)) * _SLEEP_UNIT_SECONDS.get(match.group(2), 1)
        index.sleeps.append(SleepCall(tool_use_id, at, delay, _clip(command)))
    excess = len(index.sleeps) - MAX_WAKEUPS
    if excess > 0:
        index.sleeps = index.sleeps[excess:]


def _fold_results(record: Dict[str, Any], index: TimerIndex) -> None:
    content = _content(record)
    if not isinstance(content, list):
        return
    for block in content:
        if not (isinstance(block, dict) and block.get("type") == "tool_result"):
            continue
        tool_use_id = block.get("tool_use_id")
        if tool_use_id not in index.pending:
            continue
        index.pending.discard(tool_use_id)
        for position in range(len(index.calls) - 1, -1, -1):
            call = index.calls[position]
            if call.tool_use_id == tool_use_id and not call.answered:
                index.calls[position] = replace(
                    call, answered=True, result=record.get("toolUseResult"),
                    result_text=_clip(_result_text(block)),
                )
                break


def _is_turn_start(record: Dict[str, Any]) -> bool:
    if record.get("type") != "user" or record.get("isSidechain") is True:
        return False
    if record.get("toolUseResult") is not None:
        return False
    content = _content(record)
    if isinstance(content, list):
        return not any(isinstance(block, dict) and block.get("type") == "tool_result"
                       for block in content)
    return isinstance(content, str)


def scan_lines(handle: BinaryIO, index: TimerIndex) -> Tuple[TimerIndex, int]:
    offset = handle.tell()
    while True:
        line = handle.readline()
        if not line or not line.endswith(b"\n"):
            break
        offset += len(line)
        call = any(mark in line for mark in _TOOL_MARKS)
        sleep = _BASH_MARK in line and _BACKGROUND_MARK in line
        result = bool(index.pending) and _RESULT_MARK in line
        user = _USER_MARK in line
        if not (call or sleep or result or user):
            continue
        try:
            record = json.loads(line)
        except (ValueError, UnicodeDecodeError):
            continue
        if not isinstance(record, dict) or record.get("isSidechain") is True:
            continue
        at = parse_timestamp(record.get("timestamp"))
        if at is None:
            continue
        if record.get("type") == "assistant":
            if call:
                _fold_calls(record, at, index)
            if sleep:
                _fold_sleep_calls(record, at, index)
        if result and record.get("type") == "user":
            _fold_results(record, index)
        if user and _is_turn_start(record):
            if index.last_turn_start is None or at > index.last_turn_start:
                index.last_turn_start = at
    return index, offset


def encode_timer_index(index: TimerIndex) -> Dict[str, Any]:
    return {
        "c": [[c.tool, c.tool_use_id, encode_instant(c.created_at), c.input, c.answered,
               c.result, c.result_text] for c in index.calls],
        "t": encode_instant(index.last_turn_start),
        "p": sorted(index.pending),
        "s": [[s.tool_use_id, encode_instant(s.created_at), s.delay_seconds, s.command]
              for s in index.sleeps],
    }


def _need(value: Any, kind: type, what: str) -> Any:
    if type(value) is not kind:
        raise TypeError(f"{what} must be {kind.__name__}")
    return value


def _instant(value: Any, what: str) -> datetime:
    parsed = decode_instant(value)
    if parsed is None:
        raise ValueError(f"{what} must not be null")
    return parsed


def decode_timer_index(value: Any) -> TimerIndex:
    if not isinstance(value, dict) or set(value) != {"c", "t", "p", "s"}:
        raise ValueError("timer index payload has the wrong fields")
    calls: List[TimerCall] = []
    for row in _need(value["c"], list, "calls"):
        tool, tool_use_id, created, given, answered, result, text = row
        if text is not None:
            _need(text, str, "result_text")
        calls.append(TimerCall(_need(tool, str, "tool"), _need(tool_use_id, str, "tool_use_id"),
                               _instant(created, "created_at"), given,
                               _need(answered, bool, "answered"), result, text))
    pending = {_need(item, str, "pending id") for item in _need(value["p"], list, "pending")}
    sleeps: List[SleepCall] = []
    for row in _need(value["s"], list, "sleeps"):
        tool_use_id, created, delay, command = row
        sleeps.append(SleepCall(_need(tool_use_id, str, "tool_use_id"), _instant(created, "created_at"),
                                _need(delay, int, "delay_seconds"), _need(command, str, "command")))
    return TimerIndex(calls, decode_instant(value["t"]), pending, sleeps)


TIMER_INDEX_SPEC = PersistSpec(
    name="timers.timer_index",
    manual_version=1,
    sources=(
        "src.core.timers.index",
        "src.core.timers.contract",
        "src.core.subagents.parent_index",
        "src.core.session_token_usage.cache",
        "src.core.session_token_usage.persist_spec",
    ),
    encode=encode_timer_index,
    decode=decode_timer_index,
)

TIMER_INDEX_CACHE = IncrementalCache(persist=TIMER_INDEX_SPEC)


def read_timer_index(
    path: Path,
    *,
    cache: Optional[IncrementalCache] = None,
    max_cold_bytes: int = MAX_COLD_BYTES,
) -> Optional[TimerIndex]:
    store = cache if cache is not None else TIMER_INDEX_CACHE
    key = os.path.abspath(str(path))
    try:
        stat = os.stat(key)
        if stat.st_size > max_cold_bytes and not store.knows(key):
            logger.debug("timer_index_too_large_cold", size=stat.st_size)
            return None
        with open(key, "rb") as handle:
            head = handle.read(HEAD_BYTES)
            resume = store.resume_point(
                key, size=stat.st_size, mtime_ns=stat.st_mtime_ns, head=head
            )
            if resume is None:
                handle.seek(0)
                index = TimerIndex()
            else:
                offset, remembered = resume
                handle.seek(offset)
                index = remembered.copy()
            index, offset = scan_lines(handle, index)
    except OSError as exc:
        logger.debug("timer_index_unreadable", error=str(exc),
                     error_type=type(exc).__name__)
        return None
    store.remember(key, size=stat.st_size, mtime_ns=stat.st_mtime_ns,
                   head=head, offset=offset, totals=index)
    return index


__all__ = ["TimerCall", "SleepCall", "TimerIndex", "read_timer_index", "scan_lines",
           "TIMER_INDEX_CACHE", "MAX_WAKEUPS"]
