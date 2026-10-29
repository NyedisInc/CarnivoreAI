
from __future__ import annotations

import re
from typing import List, NamedTuple, Optional

from src.cplugs.sdk.file_secrets import Deadline

MIN_ATTRIBUTE_CHARS = 12

_LONG_ELEMENT = re.compile(r"</?([\w.\-:]{%d,})" % MIN_ATTRIBUTE_CHARS)
_LONG_ATTRIBUTE_NAME = re.compile(r"\s([\w.\-:]{%d,})\s*=" % MIN_ATTRIBUTE_CHARS)
_NAME = re.compile(r"(/?)(?:[\w.\-]+:)?([\w.\-]+)")
_ATTRIBUTE = re.compile(r"""=\s*(?:"([^"]*)"|'([^']*)')""")
_ATTRIBUTE_VALUE = re.compile(r"""=\s*(?:"([^"<>]{%d,})"|'([^'<>]{%d,})')""" % (MIN_ATTRIBUTE_CHARS, MIN_ATTRIBUTE_CHARS))
_HARD_TAG = re.compile(r"</(?:[\w.\-]+:)?(?:p|tr|tc|row|c|si|comment)\s*>|<(?:[\w.\-]+:)?(?:br|tab|cr|ptab)(?![\w.\-])[^<>]*>")
_ANY_TAGS = re.compile(r"(?:<[^<>]*>)+")
_ANY_TAG = re.compile(r"<[^<>]*>")
_SPECIAL = re.compile(r"<!|<\?")
_SOFT_RUN = re.compile(r"(?<=[^\s>])(?:<(?!/?(?:[\w.\-]+:)?(?:p|tr|tc|row|c|si|comment|br|tab|cr|ptab)(?![\w.\-]))[^<>]*>)+(?=[^\s<])")
CHUNK_CHARS = 4 * 1024 * 1024
CHECK_EVERY = 8192
_ENTITY = re.compile(r"&(?:#x([0-9a-fA-F]{1,6})|#([0-9]{1,7})|(amp|lt|gt|quot|apos));")
_SECTION_CODE = re.compile(r"&[LCR](?=\S)")
_NAMED = {"amp": "&", "lt": "<", "gt": ">", "quot": '"', "apos": "'"}
_BLOCK_END = frozenset({"p", "tr", "tc", "row", "c", "si", "comment"})
_BREAKS = frozenset({"br", "tab", "cr", "ptab"})


class SizeExceeded(Exception):
    pass


class Readings(NamedTuple):

    joined: str
    separated: str


class _Sink:

    def __init__(self, limit: int) -> None:
        self.joined: List[str] = []
        self.separated: List[str] = []
        self.size = 0
        self.limit = limit
        self._joined_nl = True
        self._separated_nl = True

    def _grow(self, n: int) -> None:
        self.size += n
        if self.size > self.limit:
            raise SizeExceeded()

    def text(self, s: str) -> None:
        if s:
            self._grow(len(s))
            self.joined.append(s)
            self.separated.append(s)
            self._joined_nl = self._separated_nl = False

    def line(self, s: str) -> None:
        if s:
            self._grow(len(s) + 2)
            self.joined.append("\n" + s + "\n")
            self.separated.append("\n" + s + "\n")
            self._joined_nl = self._separated_nl = True

    def boundary(self, hard: bool) -> None:
        if not self._separated_nl:
            self._grow(1)
            self.separated.append("\n")
            self._separated_nl = True
        if hard and not self._joined_nl:
            self.joined.append("\n")
            self._joined_nl = True


def decode_entities(text: str) -> str:
    def one(m: "re.Match[str]") -> str:
        if m.group(3):
            return _NAMED[m.group(3)]
        code = int(m.group(1), 16) if m.group(1) else int(m.group(2))
        return chr(code) if 0 < code <= 0x10FFFF else m.group(0)
    return _ENTITY.sub(one, text) if "&" in text else text


def _attributes(sink: _Sink, tag: str) -> None:
    if '"' not in tag and "'" not in tag:
        return
    for m in _ATTRIBUTE.finditer(tag):
        value = m.group(1) if m.group(1) is not None else m.group(2)
        if len(value) >= MIN_ATTRIBUTE_CHARS:
            sink.line(value)


