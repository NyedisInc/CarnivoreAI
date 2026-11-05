
from __future__ import annotations

import re
from typing import FrozenSet, Set

from src.cplugs.reviewboard.pdf_actions import open_time_features
from src.cplugs.reviewboard.pdf_doc import Parsed, parse
from src.cplugs.reviewboard.pdf_lexer import Meter
from src.cplugs.reviewboard.pdf_streams import REASON_TRUNCATED, Budget, PdfUnreadable
from src.cplugs.reviewboard.pdf_xref import verify_against_walk
from src.cplugs.sdk.file_secrets import Deadline

ACTIVE_NAMES = {"JavaScript": "JavaScript", "JS": "JavaScript", "Launch": "Launch", "EmbeddedFile": "EmbeddedFile",
                "EmbeddedFiles": "EmbeddedFile", "RichMedia": "RichMedia", "XFA": "XFA", "SubmitForm": "SubmitForm", "ImportData": "ImportData",
                "OnInstantiate": "3DScript"}
REASON_DISAGREE = "parser_disagreement"
EOF_WINDOW = 2048

_RAW_NAME = re.compile(rb"/([^\x00\t\n\x0c\r ()<>\[\]{}/%]*)")
_ESCAPE = re.compile(rb"#([0-9A-Fa-f]{2})")
_TICK = 4096


def _raw_names(text: bytes, meter: Meter, found: Set[str]) -> None:
    for i, match in enumerate(_RAW_NAME.finditer(text)):
        if i % _TICK == 0:
            meter.deadline.check()
        raw = match.group(1)
        name = (_ESCAPE.sub(lambda m: bytes([int(m.group(1), 16)]), raw) if b"#" in raw else raw).decode("latin-1")
        if name in ACTIVE_NAMES:
            found.add(ACTIVE_NAMES[name])


def _raw_file_view(parsed: Parsed, data: bytes, meter: Meter, found: Set[str]) -> None:
    pos = 0
    for start, end in sorted(parsed.kept):
        _raw_names(data[pos:start], meter, found)
        pos = end
    _raw_names(data[pos:], meter, found)


def features(data: bytes, deadline: Deadline) -> FrozenSet[str]:
    if b"%%EOF" not in data[-EOF_WINDOW:]:
        raise PdfUnreadable(REASON_TRUNCATED)
    meter, raw = Meter.for_input(deadline, len(data)), set()  # type: Meter, Set[str]
    budget = Budget.for_input(deadline, len(data))
    parsed = parse(data, meter, budget, on_decoded=lambda text: _raw_names(text, meter, raw))
    verify_against_walk(data, parsed, meter, budget)
    _raw_file_view(parsed, data, meter, raw)
    seen = {ACTIVE_NAMES[n] for n in parsed.names if n in ACTIVE_NAMES}
    if raw - seen:
        raise PdfUnreadable(REASON_DISAGREE)
    return frozenset(seen | open_time_features(parsed, meter))
