
from __future__ import annotations

import bisect
import re
from dataclasses import dataclass
from typing import FrozenSet, List, Optional, Sequence, Tuple

from src.core.message_model_secret_redaction import VENDOR_MARKER_RE

_CRED = r"A-Za-z0-9+/=_.:\-"

BRIDGE_FILL_CHARS: int = 12

_PAD = "[ \t\u00a0|\u2500-\u259f\"'\\\\]"
_LEAD = "[ \t\u00a0|>*\u2500-\u259f\"'\\\\]"
_BREAK = r"(?:\r*\n|\r+)"
_GUTTER = (
    r"(?:[+\-](?=[" + _CRED + r"])|[0-9+/=_.:\-]{1,8}" + _LEAD
    + r"{1,%d})" % BRIDGE_FILL_CHARS
)

_BRIDGE_RE = re.compile(
    r"(?<=[" + _CRED + r"*])" + _PAD + r"{0,%d}" % BRIDGE_FILL_CHARS
    + _BREAK + _LEAD + r"{0,%d}" % BRIDGE_FILL_CHARS
    + r"(?P<gutter>" + _GUTTER + r")?(?=[" + _CRED + r"])"
)

_PENDING_RE = re.compile(
    r"(?<=[" + _CRED + r"*])" + _PAD + r"{0,%d}" % BRIDGE_FILL_CHARS
    + r"(?:" + _BREAK + r"[^A-Za-z\r\n]{0,%d})?\Z" % (2 * BRIDGE_FILL_CHARS)
)

MARKER_LOOKBACK_CHARS: int = 96


@dataclass(frozen=True)
class Joined:

    text: str
    positions: Sequence[int]
    removed: FrozenSet[int]

    def span(self, offset: int, length: int) -> Tuple[int, int]:
        return self.positions[offset], self.positions[offset + length - 1] + 1

    def index_of(self, source: int) -> int:
        return bisect.bisect_left(self.positions, source)

    def source_end(self, end: int) -> int:
        return self.positions[end - 1] + 1


def unjoined(text: str) -> Joined:
    return Joined(text, range(len(text)), frozenset())


def bridge_gaps(
    text: str,
) -> Tuple[List[Tuple[int, int]], List[Tuple[int, int]]]:
    loose: List[Tuple[int, int]] = []
    tight: List[Tuple[int, int]] = []
    for match in _BRIDGE_RE.finditer(text):
        loose.append((match.start(), match.end()))
        gutter = match.start("gutter")
        tight.append((match.start(), match.end() if gutter < 0 else gutter))
    return loose, tight


def join(text: str, gaps: List[Tuple[int, int]]) -> Joined:
    if not gaps:
        return unjoined(text)
    pieces: List[Tuple[int, int]] = []
    removed: set = set()
    cursor = 0
    for start, end in gaps:
        pieces.append((cursor, start))
        removed.update(range(start, end))
        cursor = end
    pieces.append((cursor, len(text)))
    return Joined(
        "".join(text[start:end] for start, end in pieces),
        [i for start, end in pieces for i in range(start, end)],
        frozenset(removed),
    )


def pending_bridge(text: str, stop: int) -> Optional[int]:
    match = _PENDING_RE.search(text, max(0, stop - 3 * BRIDGE_FILL_CHARS - 4), stop)
    if match is None or match.start() == stop:
        return None
    return match.start()


def carries_marker(
    text: str, start: int, end: int, bridged: FrozenSet[int] = frozenset(),
) -> bool:
    lo = max(0, start - MARKER_LOOKBACK_CHARS)
    read = "".join(text[q] for q in range(lo, end) if q not in bridged)
    return VENDOR_MARKER_RE.search(read) is not None
