
from __future__ import annotations

import re
from typing import Dict, List, NamedTuple, Optional, Tuple

from src.cplugs.reviewboard.pdf_doc import Parsed
from src.cplugs.reviewboard.pdf_lexer import Lexer, Meter
from src.cplugs.reviewboard.pdf_objects import Dict as PdfDict, Name, parse_value
from src.cplugs.reviewboard.pdf_streams import REASON_FILTER, Budget, PdfUnreadable, decode

REASON_HIDDEN = "hidden_object"
REASON_UNRESOLVED = "xref_unresolved"
MAX_SECTIONS = 1024
MAX_ENTRIES = 5_000_000
_XREF_FILTERS = {"FlateDecode", "Fl", "ASCIIHexDecode", "AHx", "ASCII85Decode", "A85"}
_WS = frozenset(b"\x00\t\n\x0b\x0c\r ")
_WS_CLASS = rb"\x00\t\n\x0b\x0c\r "
_GAP = rb"(?:[" + _WS_CLASS + rb"]++|%[^\r\n]*+)*+"
_NUM = rb"(?:[+-]?[0-9]++|[+-])"
_HEADER_AT = re.compile(_NUM + _GAP + _NUM + _GAP + rb"obj(?![^" + _WS_CLASS + rb"()<>\[\]{}/%])")
_GAP_AT = re.compile(_GAP)
_CLASSIC_SUBHEAD = re.compile(rb"\s*(\d+)\s+(\d+)\s*")
_CLASSIC_ROW = re.compile(rb"\s*(\d{10})\s(\d{5})\s([nf])")


class Entry(NamedTuple):

    offset: Optional[int]
    stm: Optional[int]


def _skip_ws(data: bytes, pos: int) -> int:
    end = len(data)
    while pos < end and data[pos] in _WS:
        pos += 1
    return pos


def _skip_gap(data: bytes, pos: int) -> int:
    return _GAP_AT.match(data, pos).end()


def _last_startxref(data: bytes) -> Optional[int]:
    tail = data[-2048:]
    matches = list(re.finditer(rb"startxref\s+(\d+)", tail))
    if not matches:
        return None
    offset = int(matches[-1].group(1))
    return offset if 0 <= offset < len(data) else None


def resolve_xref(data: bytes, meter: Meter, budget: Budget) -> Optional[Dict[int, Entry]]:
    start = _last_startxref(data)
    if start is None:
        return None
    entries: Dict[int, Entry] = {}
    pending: List[int] = [start]
    seen: set = set()
    parsed = 0
    while pending:
        meter.deadline.check()
        offset = pending.pop()
        if offset in seen or not (0 <= offset < len(data)):
            continue
        if len(seen) >= MAX_SECTIONS:
            raise PdfUnreadable(REASON_UNRESOLVED)
        seen.add(offset)
        section = _parse_section(data, offset, meter, budget)
        if section is None:
            if parsed == 0:
                return None
            raise PdfUnreadable(REASON_UNRESOLVED)
        parsed += 1
        for num, entry in section.entries.items():
            entries.setdefault(num, entry)
            if len(entries) > MAX_ENTRIES:
                raise PdfUnreadable("too_much_data")
        pending.extend(off for off in (section.xrefstm, section.prev) if off is not None)
    return entries if entries else None


class _Section(NamedTuple):

    entries: Dict[int, Entry]
    xrefstm: Optional[int]
    prev: Optional[int]


def _parse_section(data: bytes, offset: int, meter: Meter, budget: Budget) -> Optional[_Section]:
    at = _skip_ws(data, offset)
    if data[at:at + 4] == b"xref":
        return _parse_classic(data, at + 4, meter)
    return _parse_xref_stream(data, at, meter, budget)


