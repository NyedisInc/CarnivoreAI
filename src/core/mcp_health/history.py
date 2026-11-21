
from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Sequence, Tuple

import structlog

from src.core.mcp_health.fold import McpEvent, extract_mcp_events

log = structlog.get_logger()

SCAN_MAX_BYTES: int = 32 * 1024 * 1024
_CHUNK_BYTES: int = 4 * 1024 * 1024
_MARKERS: Tuple[bytes, ...] = (
    b"mcp_instructions_delta", b"deferred_tools_delta", b"<local-command-stdout>Reconnected",
    b"<local-command-stdout>Successfully reconnected",
)
MAX_EVENTS: int = 400
MAX_PATHS: int = 512


@dataclass
class HistoryEntry:

    seen_to: int = 0
    events: List[McpEvent] = field(default_factory=list)

    def is_stale(self, file_size: int) -> bool:
        return file_size < self.seen_to

    def scan_start(self, scanned_from: int) -> int:
        return max(self.seen_to, scanned_from - SCAN_MAX_BYTES, 0)

    def record(self, merged: Sequence[McpEvent], file_size: int) -> None:
        self.events = list(merged)
        self.seen_to = max(self.seen_to, file_size)


_TABLE: Dict[str, HistoryEntry] = {}
_LOCK = threading.Lock()


def entry_copy(path: str) -> Optional[HistoryEntry]:
    with _LOCK:
        entry = _TABLE.get(path)
        return HistoryEntry(entry.seen_to, list(entry.events)) if entry is not None else None


def reset_history() -> None:
    with _LOCK:
        _TABLE.clear()


def _event_key(e: McpEvent) -> tuple:
    return (e.at, e.exact, e.removed, e.added, e.failed, e.needs_auth, e.reconnect, e.all_connected)


def scan_mcp_events(path: str, start: int, end: int) -> Tuple[McpEvent, ...]:
    if end <= start:
        return ()
    records: List[dict] = []
    try:
        with open(path, "rb") as handle:
            handle.seek(start)
            remaining = end - start
            carry = b""
            first = start > 0
            while remaining > 0:
                block = handle.read(min(_CHUNK_BYTES, remaining))
                if not block:
                    break
                remaining -= len(block)
                lines = (carry + block).split(b"\n")
                carry = lines.pop()
                if first and lines:
                    lines = lines[1:]
                    first = False
                elif first:
                    continue
                records.extend(_parse_marked(lines))
            if carry and not first:
                records.extend(_parse_marked([carry]))
    except OSError as exc:
        log.debug("mcp_history_scan_unreadable", path=path, error=str(exc))
        return ()
    return extract_mcp_events(records)


def _parse_marked(lines: Sequence[bytes]) -> List[dict]:
    out: List[dict] = []
    for line in lines:
        if not any(marker in line for marker in _MARKERS):
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict):
            out.append(record)
    return out


def combine_mcp_events(old: Sequence[McpEvent], new: Sequence[McpEvent]) -> List[McpEvent]:
    by_key = {_event_key(e): e for e in list(old) + list(new)}
    merged = sorted(by_key.values(), key=lambda e: (e.at is not None, e.at or datetime.min))
    newest_heal: Dict[str, McpEvent] = {}
    kept: List[McpEvent] = []
    for e in merged:
        if e.reconnect and not e.exact and len(e.added) == 1:
            newest_heal[e.added[0]] = e
        else:
            kept.append(e)
    kept = kept[-MAX_EVENTS:]
    return sorted(kept + list(newest_heal.values()), key=lambda e: (e.at is not None, e.at or datetime.min))


def join_history(old: Sequence[McpEvent], found: Sequence[McpEvent], window_events: Sequence[McpEvent]) -> List[McpEvent]:
    return combine_mcp_events(combine_mcp_events(old, found), window_events)


def merge_mcp_history(
    path: Optional[str], window_events: Sequence[McpEvent], *, scanned_from: int, file_size: int
) -> Tuple[McpEvent, ...]:
    if not path:
        return tuple(window_events)
    with _LOCK:
        entry = _TABLE.get(path)
        if entry is None or entry.is_stale(file_size):
            if len(_TABLE) >= MAX_PATHS:
                _TABLE.clear()
            entry = _TABLE[path] = HistoryEntry()
        scan_from = entry.scan_start(scanned_from)
        old = tuple(entry.events)
    found = scan_mcp_events(path, scan_from, scanned_from) if scanned_from > scan_from else ()
    merged = join_history(old, found, window_events)
    with _LOCK:
        entry.record(merged, file_size)
    return tuple(merged)
