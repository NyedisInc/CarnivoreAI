
from __future__ import annotations

import re
from typing import List, Optional, Pattern, Sequence, Tuple, Union

from src.core.attention.evidence import PaneVerdict
from src.core.attention.pane_prompt_box import line_above_prompt_box
from src.core.session_permission_verify import (
    PERMISSION_TAIL_LINES,
    detect_permission_dialog,
)
from src.core.session_startup_gate import detect_startup_prompt

BLOCK_SEPARATOR_BLANK_LINES: int = 2

BLOCK_MAX_LINES: int = PERMISSION_TAIL_LINES

QUESTION_DIALOG_MARKERS: Tuple[Union[str, Pattern[str]], ...] = (
    re.compile(
        r"^\s*Enter to select\s*[·•|,-]?\s*"
        r"(?:Tab/Arrow keys|↑/↓) to navigate"
        r"(?:\s*[·•|,-]\s*[^·•|\n]+?)*?"
        r"\s*[·•|,-]?\s*Esc to cancel\s*$",
        re.M,
    ),
)


RESTING_TAIL_LINES: int = 12

RESTING_PROMPT_MARKER: Pattern[str] = re.compile(
    "^\\s*\\u276f", re.M
)

_SPINNER_GLYPHS: str = (
    "\\u002a\\u00b7\\u2722\\u2733\\u2736\\u273b\\u273d"
    "\\u2800-\\u28ff\\u25d0-\\u25d3"
)

RESTING_BUSY_MARKERS: Tuple[Union[str, Pattern[str]], ...] = (
    re.compile(r"(?i)esc to interrupt", re.M),
    re.compile(
        "^\\s*[" + _SPINNER_GLYPHS + "]\\s+Waiting for "
        "(?:[1-9]\\d* background agents?"
        "(?: and [1-9]\\d* dynamic workflows?)?"
        "|[1-9]\\d* dynamic workflows?) to finish\\s*$",
        re.M,
    ),
    re.compile(
        "^[ \\t]+(?:[^\\n\u276f]*\\s\u00b7\\s+)?"
        "(?:[1-9]\\d* shells?(?:, [1-9]\\d* monitors?)?"
        "|[1-9]\\d* monitors?|[1-9]\\d* background tasks?)"
        "(?:\\s+\u00b7\\s[^\\n]*)?\\s*$",
        re.M,
    ),
    re.compile(r"(?i)[1-9]\d* MCP tasks? still running", re.M),
    re.compile(
        "^\\s*[" + _SPINNER_GLYPHS + "]\\s+\\S[^\\n]*?\\u2026"
        "(?:\\s*\\(\\s*\\d+[smh]|\\s*$)",
        re.M,
    ),
)


def bottom_non_blank_lines(
    lines: Optional[Sequence[str]], limit: int
) -> List[str]:
    if not lines or limit <= 0:
        return []
    kept: List[str] = []
    for line in reversed(list(lines)):
        if not line.strip():
            continue
        kept.append(line)
        if len(kept) >= limit:
            break
    kept.reverse()
    return kept


def detect_resting_prompt(lines: Optional[Sequence[str]]) -> Optional[bool]:
    window = bottom_non_blank_lines(lines, RESTING_TAIL_LINES)
    if not window:
        return None
    text = "\n".join(window)
    if _matches(text, RESTING_BUSY_MARKERS):
        return False
    if not RESTING_PROMPT_MARKER.search(text):
        return False
    above = line_above_prompt_box(window, lines, RESTING_PROMPT_MARKER)
    return not (above is not None and _matches(above, RESTING_BUSY_MARKERS))


def last_text_block(lines: Optional[Sequence[str]]) -> List[str]:
    if not lines:
        return []

    end = len(lines)
    while end > 0 and not lines[end - 1].strip():
        end -= 1
    if end == 0:
        return []

    start = end
    blank_run = 0
    index = end
    while index > 0 and (end - index) < BLOCK_MAX_LINES:
        index -= 1
        if lines[index].strip():
            blank_run = 0
            start = index
        else:
            blank_run += 1
            if blank_run >= BLOCK_SEPARATOR_BLANK_LINES:
                break
    return list(lines[start:end])


def _matches(text: str, markers: Tuple[Union[str, Pattern[str]], ...]) -> bool:
    for marker in markers:
        if isinstance(marker, str):
            if marker in text:
                return True
        elif marker.search(text):
            return True
    return False


def _with_wrapped_lines_joined(block: Sequence[str]) -> str:
    joined = [" ".join(s.strip() for s in block[i:i + span])
              for i in range(len(block)) for span in (2, 3) if i + span <= len(block)]
    return "\n".join([*block, *joined])


def classify_pane_tail(lines: Optional[Sequence[str]]) -> PaneVerdict:
    block = last_text_block(lines)
    if not block:
        return PaneVerdict(
            detail=(
                "the pane capture held no text, so nothing was measured; "
                "capture-pane on a full-screen TUI returns trailing blanks "
                "and that is a failed read, not a clear screen"
            )
        )

    text = "\n".join(block)
    permission = detect_permission_dialog(text)
    question = _matches(_with_wrapped_lines_joined(block), QUESTION_DIALOG_MARKERS)
    trust = detect_startup_prompt(text)

    resting = detect_resting_prompt(lines)
    if resting and (permission is True or question is True or trust is True):
        resting = False

    found = [
        name
        for name, value in (
            ("permission", permission),
            ("question", question),
            ("trust", trust),
        )
        if value is True
    ]
    if found:
        summary = "matched " + ", ".join(found)
    else:
        summary = "matched no dialog family"
    return PaneVerdict(
        permission_dialog=permission,
        question_dialog=question,
        trust_dialog=trust,
        resting_prompt=resting,
        detail=(
            "read the last %d line(s) of the pane capture and %s; the live "
            "region %s"
            % (
                len(block),
                summary,
                "shows claude's resting input prompt"
                if resting is True
                else (
                    "could not be read"
                    if resting is None
                    else "is not a resting prompt"
                ),
            )
        ),
    )
