
from __future__ import annotations

import base64
import binascii
import re
import zlib
from dataclasses import dataclass, field
from typing import Sequence

from src.cplugs.reviewboard import office_text as limits
from src.cplugs.sdk.file_secrets import Deadline

REASON_FILTER = "unsupported_filter"
REASON_CORRUPT = "corrupt_data"
REASON_TRUNCATED = "truncated"
REASON_AMBIGUOUS = "ambiguous_stream"
REASON_HIDDEN = "hidden_object"
REASON_DUP_KEY = "ambiguous_object"
MAX_STREAM_BYTES = 64 * 1024 * 1024
MIN_TOTAL_BYTES = 32 * 1024 * 1024
TOTAL_PER_INPUT_BYTE = 8
MAX_CHAIN = 4
_CHUNK = 1024 * 1024

_FLATE = {"FlateDecode", "Fl"}
_HEX = {"ASCIIHexDecode", "AHx"}
_A85 = {"ASCII85Decode", "A85"}


class PdfUnreadable(Exception):

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass
class Budget:

    deadline: Deadline
    raw_left: int = field(default_factory=lambda: MIN_TOTAL_BYTES)

    @classmethod
    def for_input(cls, deadline: Deadline, size: int) -> "Budget":
        return cls(deadline, max(MIN_TOTAL_BYTES, TOTAL_PER_INPUT_BYTE * size))


def _inflate(data: bytes, budget: Budget) -> bytes:
    cap = min(MAX_STREAM_BYTES, budget.raw_left)
    inflater, out, total, pending = zlib.decompressobj(), [], 0, data
    try:
        while pending and not inflater.eof:
            budget.deadline.check()
            piece = inflater.decompress(pending, _CHUNK)
            pending = inflater.unconsumed_tail
            total += len(piece)
            if total > cap:
                raise PdfUnreadable(limits.REASON_TOO_BIG)
            out.append(piece)
    except zlib.error as exc:
        raise PdfUnreadable(REASON_CORRUPT) from exc
    budget.raw_left -= total
    return b"".join(out)


def _ascii_hex(data: bytes) -> bytes:
    digits = re.sub(rb"\s+", b"", data.split(b">", 1)[0])
    try:
        return binascii.unhexlify(digits + (b"0" if len(digits) % 2 else b""))
    except binascii.Error as exc:
        raise PdfUnreadable(REASON_CORRUPT) from exc


def _ascii85(data: bytes) -> bytes:
    body = data.strip().removeprefix(b"<~").split(b"~", 1)[0]
    try:
        return base64.a85decode(body)
    except ValueError as exc:
        raise PdfUnreadable(REASON_CORRUPT) from exc


def decode(body: bytes, filters: Sequence[str], budget: Budget) -> bytes:
    if len(filters) > MAX_CHAIN:
        raise PdfUnreadable(REASON_FILTER)
    data = body
    for name in filters:
        budget.deadline.check()
        if name in _FLATE:
            data = _inflate(data, budget)
        elif name in _HEX:
            data = _ascii_hex(data)
        elif name in _A85:
            data = _ascii85(data)
        else:
            raise PdfUnreadable(REASON_FILTER)
    return data
