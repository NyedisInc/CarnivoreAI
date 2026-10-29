
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, FrozenSet, Optional

from src.core.skill_fires.store import SkillFireStore
from src.core.skill_watch.tripwire import undisclosed
from src.core.skill_watch.spans import read_span

MAX_SPANS = 60
RECENT = 5
MAX_DAYS = 365


def _cutoff(now: datetime, days: int) -> str:
    return (now - timedelta(days=days)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def build_autopsy(skill: str, days: int, store: SkillFireStore, now: datetime, *,
                  installed_digest: Optional[str] = None, installed_at: Optional[str] = None,
                  disclosed: Optional[FrozenSet[str]] = None,
                  attribution: Optional[Any] = None) -> Dict[str, Any]:
    cutoff = _cutoff(now, min(max(days, 1), MAX_DAYS))
    counted = store.usage(skill, [cutoff])
    if counted is None:
        return {"skill": skill, "days": days, "state": "not_measured", "fires": None}
    out: Dict[str, Any] = {
        "skill": skill, "days": days, "state": "measured", "fires": counted[0],
        "spans_measured": 0, "tool_calls": 0, "tool_errors": 0, "interrupts": 0,
        "corrections": 0, "corrections_measured": 0, "tokens_total": None,
        "categories": {}, "undisclosed": None, "recent": [],
    }
    seen: set = set()
    hit: set = set()
    judged = False
    for path, off, harness, fired_at in store.fires_since(skill, cutoff, MAX_SPANS):
        span = read_span(path, off, harness)
        if span is None:
            continue
        out["spans_measured"] += 1
        out["tool_calls"] += span.tool_calls
        out["tool_errors"] += span.tool_errors
        out["interrupts"] += span.interrupts
        if span.correction is not None:
            out["corrections_measured"] += 1
            out["corrections"] += 1 if span.correction else 0
        if span.tokens is not None:
            out["tokens_total"] = (out["tokens_total"] or 0) + span.tokens
        for category, n in span.categories.items():
            out["categories"][category] = out["categories"].get(category, 0) + n
            seen.add(category)
        span_digest, span_at = installed_digest, installed_at
        if attribution is not None:
            span_disclosed = attribution.disclosed(skill, span.cwd)
            row = attribution.row(skill, span.cwd)
            span_digest, span_at = (row.digest, row.updated_at) if row is not None else (None, None)
            extra = attribution.dynamic(skill, span.cwd) if span_disclosed is not None else frozenset()
            for category in extra:
                out["categories"][category] = out["categories"].get(category, 0) + 1
            seen.update(extra)
            if span_disclosed is not None:
                judged = True
                hit.update(undisclosed(sorted(set(span.categories) | extra), span_disclosed))
        if len(out["recent"]) < RECENT:
            ran_under = span_digest if (
                span_digest and span_at and fired_at
                and fired_at[:19] >= span_at[:19]) else None
            out["recent"].append({
                "fired_at": fired_at, "session": path.rsplit("/", 1)[-1].rsplit(".", 1)[0],
                "tool_calls": span.tool_calls, "tool_errors": span.tool_errors,
                "interrupted": span.interrupts > 0, "tokens": span.tokens,
                "correction": span.correction, "next_excerpt": span.next_excerpt,
                "ended": span.ended, "categories": sorted(span.categories),
                "digest": ran_under})
    if attribution is not None:
        out["undisclosed"] = sorted(hit) if judged else None
    elif disclosed is not None:
        out["undisclosed"] = undisclosed(sorted(seen), disclosed)
    return out
