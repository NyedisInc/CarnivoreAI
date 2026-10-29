
from __future__ import annotations

import sqlite3
from typing import Any, Dict, Iterable, List, Optional, Set

QUESTION_REF = "question:"
SUBJECT_PREFIXES = ("wake_refused:", "wake_failed:", "stuck:", "dead:")
OPEN_STATES = ("routing", "open", "reopened")
ASKING_KINDS = ("question", "waiting")
ASKING_PREFIXES = ("stuck:", "alert:")

_LIVE_SQL = (
    "SELECT DISTINCT k.question_id, k.agent_id FROM swarm_question_askers k "
    "JOIN swarm_questions q ON q.id = k.question_id JOIN swarm_agents a ON a.id = k.agent_id "
    "WHERE q.state IN ('routing', 'open', 'reopened') AND a.torn_down_at IS NULL "
    "AND (q.state = 'reopened' OR NOT EXISTS "
    "(SELECT 1 FROM swarm_wakes w WHERE w.agent_id = k.agent_id AND w.started_at > k.asked_at))")


def live_questions(conn: sqlite3.Connection) -> Dict[int, Set[int]]:
    out: Dict[int, Set[int]] = {}
    for qid, agent_id in conn.execute(_LIVE_SQL).fetchall():
        out.setdefault(int(qid), set()).add(int(agent_id))
    return out


def asking_agents(live: Dict[int, Set[int]]) -> Set[int]:
    return set().union(*live.values()) if live else set()


def question_id(swarm_ref: str) -> Optional[int]:
    if not swarm_ref.startswith(QUESTION_REF):
        return None
    tail = swarm_ref[len(QUESTION_REF):]
    return int(tail) if tail.isdigit() else None


def subject_agent(swarm_ref: str) -> Optional[int]:
    for prefix in SUBJECT_PREFIXES:
        if swarm_ref.startswith(prefix):
            head = swarm_ref[len(prefix):].split(":", 1)[0]
            return int(head) if head.isdigit() else None
    return None


def card_counts(swarm_ref: str, live: Dict[int, Set[int]], live_agents: Set[int]) -> bool:
    qid = question_id(swarm_ref)
    if qid is not None:
        return qid in live
    subject = subject_agent(swarm_ref)
    return subject is None or subject in live_agents


def asks_owner(kind: str, swarm_ref: str) -> bool:
    return kind in ASKING_KINDS or swarm_ref.startswith(ASKING_PREFIXES)


def _open_thread_question(item: Dict[str, Any]) -> bool:
    return any(m.get("kind") == "question" and not m.get("answered") for m in item.get("thread") or [])


def entry_waits(entry: Dict[str, Any], live: Dict[int, Set[int]]) -> bool:
    if entry.get("kind") != "card":
        return False
    item = entry.get("item") or {}
    if item.get("state") == "done" or item.get("status") == "done":
        return False
    qid = question_id(str(item.get("swarm_ref") or ""))
    if qid is not None:
        return qid in live
    return item.get("status") == "question" or _open_thread_question(item)


def annotate(conn: sqlite3.Connection, entries: Iterable[Dict[str, Any]]) -> None:
    live = live_questions(conn)
    for entry in entries:
        if entry.get("kind") == "card":
            entry["waits_on_owner"] = entry_waits(entry, live)


def stale_questions(conn: sqlite3.Connection) -> List[int]:
    live = live_questions(conn)
    rows = conn.execute("SELECT id FROM swarm_questions WHERE state IN ('routing', 'open', 'reopened') ORDER BY id").fetchall()
    return [int(r[0]) for r in rows if int(r[0]) not in live]