def _tag(sink: _Sink, tag: str) -> None:
    m = _NAME.match(tag)
    if m is None:
        sink.boundary(False)
        return
    closing, name = m.group(1) == "/", m.group(2)
    if not closing:
        _attributes(sink, tag)
    for long_name in _LONG_ELEMENT.findall(tag) + _LONG_ATTRIBUTE_NAME.findall(tag):
        sink.line(long_name)
    sink.boundary(name in _BREAKS or (closing and name in _BLOCK_END))


def extract(xml: str, *, limit: int, deadline: Optional[Deadline] = None) -> Readings:
    if _SPECIAL.search(xml, xml.find("?>") + 2 if xml.startswith("<?xml") else 0) is None:
        return _extract_plain(xml, limit, deadline)
    sink, find, n, pos, steps = _Sink(limit), xml.find, len(xml), 0, 0
    while pos < n:
        steps += 1
        if deadline is not None and steps % CHECK_EVERY == 0:
            deadline.check()
        lt = find("<", pos)
        if lt == -1:
            sink.text(xml[pos:])
            break
        sink.text(xml[pos:lt])
        pos = _construct(sink, xml, lt)
    separated = _SECTION_CODE.sub(lambda m: m.group() + "\n", decode_entities("".join(sink.separated)))
    return Readings(decode_entities("".join(sink.joined)), separated)


def _sub_chunked(pattern: "re.Pattern[str]", repl: str, text: str, deadline: Optional[Deadline]) -> str:
    out: List[str] = []
    pos, n = 0, len(text)
    while pos < n:
        if deadline is not None:
            deadline.check()
        end = min(n, pos + CHUNK_CHARS)
        if end < n:
            gt = text.rfind(">", pos, end)
            end = gt + 1 if gt != -1 else end
        out.append(pattern.sub(repl, text[pos:end]))
        pos = end
    return "".join(out)


def _extract_plain(xml: str, limit: int, deadline: Optional[Deadline]) -> Readings:
    lines = ["\n".join(m for pair in _ATTRIBUTE_VALUE.findall(xml) for m in pair if m),
             "\n".join(_LONG_ELEMENT.findall(xml) + _LONG_ATTRIBUTE_NAME.findall(xml))]
    extra = "\n" + "\n".join(part for part in lines if part) + "\n"
    if deadline is not None:
        deadline.check()
    joined = decode_entities(_sub_chunked(_ANY_TAG, "", _sub_chunked(_HARD_TAG, "\n", xml, deadline), deadline) + extra)
    if len(joined) > limit:
        raise SizeExceeded()
    if _SOFT_RUN.search(xml) is None and _SECTION_CODE.search(joined) is None:
        return Readings(joined, "")
    if deadline is not None:
        deadline.check()
    separated = _SECTION_CODE.sub(lambda m: m.group() + "\n", decode_entities(_sub_chunked(_ANY_TAGS, "\n", xml, deadline) + extra))
    if len(separated) > limit:
        raise SizeExceeded()
    return Readings(joined, separated)


def _construct(sink: _Sink, xml: str, lt: int) -> int:
    n = len(xml)
    if xml.startswith("<!--", lt):
        end = xml.find("-->", lt + 4)
        sink.boundary(False)
        sink.line(xml[lt + 4:] if end == -1 else xml[lt + 4:end])
        return n if end == -1 else end + 3
    if xml.startswith("<![CDATA[", lt):
        end = xml.find("]]>", lt + 9)
        sink.text(xml[lt + 9:] if end == -1 else xml[lt + 9:end])
        return n if end == -1 else end + 3
    if xml.startswith("<?", lt):
        end = xml.find("?>", lt + 2)
        sink.line(xml[lt + 2:] if end == -1 else xml[lt + 2:end])
        return n if end == -1 else end + 2
    nxt = xml.find("<", lt + 1)
    stop = n if nxt == -1 else nxt
    end = xml.find(">", lt, stop)
    if end == -1:
        return lt + 1
    _tag(sink, xml[lt + 1:end])
    return end + 1
