
from __future__ import annotations

import asyncio
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.core.crosstalk import store as crosstalk_store
from src.core.swarm import body

EVENTS = ("spawned", "reported", "accepted", "asked", "answered", "escalated", "learned", "promoted")


def _epoch(stamp: str) -> float:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()


def event_entry(event: str, at: float, ref: str, text: str, **extra: Any) -> Dict[str, Any]:
    if event not in EVENTS:
        raise ValueError(f"unknown swarm event {event!r}")
    return {"kind": "event", "id": f"ev:{event}:{ref}", "at": float(at), "event": event, "ref": ref, "text": text, **extra}


SUMMARY_CHARS = 100
_LEAD_MARKUP = re.compile(r"^(?:#{1,6}\s+|>\s*|[-*+]\s+(?:\[[ xX]\]\s+)?|\d+[.)]\s+)+")


def summary_line(text: str) -> str:
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("```") or re.fullmatch(r"[-*_=\s]{3,}", line):
            continue
        line = " ".join(_LEAD_MARKUP.sub("", line).replace("**", "").replace("__", "").replace("`", "").split())
        if not line:
            continue
        if len(line) <= SUMMARY_CHARS:
            return line
        cut = line[:SUMMARY_CHARS - 3]
        space = cut.rfind(" ")
        return (cut[:space] if space > SUMMARY_CHARS // 2 else cut).rstrip(" ,;:.") + "..."
    return ""


def traffic_entry(key: str, msg: Dict[str, Any]) -> Dict[str, Any]:
    out = msg["sender_key"] == key
    return {"kind": "traffic", "id": f"xt:{msg['id']}", "at": float(msg["created_at"]), "direction": "out" if out else "in",
            "peer": (msg["receiver_name"] or msg["receiver_id"]) if out else msg["sender_name"],
            "peer_key": msg["receiver_key"] if out else msg["sender_key"], "text": msg["text"], "summary": summary_line(msg["text"]),
            "thread": msg["thread"], "in_reply_to": msg["in_reply_to"],
            "receipt": {"status": msg["status"], "reason": msg["reason"], "delivered_at": msg["delivered_at"]}}


async def crosstalk_traffic(agent: Dict[str, Any], limit: int) -> List[Dict[str, Any]]:
    row_id = agent.get("session_row_id")
    if row_id is None:
        return []
    found = await body.run_db(lambda c: c.execute("SELECT session_uuid FROM sessions WHERE id = ?", (row_id,)).fetchone())
    key = found[0] if found else None
    if not key:
        return []
    rows = await asyncio.to_thread(crosstalk_store.recent_for, key, limit)
    return [traffic_entry(key, m) for m in rows]


def _events(conn: Any, agent_id: int, limit: int) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for r in conn.execute(
            "SELECT c.id, c.display_name, c.job, c.rank, c.created_at, COALESCE(p.display_name, 'a parent') AS parent_name "
            "FROM swarm_agents c JOIN swarm_agents p ON p.id = c.parent_id WHERE c.parent_id = ? OR c.id = ? "
            "ORDER BY c.created_at DESC LIMIT ?", (agent_id, agent_id, limit)).fetchall():
        text = (f"{r['display_name']} was turned on" if r["rank"] in ("project", "company")
                else f"{r['parent_name']} spawned {r['display_name']}: {r['job'][:200]}")
        out.append(event_entry("spawned", _epoch(r["created_at"]), f"agent:{r['id']}", text, agent_id=r["id"]))
    for r in conn.execute(
            "SELECT r.id, r.agent_id, r.parent_id, r.state, r.created_at, r.decided_at, "
            "COALESCE(a.display_name, 'an agent') AS agent_name, COALESCE(p.display_name, 'a parent') AS parent_name "
            "FROM swarm_reports r LEFT JOIN swarm_agents a ON a.id = r.agent_id LEFT JOIN swarm_agents p ON p.id = r.parent_id "
            "WHERE r.agent_id = ? OR r.parent_id = ? ORDER BY r.id DESC LIMIT ?", (agent_id, agent_id, limit)).fetchall():
        ref = f"report:{r['id']}"
        out.append(event_entry("reported", _epoch(r["created_at"]), ref, f"{r['agent_name']} reported to {r['parent_name']}",
                               agent_id=r["agent_id"], report_id=r["id"]))
        if r["state"] == "accepted" and r["decided_at"]:
            out.append(event_entry("accepted", _epoch(r["decided_at"]), ref, f"{r['parent_name']} accepted {r['agent_name']}'s report",
                                   agent_id=r["agent_id"], report_id=r["id"]))
    return out


async def swarm_events(agent: Dict[str, Any], limit: int) -> List[Dict[str, Any]]:
    return await body.run_db(lambda c: _events(c, agent["id"], limit))


async def reply_drafts(agent: Dict[str, Any], limit: int) -> List[Dict[str, Any]]:
    from src.core.swarm import reply_mirror

    return (await asyncio.to_thread(reply_mirror.draft_entries, agent))[-limit:]


SOURCES = (crosstalk_traffic, swarm_events, reply_drafts)
