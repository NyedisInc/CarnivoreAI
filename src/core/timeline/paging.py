
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.core.timeline import cursor as cursors, index_read, reading
from src.core.timeline.context import ExtractContext
from src.core.timeline.model import FILE_KEY_MAIN, Kind, TimelineEvent
from src.core.transcript_manifest.tail import line_serial

MAX_BACKWARD_BYTES: int = 8 * 1024 * 1024


class UnknownTurn(LookupError):
    pass


def cursor_at(real: str, conv: str, file_key: str, offset: int) -> Optional[cursors.Cursor]:
    if offset <= 0:
        return None
    start = cursors.line_start_before(real, offset)
    if start is None:
        return None
    with open(real, "rb") as handle:
        handle.seek(start)
        raw = handle.read(offset - start)
    return cursors.Cursor(conv, file_key, offset, line_serial(raw[:-1]))


def _page(events: List[TimelineEvent], nxt: Optional[cursors.Cursor], end: bool, next_before: Optional[int], pct: Optional[int],
          size: int, chips: Optional[List[Dict[str, Any]]] = None, indexing: bool = True) -> Dict[str, Any]:
    return {"events": events, "next": nxt.wire() if nxt else None, "end": end, "reset": None, "next_before": next_before,
            "indexing": {"pct": pct} if indexing else None, "size": size, "chips": chips or []}


def _newest_window(real: str, conv: str, pct: Optional[int], size: int) -> Dict[str, Any]:
    page = reading.read_tail(real, conv, FILE_KEY_MAIN)
    return _page(page.events, cursor_at(real, conv, FILE_KEY_MAIN, page.end), page.at_end, None, pct, size)


def _chip(state_dir: Path, conv: str, span: index_read.TurnSpan) -> Dict[str, Any]:
    rows = index_read.turn_rows(state_dir, conv, span.turn + 1, 1) or []
    row = rows[0] if rows and rows[0]["turn"] == span.turn else {}
    keys = ("calls", "top_tools", "replies", "bytes", "opened_at", "ended_at")
    return {"turn": span.turn, "giant": True, "start_off": span.start_off, "end_off": span.end_off, **{k: row.get(k) for k in keys}}


def _giant(state_dir: Path, real: str, conv: str, family: str, span: index_read.TurnSpan) -> Tuple[List[TimelineEvent], Dict[str, Any]]:
    fresh = ExtractContext(conv=conv, file_key=FILE_KEY_MAIN, family=family)
    head = reading.read_from(real, conv, FILE_KEY_MAIN, family, span.start_off, None, size=span.end_off, limit=1, ctx=fresh,
                             max_bytes=reading.MAX_PAGE_BYTES, remember=False)
    tail = reading.read_span_tail(real, conv, FILE_KEY_MAIN, family, head.end, span.end_off)
    replies = [e.model_copy(update={"turn": span.turn}) for e in tail.events if e.kind is Kind.REPLY]
    return [*head.events, *replies[-1:]], _chip(state_dir, conv, span)


def backward(state_dir: Path, real: str, conv: str, family: str, before_turn: Optional[int], turns: Optional[int]) -> Dict[str, Any]:
    size = os.stat(real).st_size
    wanted = min(turns or index_read.DEFAULT_TURNS, index_read.MAX_WANTED_TURNS)
    found = index_read.turns_before(state_dir, conv, before_turn, wanted + 1)
    pct = index_read.indexed_percent(state_dir, conv, size)
    if not found:
        if before_turn is not None:
            return _page([], None, False, None, pct, size)
        return _newest_window(real, conv, pct, size)
    if before_turn is None and pct != 100 and found[0].end_off < size:
        return _newest_window(real, conv, pct, size)
    more, picked, budget = len(found) > wanted, [], MAX_BACKWARD_BYTES
    for span in found[:wanted]:
        cost = span.end_off - span.start_off
        if cost <= MAX_BACKWARD_BYTES:
            if picked and cost > budget:
                more = True
                break
            budget -= cost
        picked.append(span)
    events: List[TimelineEvent] = []
    chips: List[Dict[str, Any]] = []
    for span in reversed(picked):
        if span.end_off - span.start_off > MAX_BACKWARD_BYTES:
            shown, chip = _giant(state_dir, real, conv, family, span)
            events.extend(shown)
            chips.append(chip)
        else:
            events.extend(reading.read_span(real, conv, FILE_KEY_MAIN, family, span.start_off, span.end_off).events)
    newest = cursor_at(real, conv, FILE_KEY_MAIN, found[0].end_off) if before_turn is None else None
    return _page(events, newest, before_turn is None and pct == 100, picked[-1].turn if more else None, pct, size, chips,
                 indexing=pct != 100)


def one_turn(state_dir: Path, real: str, conv: str, family: str, turn: int) -> Dict[str, Any]:
    found = index_read.turns_before(state_dir, conv, turn + 1, 1)
    if not found or found[0].turn != turn:
        raise UnknownTurn("the index has no such turn (yet)")
    span = found[0]
    stop = min(span.end_off, span.start_off + MAX_BACKWARD_BYTES)
    page = reading.read_span(real, conv, FILE_KEY_MAIN, family, span.start_off, stop)
    more = page.end < span.end_off
    return {"events": page.events, "next": cursor_at(real, conv, FILE_KEY_MAIN, page.end).wire() if more and page.end else None,
            "end": False, "reset": None, "next_before": None, "indexing": None, "size": os.stat(real).st_size, "chips": []}
