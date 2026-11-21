
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Iterator, List, Optional, Tuple

import structlog

from src.core.pipeline import reader as pipeline_reader
from src.core.timeline import ctx_cache, cursor as cursors
from src.core.timeline.context import ExtractContext
from src.core.timeline.extract import MAX_LINE_BYTES, extract_line
from src.core.timeline.model import FAMILY_CLAUDE, Family, TimelineEvent
from src.core.transcript_manifest.tail import line_serial, serial_of_record

log = structlog.get_logger(__name__)

MAX_PAGE_BYTES: int = 1024 * 1024
DEFAULT_PAGE_EVENTS: int = 500
MAX_PAGE_EVENTS: int = 500
WARMUP_BYTES: int = 1024 * 1024
PEEK_BYTES: int = 64 * 1024
TAIL_WINDOW_BYTES: int = 1024 * 1024
NEWLINE = b"\n"
_RULE_ERRORS = (ValueError, TypeError, KeyError, AttributeError)


@dataclass
class Page:

    events: List[TimelineEvent] = field(default_factory=list)
    start: int = 0
    end: int = 0
    last_serial: Optional[str] = None
    size: int = 0
    at_end: bool = False
    reset: Optional[str] = None


def split_lines(data: bytes, base: int) -> Iterator[Tuple[int, int, bytes]]:
    cursor = 0
    while True:
        found = data.find(NEWLINE, cursor)
        if found < 0:
            return
        yield base + cursor, base + found + 1, data[cursor:found]
        cursor = found + 1


def line_events(ctx: ExtractContext, body: bytes, end: int) -> Tuple[List[TimelineEvent], str]:
    if len(body) > MAX_LINE_BYTES:
        serial = line_serial(body)
    else:
        try:
            record = json.loads(body)
        except ValueError:
            record = None
        serial = serial_of_record(record, body)
    try:
        return extract_line(ctx, body, end, serial=serial), serial
    except _RULE_ERRORS as exc:
        log.warning("timeline_read_extract_failed", conv=ctx.conv, file_key=ctx.file_key, end=end, error=type(exc).__name__)
        return [], serial


def warm_context(conv: str, file_key: str, family: Family, real: str, start: int) -> ExtractContext:
    ctx = ExtractContext(conv=conv, file_key=file_key, family=family)
    if start == 0:
        return ctx
    low = max(0, start - WARMUP_BYTES)
    with open(real, "rb") as handle:
        handle.seek(low)
        chunk = handle.read(start - low)
    base = low
    if low > 0:
        cut = chunk.find(NEWLINE)
        if cut < 0:
            return ctx
        chunk, base = chunk[cut + 1:], low + cut + 1
    for _line_start, line_end, body in split_lines(chunk, base):
        if len(body) <= MAX_LINE_BYTES:
            line_events(ctx, body, line_end)
    return ctx


def has_line_after(real: str, offset: int, size: int) -> bool:
    if offset >= size:
        return False
    with open(real, "rb") as handle:
        handle.seek(offset)
        window = handle.read(min(PEEK_BYTES, size - offset))
    return NEWLINE in window or size - offset > PEEK_BYTES


def read_from(real: str, conv: str, file_key: str, family: Family, start: int, serial: Optional[str], *, size: int,
              limit: int = DEFAULT_PAGE_EVENTS, ctx: Optional[ExtractContext] = None,
              max_bytes: int = MAX_PAGE_BYTES, remember: bool = True) -> Page:
    limit = max(1, min(limit, MAX_PAGE_EVENTS))
    ctx = ctx or ctx_cache.take(real, start) or warm_context(conv, file_key, family, real, start)
    data = pipeline_reader.read_slice(real, start, size, max_bytes)
    page = Page(start=start, end=start, last_serial=serial, size=size)
    finished = True
    for _line_start, line_end, body in split_lines(data, start):
        if len(page.events) >= limit:
            finished = False
            break
        events, line_serial_ = line_events(ctx, body, line_end)
        page.events.extend(events)
        page.end, page.last_serial = line_end, line_serial_
    page.at_end = finished and not has_line_after(real, page.end, size)
    if remember and page.end > start:
        ctx_cache.put(real, page.end, ctx)
    return page


def read_forward(real: str, conv: str, file_key: str, after: Optional[cursors.Cursor], *, family: Family = FAMILY_CLAUDE,
                 limit: int = DEFAULT_PAGE_EVENTS) -> Page:
    size = os.stat(real).st_size
    if after is None:
        return read_from(real, conv, file_key, family, 0, None, size=size, limit=limit)
    reset = cursors.check(real, after, size=size)
    if reset is not None:
        return Page(start=after.offset, end=after.offset, last_serial=after.serial or None, size=size, reset=reset)
    return read_from(real, conv, file_key, family, after.offset, after.serial or None, size=size, limit=limit)


def read_span(real: str, conv: str, file_key: str, family: Family, start: int, end: int) -> Page:
    size = min(end, os.stat(real).st_size)
    return read_from(real, conv, file_key, family, start, None, size=size, limit=MAX_PAGE_EVENTS * 1000,
                     ctx=ExtractContext(conv=conv, file_key=file_key, family=family), max_bytes=max(1, size - start),
                     remember=False)


def read_tail(real: str, conv: str, file_key: str, family: Family = FAMILY_CLAUDE) -> Page:
    from src.core.claude_title_sync import align_to_record_start  # noqa: PLC0415

    size = os.stat(real).st_size
    nominal = max(0, size - TAIL_WINDOW_BYTES)
    start = 0
    if nominal:
        with open(real, "rb") as handle:
            aligned = align_to_record_start(handle, nominal, max_scan=TAIL_WINDOW_BYTES)
        start = aligned if aligned is not None else nominal
    ctx = ExtractContext(conv=conv, file_key=file_key, family=family)
    return read_from(real, conv, file_key, family, start, None, size=size, limit=MAX_PAGE_EVENTS * 1000, ctx=ctx,
                     max_bytes=size - start + 1, remember=False)


def read_span_tail(real: str, conv: str, file_key: str, family: Family, start: int, end: int,
                   window: int = TAIL_WINDOW_BYTES) -> Page:
    size = min(end, os.stat(real).st_size)
    nominal = max(start, size - window)
    opens = nominal
    if nominal > start:
        with open(real, "rb") as handle:
            handle.seek(nominal - 1)
            data = handle.read(1 + size - nominal)
        if data[:1] != NEWLINE:
            cut = data.find(NEWLINE, 1)
            if cut < 0:
                return Page(start=start, end=start, size=size)
            opens = nominal - 1 + cut + 1
    return read_from(real, conv, file_key, family, opens, None, size=size, limit=MAX_PAGE_EVENTS * 1000,
                     ctx=ExtractContext(conv=conv, file_key=file_key, family=family), max_bytes=max(1, size - opens), remember=False)
