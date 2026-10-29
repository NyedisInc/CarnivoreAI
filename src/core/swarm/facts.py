
from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

from src.core import db
from src.core.db import transaction
from src.core.mcp.caller import AgentCaller
from src.core.swarm import activity, body, fact_index, memory, push, spawn, store, thread_port
from src.core.trail_entry import utc_now

logger = structlog.get_logger()

CONFLICT_COVERAGE = 0.8
MAX_TITLE_CHARS = 200
MAX_FACT_CHARS = 8000
CONFLICT_PREFIX = "conflict:"
_CHAIN_LIMIT = 10
_ERRORS = (memory.SwarmFileError, OSError, sqlite3.Error, db.DatastoreUnreadableError)


class FactRefused(ValueError):
    pass


class FactNotFound(LookupError):
    pass


@dataclass(frozen=True)
class KillResult:

    fact: Dict[str, Any]
    cited_question_ids: List[int]


def _chain_ids(conn: sqlite3.Connection, agent: Dict[str, Any]) -> List[int]:
    ids, current = [], agent
    while current is not None and len(ids) < _CHAIN_LIMIT and current["id"] not in ids:
        ids.append(current["id"])
        current = store.get_agent(conn, current["parent_id"]) if current["parent_id"] is not None else None
    return ids


def chain_facts(conn: sqlite3.Connection, agent: Dict[str, Any], text: str, *, limit: int = 3) -> List[Dict[str, str]]:
    chain = _chain_ids(conn, agent)
    project_id = next((r[0] for i in chain for r in [conn.execute("SELECT project_id FROM swarm_agents WHERE id = ?", (i,)).fetchone()] if r and r[0] is not None), None)
    titles = {f"fact:{r['id']}": r["title"] for r in conn.execute(
        f"SELECT f.id, f.title FROM swarm_facts f JOIN swarm_agents a ON a.id = f.agent_id "
        f"WHERE f.state = 'live' AND f.origin IN ('agent', 'owner') AND f.agent_id IN ({','.join('?' * len(chain))}) "
        f"AND (f.agent_id = ? OR f.scope = 'craft' OR a.project_id IS ? OR (a.project_id IS NULL AND a.rank IN ('feature', 'task')))",
        (*chain, agent["id"], project_id))
        if not memory.scan_text(r["title"])}
    ranked = fact_index.rank(conn, fact_index.query_terms(text), chain, doc_keys=set(titles))
    return [{"fact_id": h.doc_key[5:], "title": titles[h.doc_key]} for h in ranked[:limit]]


_CHAIN_READ_ERRORS = (body.BodyError, fact_index.Fts5Missing, sqlite3.Error, db.DatastoreUnreadableError, OSError, RuntimeError, ValueError)


async def chain_facts_for(agent_id: int, text: str) -> List[Dict[str, str]]:
    def read(conn: sqlite3.Connection) -> List[Dict[str, str]]:
        agent = store.get_agent(conn, int(agent_id))
        return chain_facts(conn, agent, text) if agent is not None else []

    try:
        return await body.run_db(read)
    except _CHAIN_READ_ERRORS as exc:
        logger.warning("swarm_card_chain_facts_failed", agent_id=agent_id, error=type(exc).__name__)
        return []


def _conflict_with(conn: sqlite3.Connection, agent: Dict[str, Any], title: str, text: str) -> Optional[Dict[str, Any]]:
    terms = fact_index.query_terms(f"{title} {text}")
    chain = _chain_ids(conn, agent)
    owner = {f"fact:{r['id']}": dict(r) for r in conn.execute(
        f"SELECT id, title, agent_id FROM swarm_facts WHERE origin = 'owner' AND state = 'live' "
        f"AND agent_id IN ({','.join('?' * len(chain))})", chain)}
    ranked = fact_index.rank(conn, terms, chain, set(owner))
    return owner[ranked[0].doc_key] if ranked and ranked[0].coverage >= CONFLICT_COVERAGE else None