def _parse_classic(data: bytes, pos: int, meter: Meter) -> Optional[_Section]:
    entries: Dict[int, Entry] = {}
    while True:
        meter.deadline.check()
        pos = _skip_ws(data, pos)
        if data[pos:pos + 7] == b"trailer":
            break
        head = _CLASSIC_SUBHEAD.match(data, pos)
        if head is None:
            return _with_trailer(data, pos, entries, meter) if entries else None
        first, count = int(head.group(1)), int(head.group(2))
        if count > MAX_ENTRIES:
            raise PdfUnreadable("too_much_data")
        pos = head.end()
        for i in range(count):
            row = _CLASSIC_ROW.match(data, pos)
            if row is None:
                return _with_trailer(data, pos, entries, meter) if entries else None
            if row.group(3) == b"n":
                entries[first + i] = Entry(offset=int(row.group(1)), stm=None)
            pos = row.end()
    return _with_trailer(data, pos + 7, entries, meter)


def _with_trailer(data: bytes, pos: int, entries: Dict[int, Entry], meter: Meter) -> _Section:
    dic = _trailer_dict(data, pos, meter)
    return _Section(entries, _int_entry(dic, "XRefStm"), _int_entry(dic, "Prev"))


def _trailer_dict(data: bytes, pos: int, meter: Meter) -> PdfDict:
    start = data.find(b"<<", pos)
    if start < 0 or start - pos > 64:
        return PdfDict()
    try:
        value = parse_value(Lexer(data, meter, pos=start))
    except PdfUnreadable:
        return PdfDict()
    return value if isinstance(value, PdfDict) else PdfDict()


def _int_entry(dic: PdfDict, key: str) -> Optional[int]:
    raw = dic.get(key)
    return raw if isinstance(raw, int) and not isinstance(raw, bool) and raw >= 0 else None


def _parse_xref_stream(data: bytes, pos: int, meter: Meter, budget: Budget) -> Optional[_Section]:
    lx = Lexer(data, meter, pos=pos)
    try:
        a, b, kw = lx.next(), lx.next(), lx.next()
        if not (a and b and kw) or a[0] != "int" or b[0] != "int" or kw != ("kw", b"obj", kw[2]):
            return None
        dic = parse_value(lx)
        stream_kw = lx.next()
    except PdfUnreadable:
        return None
    if not isinstance(dic, PdfDict) or stream_kw is None or stream_kw[1] != b"stream":
        return None
    body = _xref_stream_body(data, lx.pos, dic, budget)
    if body is None:
        return None
    rows = _decode_xref_stream(body, dic, budget)
    entries = _xref_stream_entries(rows, dic)
    if entries is None:
        return None
    return _Section(entries, None, _int_entry(dic, "Prev"))


def _xref_stream_body(data: bytes, after_kw: int, dic: PdfDict, budget: Budget) -> Optional[bytes]:
    length = dic.get("Length")
    if not (isinstance(length, int) and not isinstance(length, bool) and length >= 0):
        return None
    eol = re.match(rb"[ \t]*(?:\r\n|\n|\r)", data[after_kw:])
    if eol is None:
        return None
    start = after_kw + eol.end()
    return data[start:start + length] if start + length <= len(data) else None


def _decode_xref_stream(body: bytes, dic: PdfDict, budget: Budget) -> bytes:
    raw = dic.get("Filter")
    names = [] if raw is None else [raw] if isinstance(raw, Name) else raw
    if not isinstance(names, list) or not all(isinstance(n, Name) and str(n) in _XREF_FILTERS for n in names):
        raise PdfUnreadable(REASON_FILTER)
    data = decode(body, [str(n) for n in names], budget)
    return _unpredict(data, dic)


