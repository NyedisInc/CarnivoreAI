
from __future__ import annotations

import re
from typing import Mapping, Sequence

from src.cplugs.huddle.nudge import planning, settings

_SLOT = re.compile(r"\{(minutes|item|items|is|it)\}")
QUOTE_CHARS = 60
WHY_SET = "you set it working"
WHY_HELD = "you hold its claim"


def fill(template: str, slots: Mapping[str, str]) -> str:
    return _SLOT.sub(lambda m: slots[m.group(1)], template).rstrip() + " "


def quote(cand: planning.Candidate) -> str:
    words = " ".join((cand.row["title"] or cand.row["text"] or "").split())
    return words if len(words) <= QUOTE_CHARS else words[:QUOTE_CHARS - 1].rstrip() + "..."


def _minutes(seconds: float) -> str:
    return str(int(max(seconds, 0) // 60))


def unclaimed_line(cand: planning.Candidate, now: float, texts: Mapping[str, str]) -> str:
    return fill(texts[settings.UNCLAIMED_TEXT], {"minutes": _minutes(now - cand.last_activity), "item": quote(cand), "items": "", "is": "", "it": ""})


def pickup_line(cand: planning.Candidate, now: float, texts: Mapping[str, str]) -> str:
    return fill(texts[settings.PICKUP_TEXT], {"minutes": _minutes(now - cand.last_activity), "item": quote(cand), "items": "", "is": "", "it": ""})


def why_working(cand: planning.Candidate) -> str:
    op = cand.row["claim_op"] if "claim_op" in cand.row.keys() else None
    return WHY_SET if op else WHY_HELD


def _named(cand: planning.Candidate) -> str:
    if cand.status == planning.WORKING:
        return f'"{quote(cand)}" ({cand.status}: {why_working(cand)})'
    return f'"{quote(cand)}" ({cand.status})'


def _more(total: int, shown: int) -> str:
    return f" and {total - shown} more" if total > shown else ""


def claimed_line(cands: Sequence[planning.Candidate], now: float, texts: Mapping[str, str], max_items: int) -> str:
    ordered = sorted(cands, key=lambda c: (c.status != planning.WORKING, c.row["position"], c.id))
    named = ordered[:max_items]
    quiet = _minutes(min(now - c.last_activity for c in named))
    items = ", ".join(_named(c) for c in named) + _more(len(ordered), len(named))
    return fill(texts[settings.CLAIMED_TEXT], {"minutes": quiet, "items": items, "item": "", "is": "", "it": ""})


STALL_LINE = "{who} has been idle for {minutes} min with this task still open, after {tries} nudges."


def stall_line(session_label: str, quiet_s: float, tries: int) -> str:
    return STALL_LINE.format(who=session_label or "its session", minutes=_minutes(quiet_s), tries=tries)