def _resolve_source(conn: sqlite3.Connection, agent: Dict[str, Any], args: Dict[str, Any],
                    owner_text: Optional[str] = None) -> Dict[str, Any]:
    text, learning_id, cited = args.get("text"), args.get("learning_id"), args.get("owner_message_ref")
    if [text, learning_id, cited].count(None) != 2:
        raise FactRefused("give exactly one of text, learning_id and owner_message_ref")
    if cited is not None:
        return {"text": owner_text or "", "origin": "owner", "owner_message_ref": cited, "learning_id": None}
    if learning_id is None:
        if not isinstance(text, str) or not text.strip():
            raise FactRefused("text must be a non-empty string")
        return {"text": text.strip(), "origin": "agent", "owner_message_ref": None, "learning_id": None}
    if type(learning_id) is not int or learning_id < 1:
        raise FactRefused("learning_id must be a positive whole number")
    row = conn.execute("SELECT * FROM swarm_learning WHERE id = ?", (learning_id,)).fetchone()
    if row is None or row["agent_id"] != agent["id"] or row["state"] not in ("queued", "delivered"):
        raise FactRefused("that learning item is not waiting in your inbox")
    ref = row["owner_message_ref"]
    return {"text": row["text"], "origin": "owner" if ref else "agent", "owner_message_ref": ref or None,
            "learning_id": learning_id}


async def _owner_words(port: Any, agent: Dict[str, Any], args: Dict[str, Any]) -> Optional[str]:
    ref = args.get("owner_message_ref")
    if ref is None:
        return None
    if not isinstance(ref, str) or not ref.startswith("huddle:msg:"):
        raise FactRefused("owner_message_ref must look like huddle:msg:<id>")
    words = await port.owner_message(agent["thread_key"], ref) if port is not None else None
    if not words or not words.strip():
        raise FactRefused("that is not an owner message in your own thread")
    return words


def _validate(args: Dict[str, Any]) -> tuple:
    title, scope, push_up = args.get("title"), args.get("scope"), args.get("push_up", False)
    if not isinstance(title, str) or not title.strip() or len(title.strip()) > MAX_TITLE_CHARS:
        raise FactRefused(f"title is required, at most {MAX_TITLE_CHARS} characters")
    if scope not in memory.FACT_SCOPES:
        raise FactRefused("scope must be craft or project")
    if not isinstance(push_up, bool):
        raise FactRefused("push_up must be true or false")
    return " ".join(title.split()), scope, push_up


def _store(conn: sqlite3.Connection, agent: Dict[str, Any], title: str, scope: str, push_up: bool,
           source: Dict[str, Any]) -> Dict[str, Any]:
    text = source["text"]
    if len(text) > MAX_FACT_CHARS:
        raise FactRefused(f"the fact must be at most {MAX_FACT_CHARS} characters")
    conflict = _conflict_with(conn, agent, title, text) if source["origin"] == "agent" else None
    fact_id = "f_" + uuid.uuid4().hex[:12]
    taught_at = utc_now()
    mem = memory.memory_dir(Path(agent["repo_dir"]), agent["slug"], agent["memory_scope"])
    memory.ensure_layout(mem)
    path = memory.write_fact(mem, memory.Fact(fact_id, title, scope, source["origin"], taught_at, text,
                                              source["owner_message_ref"]))
    try:
        with transaction(conn):
            conn.execute(
                "INSERT INTO swarm_facts (id, agent_id, rel_path, title, scope, origin, owner_message_ref, taught_at, "
                "taught_by_agent_id, sha256, state) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (fact_id, agent["id"], f"facts/{fact_id}.md", title, scope, source["origin"], source["owner_message_ref"],
                 taught_at, agent["id"], hashlib.sha256(text.encode("utf-8")).hexdigest(),
                 "held" if conflict else "live"))
            if source["learning_id"] is not None:
                conn.execute("UPDATE swarm_learning SET state = 'stamped', scope_stamp = ? WHERE id = ?",
                             (scope, source["learning_id"]))
            if push_up and agent["parent_id"] is not None and not conflict:
                conn.execute("INSERT INTO swarm_learning (agent_id, kind, text, state, created_at) "
                             "VALUES (?, 'discovery', ?, 'queued', ?)", (agent["parent_id"], text, taught_at))
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    fact_index.refresh_agent(conn, agent)
    logger.info("swarm_fact_written", fact_id=fact_id, agent_id=agent["id"], origin=source["origin"],
                state="held" if conflict else "live")
    return {"fact_id": fact_id, "state": "held" if conflict else "live", "origin": source["origin"], "scope": scope,
            "conflict": conflict}


