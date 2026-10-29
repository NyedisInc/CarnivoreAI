"""Does a claude session's own evidence say it stopped on its usage limit?

PURE. No file, no tmux, no clock: the caller hands in records or text.

    You've hit your session limit · resets 4pm (America/New_York)
    You've hit your session limit · resets 10:30pm (America/New_York) · progress saved
    You've hit your weekly limit · resets 1am (America/New_York)

(1,300 or so records, all this shape.) Older builds wrote
``Claude AI usage limit reached|<epoch>``; it is matched too, so a session
running an older binary is not missed. The same sentence is what the pane
shows.

A TRANSCRIPT SAYS "BLOCKED" ONLY WHEN THE LIMIT STOP IS THE LAST TURN. The
tail is walked back to the most recent main-thread ``user`` or ``assistant``
record, skipping bookkeeping records (system, attachment, summary and the
like) and subagent records (``isSidechain``); that record must be the limit
stop, carrying both the sentence and, for current builds, the
``quotaLimits`` object with status ``rejected`` (:func:`usage_limit.is_limit_stop` is the one predicate; a transient
429 has none). A user message after it, or any later model turn, means the session moved on and is not blocked.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping, Optional

from src.core.attention.usage_limit import LimitStop, is_limit_stop, is_limit_text, parse_limit_stop

PANE_TAIL_LINES = 15


def is_limit_record(record: Mapping[str, Any]) -> bool:
    return is_limit_stop(record)


def transcript_blocked(records: Iterable[Mapping[str, Any]]) -> bool:
    last = last_turn(records)
    return last is not None and is_limit_record(last)


def last_turn(records: Iterable[Mapping[str, Any]]) -> Optional[Mapping[str, Any]]:
    last = None
    for record in records:
        if (
            isinstance(record, Mapping)
            and record.get("type") in ("user", "assistant")
            and record.get("isSidechain") is not True
        ):
            last = record
    return last


def last_limit_stop(records: Iterable[Mapping[str, Any]]) -> Optional[LimitStop]:
    return parse_limit_stop(last_turn(records))


def pane_blocked(screen: Optional[str]) -> bool:
    if not screen:
        return False
    lines = [line for line in screen.splitlines() if line.strip()]
    return any(is_limit_text(line) for line in lines[-PANE_TAIL_LINES:])


PANE_STOP_PREFIX = "pane:"

PANE_FOOTER_LINES = 20

_RULE = re.compile(r"^\s*[\u2500\u2501]{8,}\s*$")

_BANNER = re.compile(r"^\s*\u26a0\s+Usage limit reached\s+\u00b7\s+limit resets\s+(?P<at>\S.*?)\s*$")
_CONTINUING = re.compile(r"^\s*Continuing automatically at\s+\S.*?\s+\u00b7\s+esc to cancel\b")

_PAUSED_ROW = re.compile(r"^\s*\u23f8\s+\S.*?\s+paused\s+\u00b7\s+usage limit resets at\s+(?P<at>\S.*?)\s*$")


def pane_stop_label(screen: Optional[str]) -> Optional[str]:
    if not screen:
        return None
    lines = screen.splitlines()
    rules = [i for i, line in enumerate(lines) if _RULE.match(line)]
    if not rules:
        return None
    footer = [line for line in lines[rules[-1] + 1:] if line.strip()][:PANE_FOOTER_LINES]
    banner = next((m.group("at") for m in map(_BANNER.match, footer) if m), None)
    if banner is not None and any(_CONTINUING.match(line) for line in footer):
        return banner
    return next((m.group("at") for m in map(_PAUSED_ROW.match, footer) if m), None)


def is_pane_stop(stop: Optional[Any]) -> bool:
    return stop is not None and isinstance(stop.uuid, str) and stop.uuid.startswith(PANE_STOP_PREFIX)
