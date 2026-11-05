
from __future__ import annotations

import re
from typing import List, Optional, Pattern

from src.core.approvals.extract import (
    BODY_MAX_BYTES, FAMILY_CLAUDE, KIND_OTHER, ROLE_OPTION, Dialog, Row, fingerprint_for, normalize_body, squash)
from src.core.session_startup_gate import SCREEN_EFFORT_NUDGE
from src.core.timers.redact import redact

KEEP_ROW: Pattern[str] = re.compile(r"^\s*(?:([❯›>])\s*)?Keep\s+(\S+)\s*$")
SWITCH_ROW: Pattern[str] = re.compile(r"^\s*(?:([❯›>])\s*)?Switch\s+(.+?)\s+to\s+(\S+)\s+effort\s*$")
_ANCHOR: Pattern[str] = re.compile(r"change\s+this\s+any\s+time\s+with\s+/effort|the\s+estimated\s+cost\s+of|uses\s+more\s+tokens\s+per\s+task\s+than")
BODY_LINES: int = 12


def decode(lines: List[str]) -> Optional[Dialog]:
    end = len(lines)
    while end and not lines[end - 1].strip():
        end -= 1
    if end < 3:
        return None
    first, second = lines[end - 2], lines[end - 1]
    ms = [KEEP_ROW.match(first) or SWITCH_ROW.match(first), KEEP_ROW.match(second) or SWITCH_ROW.match(second)]
    if ms[0] is None or ms[1] is None:
        return None
    keeps = [KEEP_ROW.match(ln) for ln in (first, second)]
    if sum(1 for k in keeps if k) != 1 or sum(1 for m in ms if m.group(1)) != 1:
        return None
    keep = next(k for k in keeps if k)
    switch = next(m for m, k in zip(ms, keeps) if not k)
    if switch.re is not SWITCH_ROW or keep.group(2) == switch.group(3):
        return None
    glyphs = [m.group(1) for m in ms]
    above = lines[max(0, end - 2 - BODY_LINES):end - 2]
    if _ANCHOR.search(" ".join(above)) is None:
        return None
    rows = [Row(re.sub(r"^[❯›>]\s*", "", ln.strip()), ROLE_OPTION, None, squash(re.sub(r"^[❯›>]\s*", "", ln.strip()))) for ln in (first, second)]
    body_lines = [ln.rstrip() for ln in above if ln.strip()]
    question = body_lines[0].strip() if body_lines else "effort level"
    body = redact("\n".join(body_lines + [ln.rstrip() for ln in (first, second)])).encode("utf-8")[:BODY_MAX_BYTES].decode("utf-8", "ignore")
    return Dialog(
        family=FAMILY_CLAUDE, kind=KIND_OTHER, question=redact(question), body=body, rows=tuple(rows), cursor=0 if glyphs[0] else 1,
        multi_select=False,
        fingerprint=fingerprint_for(FAMILY_CLAUDE, KIND_OTHER, squash(question), [r.key for r in rows], normalize_body(body_lines)),
        startup_kind=SCREEN_EFFORT_NUDGE)