def store_owner_fact(conn: sqlite3.Connection, agent: Dict[str, Any], *, title: str, text: str, owner_message_ref: str) -> Dict[str, Any]:
    cut = " ".join(title.split())[:MAX_TITLE_CHARS]
    return _store(conn, agent, cut, "project", False,
                  {"text": text, "origin": "owner", "owner_message_ref": owner_message_ref, "learning_id": None})


def _discard(conn: sqlite3.Connection, agent: Dict[str, Any], fact_id: str) -> None:
    """Remove a fact that never became visible (its card could not be posted): row, file, index."""
    row = conn.execute("SELECT rel_path FROM swarm_facts WHERE id = ?", (fact_id,)).fetchone()
    conn.execute("DELETE FROM swarm_facts WHERE id = ?", (fact_id,))
    if row is not None:
        (memory.memory_dir(Path(agent["repo_dir"]), agent["slug"], agent["memory_scope"]) / row["rel_path"]).unlink(missing_ok=True)
    fact_index.refresh_agent(conn, agent)


async def remember(view: Any, caller: AgentCaller, args: Dict[str, Any]) -> Dict[str, Any]:
    try:
        agent = await spawn.parent_agent(view, caller)
    except spawn.SpawnRefused as exc:
        raise FactRefused(str(exc)) from None
    title, scope, push_up = _validate(args)
    port = thread_port.get()
    owner_text = await _owner_words(port, agent, args)

    def work(conn: sqlite3.Connection) -> Dict[str, Any]:
        return _store(conn, agent, title, scope, push_up, _resolve_source(conn, agent, args, owner_text))

    try:
        done = await body.run_db(work)
    except memory.SwarmFileError as exc:
        raise FactRefused(str(exc)) from None
    except (OSError, sqlite3.Error, db.DatastoreUnreadableError, fact_index.Fts5Missing) as exc:
        logger.warning("swarm_remember_failed", agent_id=agent["id"], error_type=type(exc).__name__)
        raise FactRefused("the fact could not be written; try again") from None
    activity.mark(agent["id"], "learning")
    await asyncio.to_thread(push.notify_agent, agent["id"])
    if push_up and agent["parent_id"] is not None and not done["conflict"]:
        await asyncio.to_thread(push.notify_agent, agent["parent_id"])
    answer = {k: done[k] for k in ("fact_id", "state", "origin", "scope")}
    if done["conflict"] is not None:
        answer["held_for"] = done["conflict"]["title"]
        await _post_conflict_card(agent, done, port)
    return answer


async def _post_conflict_card(agent: Dict[str, Any], done: Dict[str, Any], port: Any) -> None:
    fact_id = done["fact_id"]
    text = (f"{agent['display_name']} wrote a fact that overlaps one you taught: \"{done['conflict']['title']}\". "
            f"approve to accept theirs: it goes live next to yours. answer to keep mine: {agent['display_name']}'s fact is dropped.")
    try:
        if port is None:
            raise RuntimeError("the huddle plugin is off")
        await port.post_card(agent["thread_key"], "question", "memory conflict", text, f"{CONFLICT_PREFIX}{fact_id}")
    except Exception as exc:  # noqa: BLE001
        await body.run_db(lambda c: _discard(c, agent, fact_id))
        logger.warning("swarm_conflict_card_failed", fact_id=fact_id, error_type=type(exc).__name__)
        raise FactRefused("the conflict card could not be posted, so the fact was not kept; try again") from None
    await asyncio.to_thread(push.notify_thread, agent["thread_key"])


