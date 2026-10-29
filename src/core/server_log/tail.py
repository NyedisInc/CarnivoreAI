"""A bounded, redacted, parsed tail of the structlog JSON-lines server log.

BOUNDED: only the last :data:`MAX_BYTES` of the file are ever read (a seek from the end), never the whole file, and at
most :data:`MAX_LINES` entries come back. REDACTED: every free-text value goes through the spectator path's redactor
(`stream_redactor.redact_whole`) before it leaves. The writer redacts structlog, stdlib and uvicorn records since #1859
(`redact.py`), but not everything in the file: lines written before that, raw stderr (an interpreter crash before
logging starts, a child's own output) and the launcher's banner lines never passed a redactor, so this read side stays.
A line that is not JSON, or has no event, is skipped here (the file also carries ``[STDERR]`` text and tracebacks);
the v2 read (`records.py`) keeps them as records and continuations.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, TypedDict

import structlog

from src.core.stream_redactor import redact_whole

logger = structlog.get_logger()

LEVELS = ("error", "warn", "info", "debug")
MAX_LINES = 500
DEFAULT_LINES = 200
MAX_BYTES = 2 * 1024 * 1024
MAX_VALUE_CHARS = 300
MAX_FIELDS_CHARS = 1200
LEVEL_ALIASES = {
    "warning": "warn", "warn": "warn", "error": "error", "critical": "error", "exception": "error", "fatal": "error",
    "info": "info", "debug": "debug", "notset": "debug",
}
_OWN_KEYS = frozenset({"event", "timestamp", "level"})
_SEPARATOR = "\n"


class LogEntry(TypedDict):

    timestamp: str
    level: str
    event: str
    fields: str


def _clip(text: str, limit: int) -> str:
    flat = text.replace("\r", " ").replace(_SEPARATOR, " ")
    return flat if len(flat) <= limit else flat[: limit - 1] + "~"


def read_tail_bytes(path: Path, max_bytes: int = MAX_BYTES) -> bytes:
    try:
        with path.open("rb") as handle:
            size = handle.seek(0, 2)
            start = max(0, size - max_bytes)
            handle.seek(start)
            data = handle.read(max_bytes)
    except FileNotFoundError:
        return b""
    if start > 0:
        newline = data.find(b"\n")
        data = b"" if newline < 0 else data[newline + 1:]
    return data


def parse_line(raw: str) -> Optional[Dict[str, Any]]:
    brace = raw.find("{")
    if brace < 0:
        return None
    try:
        record = json.loads(raw[brace:])
    except ValueError:
        return None
    if not isinstance(record, dict) or not isinstance(record.get("event"), str):
        return None
    return record


def _fields_text(record: Dict[str, Any]) -> str:
    pairs = []
    for key, value in record.items():
        if key in _OWN_KEYS:
            continue
        text = value if isinstance(value, str) else json.dumps(value, default=str, ensure_ascii=False)
        pairs.append(f"{key}={_clip(text, MAX_VALUE_CHARS)}")
    return _clip(" ".join(pairs), MAX_FIELDS_CHARS)


def _redact_all(pieces: List[str]) -> List[str]:
    if not pieces:
        return []
    out = redact_whole(_SEPARATOR.join(pieces)).split(_SEPARATOR)
    return out if len(out) == len(pieces) else ["[redacted]"] * len(pieces)


def entries_from(lines: Iterable[str], levels: Iterable[str], limit: int) -> List[LogEntry]:
    wanted = set(levels)
    kept: List[Dict[str, Any]] = []
    for raw in lines:
        record = parse_line(raw)
        if record is None:
            continue
        level = LEVEL_ALIASES.get(str(record.get("level", "info")).lower())
        if level is None or level not in wanted:
            continue
        kept.append({"record": record, "level": level})
    kept = kept[-limit:]
    pieces: List[str] = []
    for item in kept:
        pieces.append(_clip(item["record"]["event"], MAX_VALUE_CHARS))
        pieces.append(_fields_text(item["record"]))
    safe = _redact_all(pieces)
    return [
        LogEntry(
            timestamp=_clip(str(item["record"].get("timestamp", "")), 40),
            level=item["level"],
            event=safe[2 * i],
            fields=safe[2 * i + 1],
        )
        for i, item in enumerate(kept)
    ]


def read_entries(path: Path, levels: Iterable[str] = LEVELS, limit: int = DEFAULT_LINES) -> List[LogEntry]:
    capped = max(1, min(int(limit), MAX_LINES))
    text = read_tail_bytes(path, MAX_BYTES).decode("utf-8", errors="replace")
    return entries_from(text.splitlines(), [lv for lv in levels if lv in LEVELS], capped)
