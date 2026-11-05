
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Set, Tuple

from src.cplugs.reviewboard import office_text as limits
from src.cplugs.reviewboard.pdf_lexer import MAX_NUMBER_CHARS, REASON_SYNTAX, Lexer, Meter, find_headers
from src.cplugs.reviewboard.pdf_objects import Dict as PdfDict, Name, Ref, Value, parse_value
from src.cplugs.reviewboard.pdf_streams import (REASON_AMBIGUOUS, REASON_FILTER, REASON_HIDDEN, REASON_TRUNCATED, Budget, PdfUnreadable, decode)

_END = re.compile(rb"[\r\n \t\x00]{0,4}endstream")
_EOL = re.compile(rb"[ \t]*(?:\r\n|\n|\r)")
_SLACK = b"\r\n \t\x00"
_TICK = 4096
_CRITICAL = {"Filter", "DecodeParms", "DP", "N", "First", "Length", "Type"}


@dataclass
class Parsed:

    names: Set[str] = field(default_factory=set)
    top_names: Set[str] = field(default_factory=set)
    objects: Dict[int, List[Value]] = field(default_factory=dict)
    loose: List[Value] = field(default_factory=list)
    headers: Set[int] = field(default_factory=set)
    header_obj: Dict[int, int] = field(default_factory=dict)
    objstm_members: Set[int] = field(default_factory=set)
    kept: List[Tuple[int, int]] = field(default_factory=list)


@dataclass
class _Stream:

    dic: PdfDict
    start: int
    length: int
    resume: int = 0
    kw: Optional[int] = None


def _filters(dic: PdfDict) -> List[str]:
    if dic.dups & _CRITICAL:
        raise PdfUnreadable(REASON_AMBIGUOUS)
    raw = dic.get("Filter")
    names = [] if raw is None else [raw] if isinstance(raw, Name) else raw
    if not isinstance(names, list) or not all(isinstance(n, Name) for n in names):
        raise PdfUnreadable(REASON_FILTER)
    for key in ("DecodeParms", "DP"):
        parms = dic.get(key)
        for item in parms if isinstance(parms, list) else [parms]:
            if item is None:
                continue
            predictor = item.get("Predictor") if isinstance(item, PdfDict) else Ref
            if predictor is not None and (isinstance(predictor, bool) or not isinstance(predictor, int) or predictor > 1 or "Predictor" in item.dups):
                raise PdfUnreadable(REASON_FILTER)
    return [str(n) for n in names]


def _is_objstm(dic: PdfDict) -> bool:
    return ("N" in dic and "First" in dic) or dic.get("Type") == "ObjStm"


def _stream_start(data: bytes, after_kw: int) -> int:
    eol = _EOL.match(data, after_kw)
    if eol is None:
        raise PdfUnreadable(REASON_SYNTAX)
    return eol.end()


def _first_pass(data: bytes, meter: Meter, out: Parsed) -> List[_Stream]:
    lx, streams = Lexer(data, meter), []
    while (tok := lx.next()) is not None:
        if tok[0] == "int":
            mark = lx.pos
            second, third = lx.next(), lx.next()
            if second and third and second[0] == "int" and third == ("kw", b"obj", third[2]):
                out.headers.add(tok[2])
                out.header_obj[tok[2]] = int(tok[1])  # type: ignore[arg-type]
                value = parse_value(lx)
                out.objects.setdefault(int(tok[1]), []).append(value)  # type: ignore[arg-type]
                after = lx.next()
                if after is not None and after[1] == b"stream" and after[0] == "kw" and isinstance(value, PdfDict):
                    start = _stream_start(data, lx.pos)
                    streams.append(_cut(data, value, start, out.objects))
                    lx.pos = streams[-1].resume
                elif after is not None and after[1] != b"endobj":
                    lx.pos = after[2]
            else:
                lx.pos = mark
        elif tok[0] in ("<<", "["):
            out.loose.append(parse_value(lx, tok))
    out.names |= lx.names
    out.top_names |= lx.names
    return streams


def _length_of(dic: PdfDict, objects: Dict[int, List[Value]]) -> Optional[int]:
    raw = dic.get("Length")
    if isinstance(raw, Ref):
        if raw.num not in objects:
            return None
        found = [v for v in objects[raw.num] if isinstance(v, int) and not isinstance(v, bool)]
        raw = found[0] if len(found) == 1 and len(objects[raw.num]) == 1 else None
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
        raise PdfUnreadable(REASON_AMBIGUOUS)
    return raw


def _cut(data: bytes, dic: PdfDict, start: int, objects: Dict[int, List[Value]]) -> _Stream:
    length = _length_of(dic, objects)
    if length is None:
        kw = data.find(b"endstream", start)
        if kw < 0:
            raise PdfUnreadable(REASON_TRUNCATED)
        return _Stream(dic, start, kw - start, kw + len(b"endstream"), kw)
    end = _END.match(data, start + length)
    if end is None:
        raise PdfUnreadable(REASON_AMBIGUOUS if b"endstream" in data[start:] else REASON_TRUNCATED)
    return _Stream(dic, start, length, end.end())


def _settle(data: bytes, stream: _Stream, objects: Dict[int, List[Value]]) -> int:
    length = _length_of(stream.dic, objects)
    if length is None:
        raise PdfUnreadable(REASON_AMBIGUOUS)
    if stream.kw is None:
        return stream.length
    if stream.start + length > stream.kw or data[stream.start + length:stream.kw].strip(_SLACK):
        raise PdfUnreadable(REASON_AMBIGUOUS)
    return length


def _read_objstm(content: bytes, dic: PdfDict, meter: Meter, out: Parsed) -> None:
    n, first = dic.get("N"), dic.get("First")
    if not all(isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in (n, first)):
        raise PdfUnreadable(REASON_FILTER)
    head = Lexer(content, meter)
    pairs: List[Tuple[int, int]] = []
    for _ in range(int(n)):  # type: ignore[arg-type]
        num, off = head.next(), head.next()
        if not (num and off and num[0] == "int" and off[0] == "int"):
            raise PdfUnreadable(REASON_SYNTAX)
        pairs.append((int(num[1]), int(off[1])))  # type: ignore[arg-type]
    for num, off in pairs:
        sub = Lexer(content, meter, pos=int(first) + off)  # type: ignore[arg-type]
        out.objects.setdefault(num, []).append(parse_value(sub))
        out.objstm_members.add(num)
        out.names |= sub.names
    out.names |= head.names


def _refuse_hidden_objects(data: bytes, out: Parsed, meter: Meter) -> None:
    for start, len_a, len_b in find_headers(data, meter.deadline):
        if max(len_a, len_b) > MAX_NUMBER_CHARS:
            raise PdfUnreadable(REASON_SYNTAX)
        if start not in out.headers:
            raise PdfUnreadable(REASON_HIDDEN)


def parse(data: bytes, meter: Meter, budget: Budget, on_decoded: Callable[[bytes], None] = lambda text: None) -> Parsed:
    out = Parsed()
    streams = _first_pass(data, meter, out)
    if "Encrypt" in out.top_names:
        raise PdfUnreadable(limits.REASON_ENCRYPTED)
    _refuse_hidden_objects(data, out, meter)
    for late in (False, True):
        for stream in streams:
            if (stream.kw is not None) is not late:
                continue
            meter.deadline.check()
            length = _settle(data, stream, out.objects)
            out.kept.append((stream.start, stream.start + length))
            if _is_objstm(stream.dic):
                content = decode(data[stream.start:stream.start + length], _filters(stream.dic), budget)
                on_decoded(content)
                _read_objstm(content, stream.dic, meter, out)
    return out