def _get(conn: sqlite3.Connection, fact_id: str) -> Dict[str, Any]:
    row = conn.execute("SELECT * FROM swarm_facts WHERE id = ?", (fact_id,)).fetchone()
    agent = store.get_agent(conn, row["agent_id"]) if row is not None else None
    if row is None or agent is None:
        raise FactNotFound(fact_id)
    return {"fact": dict(row), "agent": agent}


def cited_question_ids(conn: sqlite3.Connection, fact_id: str) -> List[int]:
    return [r[0] for r in conn.execute(
        "SELECT DISTINCT r.question_id FROM swarm_receipts r, json_each(r.fact_ids) j WHERE j.value = ? "
        "ORDER BY r.question_id", (fact_id,))]


def kill(conn: sqlite3.Connection, fact_id: str) -> KillResult:
    found = _get(conn, fact_id)
    fact, agent = found["fact"], found["agent"]
    if fact["state"] == "killed":
        raise FactRefused("that fact is already killed")
    with transaction(conn):
        conn.execute("UPDATE swarm_facts SET state = 'killed', killed_at = ? WHERE id = ?", (utc_now(), fact_id))
    (memory.memory_dir(Path(agent["repo_dir"]), agent["slug"], agent["memory_scope"]) / fact["rel_path"]).unlink(missing_ok=True)
    fact_index.refresh_agent(conn, agent)
    logger.info("swarm_fact_killed", fact_id=fact_id, agent_id=agent["id"])
    return KillResult({**fact, "state": "killed"}, cited_question_ids(conn, fact_id))


def decide_conflict(conn: sqlite3.Connection, fact_id: str, accept_theirs: bool) -> str:
    found = _get(conn, fact_id)
    if found["fact"]["state"] != "held":
        raise FactRefused("that fact is not waiting on a conflict decision")
    if not accept_theirs:
        kill(conn, fact_id)
        return "killed"
    with transaction(conn):
        conn.execute("UPDATE swarm_facts SET state = 'live' WHERE id = ? AND state = 'held'", (fact_id,))
    fact_index.refresh_agent(conn, found["agent"])
    return "live"


def list_for_agent(conn: sqlite3.Connection, agent_id: int) -> List[Dict[str, Any]]:
    return [dict(r) for r in conn.execute(
        "SELECT id, agent_id, title, scope, origin, owner_message_ref, taught_at, taught_by_agent_id, state FROM swarm_facts "
        "WHERE agent_id = ? AND state <> 'killed' ORDER BY taught_at DESC, id", (agent_id,))]


def set_scope(conn: sqlite3.Connection, fact_id: str, scope: str) -> Dict[str, Any]:
    if scope not in memory.FACT_SCOPES:
        raise FactRefused("scope must be craft or project")
    found = _get(conn, fact_id)
    fact, agent = found["fact"], found["agent"]
    if fact["state"] == "killed":
        raise FactRefused("that fact is killed")
    mem = memory.memory_dir(Path(agent["repo_dir"]), agent["slug"], agent["memory_scope"])
    read = fact_index._read(mem / fact["rel_path"])
    if read is None:
        raise FactRefused("the fact's file could not be read")
    memory.write_fact(mem, memory.Fact(fact_id, fact["title"], scope, fact["origin"], fact["taught_at"], read[1],
                                       fact["owner_message_ref"]))
    with transaction(conn):
        conn.execute("UPDATE swarm_facts SET scope = ? WHERE id = ?", (scope, fact_id))
    fact_index.refresh_agent(conn, agent)
    return {k: v for k, v in _get(conn, fact_id)["fact"].items() if k not in ("rel_path", "sha256", "killed_at")}
