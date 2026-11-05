
from __future__ import annotations

import re
from typing import List, Optional, Pattern

from src.core.approvals.extract import (
    BODY_MAX_BYTES, FAMILY_CLAUDE, KIND_OTHER, ROLE_OPTION, ROLE_SUBMIT, Dialog, Row, fingerprint_for, normalize_body, squash)
from src.core.session_startup_gate import SCREEN_MCP_SERVER
from src.core.timers.redact import redact

SUBMIT_LABEL: str = "Enable selected"
_TITLE: Pattern[str] = re.compile(r"^\s*(\d+) new MCP servers found in this project\s*$")
_ROW: Pattern[str] = re.compile(r"^\s*(?:([❯›>])\s*)?\[(✔|✓| )\]\s+(\S+)\s*$")
_BUTTON: Pattern[str] = re.compile(r"^\s*(?:([❯›>])\s*)?" + re.escape(SUBMIT_LABEL) + r"\s*$")
_HINT: Pattern[str] = re.compile(r"^\s*Space to select\b.*Esc to reject all\s*$")


def decode(lines: List[str]) -> Optional[Dialog]:
    title_at = next((i for i, ln in enumerate(lines) if _TITLE.match(ln)), None)
    if title_at is None:
        return None
    rows: List[Row] = []
    cursor: Optional[int] = None
    end = None
    for at in range(title_at + 1, len(lines)):
        line = lines[at]
        found, button = _ROW.match(line), _BUTTON.match(line)
        if found is None and button is None:
            if rows:
                if not line.strip():
                    continue
                if _HINT.match(line) and any(r.role == ROLE_SUBMIT for r in rows):
                    end = at
                    break
                return None
            continue
        glyph = (found or button).group(1)
        if glyph:
            if cursor is not None:
                return None
            cursor = len(rows)
        if found is not None:
            if any(r.role == ROLE_SUBMIT for r in rows):
                return None
            rows.append(Row(found.group(3), ROLE_OPTION, found.group(2) != " ", squash(found.group(3))))
        else:
            rows.append(Row(SUBMIT_LABEL, ROLE_SUBMIT, None, squash(SUBMIT_LABEL)))
    servers = [r for r in rows if r.role == ROLE_OPTION]
    if end is None or cursor is None or len(servers) < 2 or rows[-1].role != ROLE_SUBMIT or len({r.key for r in servers}) != len(servers):
        return None
    if int(_TITLE.match(lines[title_at]).group(1)) != len(servers):
        return None
    question = lines[title_at].strip()
    body = redact("\n".join(ln.rstrip() for ln in lines[title_at:end + 1] if ln.strip())).encode("utf-8")[:BODY_MAX_BYTES].decode("utf-8", "ignore")
    return Dialog(
        family=FAMILY_CLAUDE, kind=KIND_OTHER, question=redact(question), body=body, rows=tuple(rows), cursor=cursor, multi_select=True,
        fingerprint=fingerprint_for(FAMILY_CLAUDE, KIND_OTHER, squash(question), [r.key for r in rows], normalize_body([question])),
        startup_kind=SCREEN_MCP_SERVER)
