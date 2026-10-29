
from __future__ import annotations

import re
from typing import List, Optional, Tuple

from src.core.approvals.extract import REVIEW_QUESTION

_BAR = re.compile(r"^\s*│\s?")
_NOTES = re.compile(r"^\s*Notes:\s?(.*?)\s*$")
_REVIEW_TITLE = "Review your answers"
_UNANSWERED_MARK = "⚠"

NOTES_IDLE = "press n to add notes"
NOTES_EMPTY_ENTRY = "Add notes on this"


def review_answers(text: str) -> Optional[Tuple[List[Tuple[str, str]], bool]]:
    lines = (text or "").splitlines()
    end = next((i for i in range(len(lines) - 1, -1, -1) if lines[i].strip() == REVIEW_QUESTION), None)
    start = next((i for i in range(len(lines) - 1, -1, -1) if lines[i].strip() == _REVIEW_TITLE and (end is None or i < end)), None)
    if end is None or start is None:
        return None
    pairs: List[List[str]] = []
    warned = False
    for raw in lines[start + 1:end]:
        line = _BAR.sub("", raw).strip()
        if not line:
            continue
        if line.startswith(_UNANSWERED_MARK):
            warned = True
        elif line.startswith("●"):
            pairs.append([line[1:].strip(), ""])
        elif line.startswith("→") and pairs:
            pairs[-1][1] = line[1:].strip()
        elif pairs:
            slot = 1 if pairs[-1][1] else 0
            pairs[-1][slot] = f"{pairs[-1][slot]} {line}".strip()
    return [(q, a) for q, a in pairs], warned


def notes_line(text: str) -> Optional[str]:
    for line in reversed((text or "").splitlines()):
        m = _NOTES.match(line)
        if m:
            return m.group(1)
    return None
