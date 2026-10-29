
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

from src.core.message_model_secrets import SecretFinding

REDACTION_CHAR: str = "*"

_ESC: str = "\x1b"
_BEL: str = "\x07"

_ABORT: str = "\x18\x1a"

_ST_C1: str = "\u009c"

_STRING_INTRODUCERS: str = "]PX^_"

_C1_INTRODUCERS: dict = {
    "\u009b": "[",
    "\u009d": "]",
    "\u0090": "P",
    "\u0098": "X",
    "\u009e": "^",
    "\u009f": "_",
}

_CSI_STOP_RE = re.compile("[\x18\x1a\x1b\x40-\x7e\x80-\U0010ffff]")
_ESCAPE_STOP_RE = re.compile("[\x18\x1a\x1b\x30-\x7e\x80-\U0010ffff]")

_STRING_STOP_RE = re.compile("[\x07\x18\x1a\x1b\x80-\x9f]")

_SKIP_RE = re.compile(
    "[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f"
    "\u00ad\u200b-\u200d\u2060\ufeff\udc80-\udcff]"
)

_OSC_CLIPBOARD: str = "52"


def _is_c1(char: str) -> bool:
    return "\x80" <= char <= "\x9f"


def _introducer(raw: str, start: int) -> Tuple[str, int]:
    if raw[start] in _C1_INTRODUCERS:
        return _C1_INTRODUCERS[raw[start]], start + 1
    if start + 1 >= len(raw):
        return "", -1
    return raw[start + 1], start + 2


def _interrupts(char: str) -> bool:
    return char == _ESC or _is_c1(char)


def is_sequence_start(char: str) -> bool:
    return char == _ESC or char in _C1_INTRODUCERS


def _escape_end(raw: str, start: int) -> int:
    kind, cursor = _introducer(raw, start)
    if not kind:
        return -1

    if kind in _STRING_INTRODUCERS:
        _, end = _string_end(raw, cursor)
        return end

    stop_re = _CSI_STOP_RE if kind == "[" else _ESCAPE_STOP_RE
    if kind != "[":
        cursor = start + 1
    found = stop_re.search(raw, cursor)
    if found is None:
        return -1
    char = found.group()
    if _interrupts(char):
        return found.start()
    return found.start() + 1


def _string_end(raw: str, cursor: int) -> Tuple[int, int]:
    found = _STRING_STOP_RE.search(raw, cursor)
    if found is None:
        return -1, -1
    stop = found.start()
    char = found.group()
    if char == _ESC:
        if stop + 1 >= len(raw):
            return -1, -1
        if raw[stop + 1] == "\\":
            return stop, stop + 2
        return stop, stop
    if _is_c1(char) and char != _ST_C1:
        return stop, stop
    return stop, stop + 1


def _dcs_data_start(raw: str, start: int, end: int) -> int:
    for cursor in range(start, end):
        if "\x40" <= raw[cursor] <= "\x7e":
            return cursor + 1
        if not "\x20" <= raw[cursor] <= "\x3f":
            return start
    return start


@dataclass(frozen=True)
class PlainView:

    text: str
    index_map: List[int]
    pending: int
    osc: List[Tuple[int, int, bool, bool]]
    osc_payload_at: Optional[int]
    escapes: Tuple[Tuple[int, int], ...] = ()


def plain_view(raw: str, *, in_osc: bool = False) -> PlainView:
    limit = len(raw)
    text: List[str] = []
    index_map: List[int] = []
    osc: List[Tuple[int, int, bool, bool]] = []
    escapes: List[Tuple[int, int]] = []
    cursor = 0
    if in_osc:
        payload_end, cursor = _string_end(raw, 0)
        if payload_end < 0:
            return PlainView("", [], 0, [], 0)
        osc.append((0, payload_end, True, False))
        escapes.append((0, cursor))

    while cursor < limit:
        found = _SKIP_RE.search(raw, cursor)
        stop = limit if found is None else found.start()
        if stop > cursor:
            text.append(raw[cursor:stop])
            index_map.extend(range(cursor, stop))
        if found is None:
            break
        cursor = stop
        if not is_sequence_start(raw[cursor]):
            cursor += 1
            continue
        kind, body = _introducer(raw, cursor)
        end = _escape_end(raw, cursor)
        if end < 0:
            is_string = bool(kind) and kind in _STRING_INTRODUCERS
            return PlainView(
                "".join(text), index_map, cursor, osc,
                min(body, limit) if is_string else None, tuple(escapes),
            )
        if kind in _STRING_INTRODUCERS:
            payload_end, _ = _string_end(raw, body)
            if kind == "P":
                body = _dcs_data_start(raw, body, payload_end)
            osc.append((body, payload_end, False, kind == "]"))
        escapes.append((cursor, end))
        cursor = end

    return PlainView("".join(text), index_map, limit, osc, None, tuple(escapes))


def is_control(char: str) -> bool:
    return char < " " or char == "\x7f"



def star(chars: List[str], start: int, end: int) -> None:
    for position in range(max(0, start), min(end, len(chars))):
        if not is_control(chars[position]):
            chars[position] = REDACTION_CHAR


def redact_osc(
    chars: List[str],
    span: Tuple[int, int, bool, bool],
    scan: Callable[[str], List[SecretFinding]],
) -> List[SecretFinding]:
    start, end, whole, is_osc = span
    if whole:
        star(chars, start, end)
        return []
    payload = "".join(chars[start:end])
    if is_osc:
        selector, _, rest = payload.partition(";")
        if selector == _OSC_CLIPBOARD:
            _selection, separator, data = rest.partition(";")
            if separator:
                star(chars, start + len(payload) - len(data), end)
            return []
    found = scan(payload)
    for finding in found:
        star(chars, start + finding.offset,
             start + finding.offset + finding.length)
    return found