def _unpredict(data: bytes, dic: PdfDict) -> bytes:
    parms = dic.get("DecodeParms") or dic.get("DP")
    parms = parms[0] if isinstance(parms, list) and parms else parms
    if not isinstance(parms, PdfDict):
        return data
    predictor = _int_entry(parms, "Predictor") or 1
    if predictor <= 1:
        return data
    columns = _int_entry(parms, "Columns") or 1
    colors = _int_entry(parms, "Colors") or 1
    bpc = _int_entry(parms, "BitsPerComponent") or 8
    pixel = max(1, (colors * bpc + 7) // 8)
    row = max(1, (colors * bpc * columns + 7) // 8)
    return _unpredict_tiff(data, row, pixel) if predictor == 2 else _unpredict_png(data, row, pixel)


def _unpredict_png(data: bytes, row: int, pixel: int) -> bytes:
    out, prior, pos = bytearray(), bytes(row), 0
    stride = row + 1
    while pos + stride <= len(data):
        tag, cur = data[pos], bytearray(data[pos + 1:pos + stride])
        for i in range(row):
            left = cur[i - pixel] if i >= pixel else 0
            up = prior[i]
            up_left = prior[i - pixel] if i >= pixel else 0
            if tag == 1:
                cur[i] = (cur[i] + left) & 0xFF
            elif tag == 2:
                cur[i] = (cur[i] + up) & 0xFF
            elif tag == 3:
                cur[i] = (cur[i] + (left + up) // 2) & 0xFF
            elif tag == 4:
                cur[i] = (cur[i] + _paeth(left, up, up_left)) & 0xFF
        out += cur
        prior = bytes(cur)
        pos += stride
    return bytes(out)


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    return a if pa <= pb and pa <= pc else (b if pb <= pc else c)


def _unpredict_tiff(data: bytes, row: int, pixel: int) -> bytes:
    out = bytearray(data)
    for base in range(0, len(out) - row + 1, row):
        for i in range(pixel, row):
            out[base + i] = (out[base + i] + out[base + i - pixel]) & 0xFF
    return bytes(out)


def _xref_stream_entries(rows: bytes, dic: PdfDict) -> Optional[Dict[int, Entry]]:
    widths = dic.get("W")
    if not (isinstance(widths, list) and len(widths) == 3 and all(isinstance(w, int) and not isinstance(w, bool) and w >= 0 for w in widths)):
        return None
    w0, w1, w2 = widths
    record = w0 + w1 + w2
    if record == 0 or len(rows) % record:
        return None
    index = _index_pairs(dic, len(rows) // record)
    if index is None:
        return None
    entries: Dict[int, Entry] = {}
    cursor = 0
    for start, count in index:
        for i in range(count):
            pos = cursor * record
            cursor += 1
            if pos + record > len(rows):
                return entries
            kind = _field(rows, pos, w0, 1)
            f2 = _field(rows, pos + w0, w1, 0)
            if kind == 1:
                entries[start + i] = Entry(offset=f2, stm=None)
            elif kind == 2:
                entries[start + i] = Entry(offset=None, stm=f2)
    return entries


def _index_pairs(dic: PdfDict, record_count: int) -> Optional[List[Tuple[int, int]]]:
    index = dic.get("Index")
    if index is None:
        size = _int_entry(dic, "Size")
        return [(0, size if size is not None else record_count)]
    if not (isinstance(index, list) and len(index) % 2 == 0 and all(isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in index)):
        return None
    return [(index[i], index[i + 1]) for i in range(0, len(index), 2)]


def _field(rows: bytes, pos: int, width: int, default: int) -> int:
    return int.from_bytes(rows[pos:pos + width], "big") if width else default


def verify_against_walk(data: bytes, out: Parsed, meter: Meter, budget: Budget) -> None:
    entries = resolve_xref(data, meter, budget)
    if entries is None:
        return
    for num, entry in entries.items():
        meter.deadline.check()
        if entry.offset is not None:
            target = _skip_gap(data, entry.offset)
            if target in out.header_obj:
                continue
            if _HEADER_AT.match(data, target) is not None:
                raise PdfUnreadable(REASON_HIDDEN)
        elif entry.stm is not None and num not in out.objstm_members:
            raise PdfUnreadable(REASON_HIDDEN)
