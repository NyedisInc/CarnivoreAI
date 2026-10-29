
from __future__ import annotations

import re
from typing import List, Optional, Pattern

from src.core.approvals.extract import (
    BODY_MAX_BYTES, FAMILY_CLAUDE, KIND_OTHER, KIND_TRUST, ROLE_OPTION, Dialog, Row, fingerprint_for,
    normalize_body, squash, startup_footer_index,
)
from src.core.session_startup_gate import SCREEN_TRUST, named_startup_marker_spans
from src.core.timers.redact import redact

MIN_ROWS: int = 2
MAX_ROWS: int = 9
MAX_LABEL_CHARS: int = 120
SUBSTANCE_LINES_ABOVE: int = 15

_ROW: Pattern[str] = re.compile(r"^(\s*)([❯›>]\s*)?(?:(\d+)\.\s+)?(\S.*?)\s*$")
_RULE: Pattern[str] = re.compile(r"^\s*[─━╌-]{10,}\s*$")
_BORDER: Pattern[str] = re.compile("[─-▟]")


def _rows_block(lines: List[str], foot: int) -> Optional[tuple]:
    end = foot
    while end > 0 and not lines[end - 1].strip():
        end -= 1
    start = end
    while start > 0 and lines[start - 1].strip():
        start -= 1
    block = lines[start:end]
    if not MIN_ROWS <= len(block) <= MAX_ROWS:
        return None
    rows: List[Row] = []
    cursor: Optional[int] = None
    columns = set()
    numbers: List[Optional[str]] = []
    for at, line in enumerate(block):
        found = _ROW.match(line)
        if found is None or _RULE.match(line) or _BORDER.search(line):
            return None
        label = found.group(4)
        if len(label) > MAX_LABEL_CHARS:
            return None
        if found.group(2):
            if cursor is not None:
                return None
            cursor = at
        columns.add(found.start(4))
        numbers.append(found.group(3))
        rows.append(Row(label, ROLE_OPTION, None, squash(label)))
    if cursor is None or len(columns) != 1:
        return None
    if any(n is not None for n in numbers) and numbers != [str(i + 1) for i in range(len(numbers))]:
        return None
    return start, rows, cursor


def _paragraph(lines: List[str], at: int, below: int) -> tuple:
    top = at
    while top > 0 and lines[top - 1].strip() and not _RULE.match(lines[top - 1]):
        top -= 1
    bottom = at
    while bottom + 1 < below and lines[bottom + 1].strip():
        bottom += 1
    return top, bottom


def decode_startup_choice(lines: List[str]) -> Optional[Dialog]:
    foot = startup_footer_index(lines)
    if foot is None:
        return None
    block = _rows_block(lines, foot)
    if block is None:
        return None
    start, rows, cursor = block
    above = "\n".join(lines[:start])
    spans = named_startup_marker_spans(above)
    if not spans:
        return None
    screen_kind, offset, _ = spans[0]
    q_line = above.count("\n", 0, offset)
    top, bottom = _paragraph(lines, q_line, start)
    question = " ".join(ln.strip() for ln in lines[top:bottom + 1])
    first = max(0, top - SUBSTANCE_LINES_ABOVE)
    substance = normalize_body([ln for ln in lines[first:start] if not _RULE.match(ln)])
    body_lines = [ln.rstrip() for ln in lines[first:foot] if ln.strip() and not _RULE.match(ln)]
    body = redact("\n".join(body_lines)).encode("utf-8")[:BODY_MAX_BYTES].decode("utf-8", "ignore")
    kind = KIND_TRUST if screen_kind == SCREEN_TRUST else KIND_OTHER
    return Dialog(
        family=FAMILY_CLAUDE, kind=kind, question=redact(question), body=body, rows=tuple(rows), cursor=cursor,
        multi_select=False,
        fingerprint=fingerprint_for(FAMILY_CLAUDE, kind, squash(question), [r.key for r in rows], substance),
        startup_kind=screen_kind,
    )


def startup_kind_of(lines: List[str]) -> Optional[str]:
    spans = named_startup_marker_spans("\n".join(lines))
    return spans[0][0] if spans else None


def answer_needs_owner(dialog: Optional[Dialog]) -> bool:
    return dialog is not None and getattr(dialog, "startup_kind", None) is not None
