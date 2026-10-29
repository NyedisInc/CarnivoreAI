
from __future__ import annotations

import os
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, Callable, Dict, List, Optional, Tuple

import structlog

from src.core.subagents.contract import (
    FILE_KIND_LINE,
    SHAPE_OK,
    SUBAGENT_LINE_CONTRACT_VERSION,
    SHAPE_UNRECOGNIZED,
    ShapeCheck,
    check_line,
    check_meta,
)
from src.core.subagents.parent_index import parse_timestamp
from src.core.subagents.shape_alert import report_unrecognized
from src.core.transcript_contract import complete_lines, decode_json

logger = structlog.get_logger(__name__)

WINDOW_BYTES: int = 64 * 1024
MAX_WINDOW_BYTES: int = 4 * 1024 * 1024

FILE_ABSENT: str = "absent"
FILE_UNREADABLE: str = "unreadable"

MAX_CACHED_FILES: int = 4096


@dataclass(frozen=True)
class LineFacts:

    state: str
    started_at: Optional[datetime] = None
    last_at: Optional[datetime] = None
    last_type: Optional[str] = None
    claude_code_version: Optional[str] = None
    mtime: Optional[datetime] = None


@dataclass(frozen=True)
class MetaFacts:

    state: str
    fields: Optional[Dict[str, Any]] = None
    unknown_keys: Tuple[str, ...] = ()


_line_cache: "OrderedDict[str, Tuple[int, int, LineFacts]]" = OrderedDict()
_meta_cache: "OrderedDict[str, Tuple[int, int, MetaFacts]]" = OrderedDict()


def _remember(cache: OrderedDict, key: str, value: Tuple[int, int, Any]) -> None:
    cache[key] = value
    cache.move_to_end(key)
    while len(cache) > MAX_CACHED_FILES:
        cache.popitem(last=False)


def _cached(cache: OrderedDict, key: str, size: int, mtime_ns: int) -> Optional[Any]:
    hit = cache.get(key)
    if hit is None or hit[0] != size or hit[1] != mtime_ns:
        return None
    cache.move_to_end(key)
    return hit[2]


def _first_record(handle, size: int) -> Tuple[Optional[Any], bool]:
    window = WINDOW_BYTES
    while True:
        handle.seek(0)
        chunk = handle.read(min(window, size))
        for line in complete_lines(chunk, at_start=True):
            ok, record = decode_json(line)
            if ok:
                return record, False
        if window >= size or window >= MAX_WINDOW_BYTES:
            return None, window < size
        window *= 2


def _is_injected(record: Any) -> bool:
    if not isinstance(record, dict):
        return False
    kind = record.get("type")
    if kind == "assistant":
        return False
    if kind == "user":
        return record.get("isMeta") is True
    return True


def last_record(
    handle: BinaryIO, size: int, skip: Callable[[Any], bool] = _is_injected
) -> Tuple[Optional[Any], bool]:
    window = WINDOW_BYTES
    fallback: Optional[Any] = None
    while True:
        start = max(0, size - window)
        handle.seek(start)
        chunk = handle.read(size - start)
        for line in reversed(complete_lines(chunk, at_start=start == 0)):
            ok, record = decode_json(line)
            if not ok:
                continue
            if not skip(record):
                return record, False
            if fallback is None:
                fallback = record
        if start == 0:
            return fallback, False
        if window >= MAX_WINDOW_BYTES:
            return fallback, fallback is None
        window *= 2


def _check_and_alert(record: Any) -> ShapeCheck:
    check = check_line(record)
    if not check.recognized:
        version = record.get("version") if isinstance(record, dict) else None
        report_unrecognized(check, claude_code_version=version if isinstance(version, str) else None)
    return check


def read_line_facts(path: Path) -> LineFacts:
    key = str(path)
    try:
        stat = os.stat(key)
    except FileNotFoundError:
        return LineFacts(FILE_ABSENT)
    except OSError as exc:
        logger.debug("subagent_line_stat_failed", error=str(exc))
        return LineFacts(FILE_UNREADABLE)
    hit = _cached(_line_cache, key, stat.st_size, stat.st_mtime_ns)
    if hit is not None:
        return hit
    mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
    facts = _read_line_facts_uncached(key, stat.st_size, mtime)
    _remember(_line_cache, key, (stat.st_size, stat.st_mtime_ns, facts))
    return facts


def _read_line_facts_uncached(key: str, size: int, mtime: datetime) -> LineFacts:
    if size == 0:
        return LineFacts(SHAPE_OK, mtime=mtime)
    try:
        with open(key, "rb") as handle:
            first, first_capped = _first_record(handle, size)
            last, last_capped = last_record(handle, size)
    except OSError as exc:
        logger.debug("subagent_line_unreadable", error=str(exc))
        return LineFacts(FILE_UNREADABLE, mtime=mtime)
    if last is None:
        state = FILE_UNREADABLE if (first_capped or last_capped) else SHAPE_OK
        return LineFacts(state, mtime=mtime)
    for record in (first, last):
        if record is not None and not _check_and_alert(record).recognized:
            return LineFacts(SHAPE_UNRECOGNIZED, mtime=mtime)
    last_at = parse_timestamp(last.get("timestamp"))
    if last_at is None:
        report_unrecognized(ShapeCheck(
            FILE_KIND_LINE, SUBAGENT_LINE_CONTRACT_VERSION, SHAPE_UNRECOGNIZED,
            ("key timestamp is not an ISO-8601 instant",)))
        return LineFacts(SHAPE_UNRECOGNIZED, mtime=mtime)
    version = last.get("version")
    return LineFacts(
        SHAPE_OK,
        started_at=parse_timestamp(first.get("timestamp")) if first else None,
        last_at=last_at,
        last_type=last.get("type"),
        claude_code_version=version if isinstance(version, str) else None,
        mtime=mtime,
    )


def read_meta_facts(path: Path) -> MetaFacts:
    key = str(path)
    try:
        stat = os.stat(key)
    except FileNotFoundError:
        return MetaFacts(FILE_ABSENT)
    except OSError as exc:
        logger.debug("subagent_meta_stat_failed", error=str(exc))
        return MetaFacts(FILE_UNREADABLE)
    hit = _cached(_meta_cache, key, stat.st_size, stat.st_mtime_ns)
    if hit is not None:
        return hit
    try:
        with open(key, "rb") as handle:
            raw = handle.read(MAX_WINDOW_BYTES + 1)
    except OSError as exc:
        logger.debug("subagent_meta_unreadable", error=str(exc))
        return MetaFacts(FILE_UNREADABLE)
    ok, document = decode_json(raw) if len(raw) <= MAX_WINDOW_BYTES else (False, None)
    if not ok:
        facts = MetaFacts(FILE_UNREADABLE)
    else:
        check = check_meta(document)
        if check.recognized:
            facts = MetaFacts(SHAPE_OK, dict(document), check.unknown_keys)
        else:
            report_unrecognized(check)
            facts = MetaFacts(SHAPE_UNRECOGNIZED)
    _remember(_meta_cache, key, (stat.st_size, stat.st_mtime_ns, facts))
    return facts


def reset_caches_for_tests() -> None:
    _line_cache.clear()
    _meta_cache.clear()
