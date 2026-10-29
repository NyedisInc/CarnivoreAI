
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

from src.core import db
from src.core.db import transaction
from src.core.trail_entry import utc_now

logger = structlog.get_logger()

KINDS = ("rule", "note")
NOTE_DAYS = 14
RULE_AFTER_USES = 3
SWEEP_DAYS = 7
RESAVE_COVERAGE = 0.8
MEMORY_BAR = ("Long-term memory is for rules only: save a fact only if it (a) changes how an agent acts later, (b) is not "
              "already in code, docs/DECISIONS.md, CLAUDE.md, an issue, a card or git, and (c) will be needed more than once. "
              "Never save a question, a status or a one-off order. A fact is a note unless you say kind rule; a note "
              "expires 14 days after its last use and becomes a rule once 3 separate conversations use it.")
_FMT = "%Y-%m-%dT%H:%M:%S.%fZ"


def _stamp(at: datetime) -> str:
    return at.astimezone(timezone.utc).strftime(_FMT)


def conversation_key(conn: sqlite3.Connection, agent_id: int) -> Optional[str]:
    row = conn.execute("SELECT id, conversation_uuid FROM swarm_wakes WHERE agent_id = ? AND ended_at IS NULL", (agent_id,)).fetchone()
    if row is None:
        return None
    return str(row["conversation_uuid"] or f"wake:{row['id']}")


def record_use(conn: sqlite3.Connection, fact_id: str, key: Optional[str], now: Optional[str] = None) -> Optional[str]:
    row = conn.execute("SELECT kind, used_in FROM swarm_facts WHERE id = ? AND state = 'live'", (fact_id,)).fetchone()
    if row is None:
        return None
    used = json.loads(row["used_in"] or "[]")
    if key and key not in used:
        used.append(key)
    at = now or utc_now()
    kind = "rule" if row["kind"] == "rule" or len(used) >= RULE_AFTER_USES else "note"
    conn.execute("UPDATE swarm_facts SET last_used_at = ?, used_in = ?, kind = ?, "
                 "ruled_at = CASE WHEN ? = 'rule' AND kind = 'note' THEN ? ELSE ruled_at END WHERE id = ?",
                 (at, json.dumps(used), kind, kind, at, fact_id))
    if kind != row["kind"]:
        logger.info("swarm_note_became_rule", fact_id=fact_id, uses=len(used))
    return kind


def expired_notes(conn: sqlite3.Connection, now: datetime) -> List[str]:
    cutoff = _stamp(now - timedelta(days=NOTE_DAYS))
    return [r[0] for r in conn.execute("SELECT id FROM swarm_facts WHERE state = 'live' AND kind = 'note' "
                                       "AND COALESCE(last_used_at, taught_at) <= ? ORDER BY id", (cutoff,))]


def expire(conn: sqlite3.Connection, now: datetime) -> List[str]:
    from src.core.swarm import facts

    killed = []
    for fact_id in expired_notes(conn, now):
        try:
            facts.kill(conn, fact_id)
            killed.append(fact_id)
        except (facts.FactNotFound, facts.FactRefused, sqlite3.Error, OSError) as exc:
            logger.warning("swarm_note_expire_failed", fact_id=fact_id, error_type=type(exc).__name__)
    if killed:
        logger.info("swarm_notes_expired", count=len(killed))
    return killed


def _project_agents(conn: sqlite3.Connection, due_before: Optional[str]) -> List[Dict[str, Any]]:
    sql = "SELECT * FROM swarm_agents WHERE rank = 'project' AND torn_down_at IS NULL"
    args: tuple = ()
    if due_before is not None:
        sql, args = sql + " AND COALESCE(memory_swept_at, created_at) <= ?", (due_before,)
    return [dict(r) for r in conn.execute(sql + " ORDER BY id", args)]


def sweep_orders(conn: sqlite3.Connection, agent: Dict[str, Any], why: str) -> str:
    ids, frontier = [agent["id"]], [agent["id"]]
    while frontier and len(ids) < 500:
        marks = ",".join("?" * len(frontier))
        frontier = [r[0] for r in conn.execute(f"SELECT id FROM swarm_agents WHERE parent_id IN ({marks}) AND id NOT IN "
                                               f"({','.join('?' * len(ids))})", (*frontier, *ids))]
        ids += frontier
    rows = conn.execute(f"SELECT f.id, f.kind, f.title, f.rel_path, f.last_used_at, f.taught_at, a.display_name, a.repo_dir, "
                        f"a.slug, a.memory_scope FROM swarm_facts f JOIN swarm_agents a ON a.id = f.agent_id WHERE f.state = 'live' "
                        f"AND f.agent_id IN ({','.join('?' * len(ids))}) ORDER BY a.id, f.taught_at", ids).fetchall()
    from src.core.swarm import learning, memory

    lines = [f"{why}: review your facts and your children's. {MEMORY_BAR}",
             "Delete with swarm_forget every fact that is now in code or docs, stale, or a duplicate of another; keep the rest. "
             "When done, post exactly one line with swarm_say: \"kept N, deleted M\".", f"{len(rows)} live facts:"]
    for r in rows:
        path = memory.memory_dir(Path(r["repo_dir"]), r["slug"], r["memory_scope"]) / r["rel_path"]
        lines.append(f"- {r['id']} ({learning.one_line(r['display_name'])}, {r['kind']}, last used "
                     f"{(r['last_used_at'] or r['taught_at'])[:10]}): {learning.one_line(r['title'])[:160]} [{path}]")
    return "\n".join(lines)


async def _send_sweep(app_state: Any, agent: Dict[str, Any], why: str) -> bool:
    from src.core.swarm import body, routing

    def stamp_and_word(conn: sqlite3.Connection) -> str:
        with transaction(conn):
            conn.execute("UPDATE swarm_agents SET memory_swept_at = ? WHERE id = ?", (utc_now(), agent["id"]))
        return sweep_orders(conn, agent, why)

    text = await body.run_db(stamp_and_word)
    return await routing.tell(app_state, agent["id"], text, source="learning", authority="data",
                              ref=f"memory_sweep:{agent['id']}:{utc_now()[:10]}", reason="learning")


async def sweep(app_state: Any, now: Optional[datetime] = None) -> Dict[str, int]:
    from src.core.swarm import body

    at = now or datetime.now(timezone.utc)
    try:
        expired = await body.run_db(lambda c: expire(c, at))
        due = await body.run_db(lambda c: _project_agents(c, _stamp(at - timedelta(days=SWEEP_DAYS))))
    except (sqlite3.Error, db.DatastoreUnreadableError, OSError) as exc:
        logger.warning("swarm_memory_sweep_unreadable", error_type=type(exc).__name__)
        return {"expired": 0, "swept": 0}
    swept = 0
    for agent in due:
        swept += 1 if await _send_sweep(app_state, agent, "weekly memory sweep") else 0
    return {"expired": len(expired), "swept": swept}


async def cleanup(app_state: Any) -> Dict[str, Any]:
    from src.core.swarm import body

    agents = await body.run_db(lambda c: _project_agents(c, None))
    done, refused = [], []
    for agent in agents:
        (done if await _send_sweep(app_state, agent, "one-time memory cleanup") else refused).append(agent["id"])
    logger.info("swarm_memory_cleanup_sent", agents=len(done), refused=len(refused))
    return {"agents": done, "refused": refused}
