
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Mapping, Optional, Sequence

from src.cplugs.huddle.nudge import planning

IDLE_STATES = planning.IDLE_STATES


def last_activity_epoch(stamp: Optional[str]) -> Optional[float]:
    if not stamp:
        return None
    try:
        parsed = datetime.fromisoformat(stamp)
    except ValueError:
        return None
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).timestamp()


def holds_claim(key: str, cands: Sequence[planning.Candidate]) -> bool:
    return any(c.status == planning.WORKING and c.row["claimant"] == key for c in cands)


def idle_rows(rows: Sequence[Mapping[str, Any]], cands: Sequence[planning.Candidate], prefs: Mapping[str, bool], project_on: bool,
              ready: Optional[str] = None) -> list:
    out = []
    for row in rows:
        if not planning.effective(prefs.get(row["key"]), project_on) or holds_claim(row["key"], cands):
            continue
        if row["activity_status"] in IDLE_STATES or (row["id"] == ready and row["activity_status"] == "unknown"):
            out.append(row)
    return out


def next_open(cands: Sequence[planning.Candidate], session_state: Optional[str], position: planning.Position) -> Optional[planning.Candidate]:
    for cand in cands:
        if cand.status != planning.OPEN or cand.row["claude_working"]:
            continue
        if position(cand.row, cand.status, session_state=session_state, idle=True) == planning.AGENT_IDLE:
            return cand
    return None


def with_session_quiet(cand: planning.Candidate, session_last: Optional[float], now: float, interval_s: float) -> planning.Candidate:
    if session_last is None or session_last >= cand.last_activity or now - cand.last_activity >= interval_s:
        return cand
    return replace(cand, last_activity=session_last, pickup=True)
