"""What the rendered pane shows, read off the LAST BLOCK of text only.

IT IS A REFUSAL, NEVER A CLAIM. A True here lets the resolver take a busy
verdict away and answer ``unknown``; it can never make one, and it can
never say a turn finished. So the cost of a wrong True is a session that
stops being described, and the cost of a wrong False is today's behaviour
unchanged. Every rule below is written to fail toward False.

WHERE THE MARKERS COME FROM, and there are two sources, both named
because a regex without a provenance is a regex nobody can safely change:

WHY THE WINDOW IS THE BOTTOM TWELVE NON-BLANK LINES AND NOT THE BLOCK.
The block reduction below stops at two consecutive blank lines, and real
claude screens use single blanks throughout, so the block is usually the
whole capture - which would let a ``Waiting for 1 background agent`` line
thirty lines up in stale scrollback hold a genuinely resting session grey
for as long as it stayed on screen. ``cloude_REPORT-Agent`` was in exactly
that state: that line 33 lines up, and ``done 11:16 PM`` under it.

WHY THE BLOCK IS SPLIT ON TWO BLANK LINES AND NOT ONE. claude's own
dialogs contain single blank lines: the captured permission prompt has
one between the command echo and the rule explanation. Splitting on a
single blank would cut a real dialog in half and drop the
``Do you want to ...?`` question line above the split, which is one of
the three markers. Two consecutive blanks is what actually separates the
live region from what is left over above it.

AN ALL-BLANK CAPTURE IS A FAILED READ, NOT A CLEAR SCREEN. ``capture-pane``
against a full-screen TUI is documented to return only trailing blanks,
and claude runs full-screen. So a capture with no text in it answers
``None`` for every family: we did not manage to look. Answering False
there would say "no dialog is open" about a screen we never saw, and a
permission prompt reported as no-prompt is the failure this project has
already paid for twice.

THE MARKERS ARE IMPORTED, NOT COPIED. The permission set was read off two
real dialogs and carries its own negative controls in
``tests/test_session_permission_verify.py``; the folder-trust set was
measured across three launches. Re-spelling either here would give this
project two copies of a regex that has to stay identical, which is how
the status LED ended up contracted to byte-identical output in two trees.
Only the ``AskUserQuestion`` footer is new, and it is new because nothing
in the codebase matched it before.
"""

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
    # bypass permissions on
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
    """Which dialog families are on screen in the last block of this pane?

    Description: PURE, and it NEVER RAISES. Reduces the capture to its
      trailing block and runs the three marker families over that block
      alone. Each family answers True, False or None, and the three are
      independent: a capture can show a permission prompt and no trust
      dialog, and that is two measurements, not one.
    """
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
