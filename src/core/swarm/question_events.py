
from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, List

from src.core.swarm import body
from src.core.swarm.stream_sources import _epoch, event_entry
from src.core.trail_entry import utc_now

_SNIPPET = 160


def _line(text: str) -> str:
    return '"' + " ".join(text.split())[:_SNIPPET] + '"'


def _events(conn: sqlite3.Connection, agent_id: int, limit: int) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    names = {r[0]: r[1] for r in conn.execute("SELECT id, display_name FROM swarm_agents")}
    for r in conn.execute(
            "SELECT q.*, k.asked_at, k.agent_id AS asker FROM swarm_questions q JOIN swarm_question_askers k ON k.question_id = q.id "
            "WHERE k.agent_id = ? ORDER BY q.id DESC LIMIT ?", (agent_id, limit)).fetchall():
        ref = f"question:{r['id']}"
        out.append(event_entry("asked", _epoch(r["asked_at"]), ref, f"asked {_line(r['text'])}",
                               agent_id=agent_id, question_id=r["id"]))
        if r["card_ref"]:
            last = conn.execute("SELECT MAX(at) FROM swarm_question_hops WHERE question_id = ?", (r["id"],)).fetchone()[0]
            out.append(event_entry("escalated", _epoch(max(r["created_at"], last or r["created_at"])), f"{ref}:owner",
                                   "no tier above could answer, so the question went to the owner",
                                   agent_id=agent_id, question_id=r["id"]))
    for r in conn.execute(
            "SELECT h.*, q.text FROM swarm_question_hops h JOIN swarm_questions q ON q.id = h.question_id "
            "WHERE (h.agent_id = ? OR h.question_id IN (SELECT question_id FROM swarm_question_askers WHERE agent_id = ?)) "
            "AND (h.outcome = 'passed' OR (h.outcome = 'timeout' AND h.at <= ?)) ORDER BY h.id DESC LIMIT ?",
            (agent_id, agent_id, utc_now(), limit)).fetchall():
        out.append(event_entry("escalated", _epoch(r["at"]), f"question:{r['question_id']}:hop:{r['id']}",
                               f"{names.get(r['agent_id'], 'a tier')} "
                               f"{'passed on' if r['outcome'] == 'passed' else 'did not answer'} {_line(r['text'])}; it went up",
                               agent_id=r["agent_id"], question_id=r["question_id"]))
    for r in conn.execute(
            "SELECT q.* FROM swarm_questions q WHERE q.state = 'answered' AND (q.answered_by = ? OR q.id IN "
            "(SELECT question_id FROM swarm_question_askers WHERE agent_id = ?)) ORDER BY q.id DESC LIMIT ?",
            (f"agent:{agent_id}", agent_id, limit)).fetchall():
        who = "the owner" if r["answered_by"] == "owner" else names.get(int(str(r["answered_by"]).split(":")[1]), "an agent")
        out.append(event_entry("answered", _epoch(r["answered_at"]), f"question:{r['id']}", f"{who} answered {_line(r['text'])}",
                               question_id=r["id"], answered_by=r["answered_by"], receipt=_receipt(conn, r)))
    return out


def _receipt(conn: sqlite3.Connection, q: sqlite3.Row) -> Dict[str, Any]:
    if q["answered_by"] == "owner":
        return {"kind": "owner_answer", "rendered": "answered by you", "owner_message_ref": q["answer_message_ref"], "facts": []}
    row = conn.execute("SELECT kind, fact_ids, rendered FROM swarm_receipts WHERE question_id = ? ORDER BY id DESC LIMIT 1",
                       (q["id"],)).fetchone()
    if row is None:
        return {"kind": "judgment", "rendered": "no stored fact", "owner_message_ref": None, "facts": []}
    ids = json.loads(row["fact_ids"])
    found = {f["id"]: f for f in conn.execute(
        f"SELECT id, title, scope, origin, owner_message_ref, taught_at, state FROM swarm_facts "
        f"WHERE id IN ({','.join('?' * len(ids))})", ids)} if ids else {}
    return {"kind": row["kind"], "rendered": row["rendered"], "owner_message_ref": None,
            "facts": [dict(found[i]) for i in ids if i in found]}


def _learned(conn: sqlite3.Connection, agent_id: int, limit: int) -> List[Dict[str, Any]]:
    return [event_entry("learned", _epoch(r["taught_at"]), f"fact:{r['id']}",
                        f"learned \"{' '.join(r['title'].split())[:120]}\" ({r['scope']})", agent_id=agent_id, fact_id=r["id"],
                        origin=r["origin"], scope=r["scope"])
            for r in conn.execute("SELECT id, title, scope, origin, taught_at FROM swarm_facts WHERE agent_id = ? "
                                  "AND state = 'live' ORDER BY taught_at DESC LIMIT ?", (agent_id, limit))]


async def learned_events(agent: Dict[str, Any], limit: int) -> List[Dict[str, Any]]:
    return await body.run_db(lambda c: _learned(c, agent["id"], limit))


async def question_events(agent: Dict[str, Any], limit: int) -> List[Dict[str, Any]]:
    return await body.run_db(lambda c: _events(c, agent["id"], limit))
