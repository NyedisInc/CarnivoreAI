
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from src.core.session_timeline import constants as C


@dataclass
class Sources:

    session: Dict[str, Any]
    entries: List[Dict[str, Any]]
    now: datetime
    compacts: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    bookmarks: List[Dict[str, Any]] = field(default_factory=list)
    points: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    split_times: Dict[Tuple[str, str], str] = field(default_factory=dict)


def parse_time(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _began(entry: Dict[str, Any], split_times: Dict[Tuple[str, str], str]) -> Optional[Dict[str, Any]]:
    began = entry.get("began")
    if not began:
        return None
    split = began.get("split")
    if split:
        at = split_times.get((split.get("conversation") or "", split.get("message_uuid") or ""))
        split = {**split, "at": at}
    return {**began, "split": split}


def _mark(kind: str, conv: str, key: str, at: Optional[str], **fields: Any) -> Dict[str, Any]:
    return {"id": f"{kind}:{conv}:{key}", "kind": kind, "conversation_id": conv, "at": at, "entry_uuid": None,
            "label": "", "snippet": "", "can_peek": False, **fields}


def _marks(src: Sources, known: set) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for conv, found in src.compacts.items():
        for p in found:
            out.append(_mark(C.MARK_COMPACT, conv, str(p.get("jsonl_line") or p.get("at") or ""), p.get("at") or None,
                             entry_uuid=p.get("entry_uuid"), can_peek=bool(p.get("entry_uuid")),
                             trigger=p.get("trigger") or None, pre_tokens=p.get("pre_tokens")))
    for b in src.bookmarks:
        conv = b.get("claude_session_uuid")
        if conv in known:
            out.append(_mark(C.MARK_BOOKMARK, conv, str(b["id"]), b.get("entry_timestamp") or b.get("created_at"),
                             entry_uuid=b.get("entry_uuid"), can_peek=True, label=b.get("label") or "",
                             snippet=(b.get("snippet") or "")[:C.SNIPPET_CHARS], bookmark_id=b["id"],
                             created_by=b.get("created_by")))
    for entry in src.entries:
        for m in entry["milestones"]:
            if m["kind"] == C.MILESTONE_RESTART and m.get("at"):
                out.append(_mark(C.MARK_RESTART, entry["conversation_id"], m["at"], m["at"]))
    for conv, found in src.points.items():
        for p in found:
            digest = p.get("digest") or {}
            out.append(_mark(C.MARK_RESTORE, conv, str(p["id"]), p.get("created_at"), point_id=p["id"],
                             reason=p.get("reason"), pinned=bool(p.get("pinned")), failsafe=p.get("kind") == "current",
                             turns=p.get("turns"), snippet=(digest.get("last_prompt") or "")[:C.SNIPPET_CHARS]))
    return out


def _event_times(src: Sources, conv: str, marks: List[Dict[str, Any]]) -> List[datetime]:
    times = [parse_time(m["at"]) for m in marks if m["conversation_id"] == conv]
    for p in src.points.get(conv, []):
        times.append(parse_time((p.get("digest") or {}).get("started_at")))
    entry = next((e for e in src.entries if e["conversation_id"] == conv), None)
    times += [parse_time(m.get("at")) for m in (entry["milestones"] if entry else [])]
    return [t for t in times if t is not None]


def _bars(src: Sources, marks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    bars = []
    for entry in src.entries:
        conv = entry["conversation_id"]
        began = _began(entry, src.split_times)
        events = _event_times(src, conv, marks)
        start = parse_time(began["at"]) if began else None
        bars.append({"conversation_id": conv, "current": bool(entry["current"]), "level": entry.get("level"),
                     "began": began, "_start": start or (min(events) if events else None), "_events": events})
    for i, bar in enumerate(bars):
        if bar["current"]:
            end = src.now
        else:
            children = [parse_time(o["began"]["at"]) for o in bars
                        if o["began"] and o["began"].get("from_conversation") == bar["conversation_id"]]
            children = [c for c in children if c is not None]
            nxt = bars[i + 1]["_start"] if i + 1 < len(bars) else None
            end = min(children) if children else nxt or (max(bar["_events"]) if bar["_events"] else None)
        bar["_end"] = end
    carry: Optional[datetime] = None
    for bar in bars:
        if bar["_start"] is None:
            bar["_start"] = carry or bar["_end"]
        if bar["_end"] is not None and bar["_start"] is not None and bar["_end"] < bar["_start"]:
            bar["_end"] = bar["_start"]
        carry = bar["_end"] or carry
    return bars


def _gaps(src: Sources, bars: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    sleeps, wakes = [], []
    for entry in src.entries:
        for m in entry["milestones"]:
            at = parse_time(m.get("at"))
            if at is None:
                continue
            if m["kind"] == C.MILESTONE_SLEEP:
                sleeps.append((at, m["at"], entry["conversation_id"]))
            elif m["kind"] in C.WAKE_KINDS:
                wakes.append(at)
    ends = {b["conversation_id"]: b["_end"] for b in bars}
    out, seen = [], set()
    for at, raw, conv in sorted(sleeps, key=lambda s: s[0]):
        if (conv, raw) in seen:
            continue
        seen.add((conv, raw))
        later = [w for w in wakes if w > at]
        end = min(later) if later else None
        current = any(b["conversation_id"] == conv and b["current"] for b in bars)
        if end is None and not current:
            end = ends.get(conv)
        out.append({"id": f"sleep:{conv}:{raw}", "conversation_id": conv, "start": raw,
                    "end": end.isoformat() if end else None, "open": end is None})
    return out


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value is not None else None


def assemble(src: Sources) -> Dict[str, Any]:
    known = {e["conversation_id"] for e in src.entries}
    marks = _marks(src, known)
    bars = _bars(src, marks)
    start_of = {b["conversation_id"]: b["_start"] for b in bars}
    floor = datetime.min.replace(tzinfo=timezone.utc)
    marks.sort(key=lambda m: (parse_time(m["at"]) or start_of.get(m["conversation_id"]) or floor, m["id"]))
    session = src.session
    return {
        "session_uuid": session["session_uuid"], "session_row_id": session["row_id"], "family": session["family"],
        "current_conversation": session.get("current"), "now": src.now.isoformat(),
        "bars": [{"conversation_id": b["conversation_id"], "current": b["current"], "level": b["level"],
                  "began": b["began"], "started_at": _iso(b["_start"]), "ended_at": _iso(b["_end"])} for b in bars],
        "marks": marks,
        "gaps": _gaps(src, bars),
    }
