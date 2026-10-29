
from __future__ import annotations

import sqlite3
from typing import Any, Dict, List

from src.core.swarm import body
from src.core.swarm.stream_sources import _epoch, event_entry
from src.core.trail_entry import utc_now

_SNIPPET = 160


def _line(text: str) -> str:
    return '"' + " ".join(text.split())[:_SNIPPET] + '"'


def message_entry(entry_id: str, at: float, author_agent_id: int, text: str) -> Dict[str, Any]:
    return {"kind": "agent", "id": entry_id, "at": float(at), "text": text, "author_agent_id": author_agent_id}


def _events(conn: sqlite3.Connection, agent_id: int, limit: int) -> List[Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    names = {r[0]: r[1] for r in conn.execute("SELECT id, display_name FROM swarm_agents")}

    def add(entry: Dict[str, Any]) -> None:
        out.setdefault(entry["id"], entry)

    for r in conn.execute(
            "SELECT q.*, k.asked_at, k.agent_id AS asker FROM swarm_questions q JOIN swarm_question_askers k ON k.question_id = q.id "
            "WHERE k.agent_id = ? ORDER BY q.id DESC LIMIT ?", (agent_id, limit)).fetchall():
        ref = f"question:{r['id']}"
        add(message_entry(f"q:{r['id']}:ask:{agent_id}", _epoch(r["asked_at"]), agent_id, r["text"]))
        if r["card_ref"]:
            last = conn.execute("SELECT MAX(at) FROM swarm_question_hops WHERE question_id = ?", (r["id"],)).fetchone()[0]
            add(event_entry("escalated", _epoch(max(r["created_at"], last or r["created_at"])), f"{ref}:owner",
                            "no tier above could answer, so the question went to the owner",
                            agent_id=agent_id, question_id=r["id"]))
    for r in conn.execute(
            "SELECT q.id, q.text, k.agent_id AS asker, k.asked_at FROM swarm_questions q "
            "JOIN swarm_question_askers k ON k.question_id = q.id AND k.asked_at = "
            "(SELECT MIN(asked_at) FROM swarm_question_askers WHERE question_id = q.id) "
            "WHERE q.id IN (SELECT question_id FROM swarm_question_hops WHERE agent_id = ? AND outcome != 'skipped') "
            "OR q.answered_by = ? ORDER BY q.id DESC LIMIT ?", (agent_id, f"agent:{agent_id}", limit)).fetchall():
        add(message_entry(f"q:{r['id']}:ask:{r['asker']}", _epoch(r["asked_at"]), r["asker"], r["text"]))
    for r in conn.execute(
            "SELECT h.*, q.text FROM swarm_question_hops h JOIN swarm_questions q ON q.id = h.question_id "
            "WHERE (h.agent_id = ? OR h.question_id IN (SELECT question_id FROM swarm_question_askers WHERE agent_id = ?)) "
            "AND (h.outcome = 'passed' OR (h.outcome = 'timeout' AND h.at <= ?)) ORDER BY h.id DESC LIMIT ?",
            (agent_id, agent_id, utc_now(), limit)).fetchall():
        add(event_entry("escalated", _epoch(r["at"]), f"question:{r['question_id']}:hop:{r['id']}",
                        f"{names.get(r['agent_id'], 'a tier')} "
                        f"{'passed on' if r['outcome'] == 'passed' else 'did not answer'} {_line(r['text'])}; it went up",
                        agent_id=r["agent_id"], question_id=r["question_id"]))
    for r in conn.execute(
            "SELECT q.* FROM swarm_questions q WHERE q.state = 'answered' AND q.answered_by LIKE 'agent:%' AND (q.answered_by = ? "
            "OR q.id IN (SELECT question_id FROM swarm_question_askers WHERE agent_id = ?)) ORDER BY q.id DESC LIMIT ?",
            (f"agent:{agent_id}", agent_id, limit)).fetchall():
        by = str(r["answered_by"]).split(":", 1)[1]
        if by.isdigit() and r["answer_text"]:
            add(message_entry(f"q:{r['id']}:answer", _epoch(r["answered_at"]), int(by), r["answer_text"]))
    return list(out.values())


def _learned(conn: sqlite3.Connection, agent_id: int, limit: int) -> List[Dict[str, Any]]:
    return [event_entry("learned", _epoch(r["at"]), f"fact:{r['id']}",
                        f"new rule: {' '.join(r['title'].split())[:80]}", agent_id=agent_id, fact_id=r["id"],
                        origin=r["origin"], scope=r["scope"])
            for r in conn.execute("SELECT id, title, scope, origin, COALESCE(ruled_at, taught_at) AS at FROM swarm_facts "
                                  "WHERE agent_id = ? AND state = 'live' AND kind = 'rule' ORDER BY at DESC LIMIT ?", (agent_id, limit))]


async def learned_events(agent: Dict[str, Any], limit: int) -> List[Dict[str, Any]]:
    return await body.run_db(lambda c: _learned(c, agent["id"], limit))


async def question_events(agent: Dict[str, Any], limit: int) -> List[Dict[str, Any]]:
    return await body.run_db(lambda c: _events(c, agent["id"], limit))
