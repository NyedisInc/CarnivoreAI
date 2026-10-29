
from __future__ import annotations

import asyncio
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import structlog

from src.core import db
from src.core.db import transaction
from src.core.mcp.caller import AgentCaller
from src.core.swarm import activity, author_path, body, fact_index, memory, push, settings, spawn, store, stream, thread_port
from src.core.swarm.cards import phone, port as card_port
from src.core.swarm.question_events import learned_events, question_events
from src.core.trail_entry import utc_now
from src.core.swarm.names import shown_name
from src.cplugs.sdk.swarm import SwarmError

logger = structlog.get_logger()

JOIN_COVERAGE = 0.8
MAX_QUESTION_CHARS = 2000
MAX_SUMMARY_CHARS = 300
MAX_TASK_CHARS = author_path.TASK_CHARS
QUESTION_PREFIX = "question:"
WITHDRAWN_PREFIX = "withdrawn:"
ALL_THREAD = "all"
OWNER_TALK = ("owner_chat", "wake_prompt")
OWNER_TALK_MARKS = ",".join("?" * len(OWNER_TALK))
JOINABLE = ("routing", "open", "reopened")
WALKING = ("routing", "reopened")
_CHAIN_LIMIT = 10
_WAKE_ERRORS = (body.BodyError, sqlite3.Error, db.DatastoreUnreadableError, OSError, RuntimeError)
_locks: Dict[int, asyncio.Lock] = {}


SUMMARY_REQUIRED = "summary is required: one plain sentence the owner can answer without reading code"


class QuestionRefused(ValueError):
    pass


@dataclass(frozen=True)
class Step:

    kind: str
    question: Dict[str, Any]
    tier: Optional[Dict[str, Any]] = None
    coverage: Optional[float] = None
    best_doc: Optional[str] = None
    askers: Optional[List[Dict[str, Any]]] = None


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _parse(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def _company_agent_of(conn: sqlite3.Connection, tiers: List[Dict[str, Any]], seen: set) -> Optional[Dict[str, Any]]:
    company_id = next((t["company_id"] for t in tiers if t.get("company_id") is not None), None)
    if company_id is None:
        project_id = next((t["project_id"] for t in tiers if t.get("project_id") is not None), None)
        found = conn.execute("SELECT company_id FROM projects WHERE id = ?", (project_id,)).fetchone() if project_id is not None else None
        company_id = found[0] if found else None
    if company_id is None:
        return None
    row = conn.execute("SELECT id FROM swarm_agents WHERE rank = 'company' AND company_id = ? AND torn_down_at IS NULL", (company_id,)).fetchone()
    return store.get_agent(conn, row[0]) if row is not None and row[0] not in seen else None


def chain_for(conn: sqlite3.Connection, asker: Dict[str, Any]) -> List[Dict[str, Any]]:
    chain: List[Dict[str, Any]] = []
    seen = {asker["id"]}
    current = asker
    while current["parent_id"] is not None and len(chain) < _CHAIN_LIMIT:
        current = store.get_agent(conn, current["parent_id"])
        if current is None or current["id"] in seen:
            break
        seen.add(current["id"])
        if current["torn_down_at"] is None:
            chain.append(current)
    if not any(t["rank"] == "company" for t in chain):
        company = _company_agent_of(conn, [asker, *chain], seen)
        if company is not None:
            chain.append(company)
    if not any(t["rank"] == "alpha" for t in chain):
        alpha = next((a for a in store.list_agents(conn) if a["rank"] == "alpha" and a["id"] not in seen), None)
        if alpha is not None:
            chain.append(alpha)
    return chain


def askers_of(conn: sqlite3.Connection, question_id: int) -> List[Dict[str, Any]]:
    return [a for a in (store.get_agent(conn, r[0]) for r in conn.execute(
        "SELECT agent_id FROM swarm_question_askers WHERE question_id = ? ORDER BY asked_at, agent_id", (question_id,)))
        if a is not None]


def _join_target(conn: sqlite3.Connection, text: str) -> Optional[int]:
    terms = fact_index.query_terms(text)
    if not terms:
        return None
    found: Dict[int, int] = {}
    for term in terms:
        for (qid,) in conn.execute("SELECT question_id FROM swarm_question_fts WHERE swarm_question_fts MATCH ?",
                                   (f'"{term}"',)):
            found[int(qid)] = found.get(int(qid), 0) + 1
    marks = ",".join("?" * len(JOINABLE))
    live = {r[0] for r in conn.execute(
        f"SELECT id FROM swarm_questions WHERE state IN ({marks}) AND id IN ({','.join('?' * len(found))})",
        (*JOINABLE, *found))} if found else set()
    ranked = sorted(((n / len(terms), -qid, qid) for qid, n in found.items() if qid in live), reverse=True)
    return ranked[0][2] if ranked and ranked[0][0] >= JOIN_COVERAGE else None


def _create_or_join(conn: sqlite3.Connection, agent: Dict[str, Any], text: str, summary: Optional[str] = None,
                    task: Optional[str] = None, *, joinable: bool = True) -> Dict[str, Any]:
    now = utc_now()
    path = json.dumps(author_path.path_for_agent(conn, agent))
    with transaction(conn):
        target = _join_target(conn, text) if joinable else None
        if target is not None:
            conn.execute("INSERT OR IGNORE INTO swarm_question_askers (question_id, agent_id, asked_at, author_path) VALUES (?, ?, ?, ?)",
                         (target, agent["id"], now, path))
            return {"question_id": target, "joined": True}
        qid = int(conn.execute("INSERT INTO swarm_questions (text, state, created_at, summary, task) VALUES (?, 'routing', ?, ?, ?)",
                               (text, now, summary, task)).lastrowid)
        conn.execute("INSERT INTO swarm_question_fts (question_id, text) VALUES (?, ?)", (qid, text))
        conn.execute("INSERT INTO swarm_question_askers (question_id, agent_id, asked_at, author_path) VALUES (?, ?, ?, ?)",
                     (qid, agent["id"], now, path))
    return {"question_id": qid, "joined": False}


def _question_text(args: Dict[str, Any]) -> str:
    text = args.get("question")
    if not isinstance(text, str) or not text.strip():
        raise QuestionRefused("question is required")
    text = text.strip()
    if len(text) > MAX_QUESTION_CHARS:
        raise QuestionRefused(f"the question must be at most {MAX_QUESTION_CHARS} characters")
    try:
        memory.refuse_secrets(text, "question")
    except memory.SwarmFileError as exc:
        raise QuestionRefused(str(exc)) from None
    return text


def _plain_line(args: Dict[str, Any], key: str, cap: int) -> Optional[str]:
    value = args.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise QuestionRefused(f"{key} must be text")
    value = " ".join(value.split())
    if len(value) > cap:
        raise QuestionRefused(f"the {key} must be at most {cap} characters")
    try:
        memory.refuse_secrets(value, key)
    except memory.SwarmFileError as exc:
        raise QuestionRefused(str(exc)) from None
    return value or None


async def _derived_task(agent: Dict[str, Any]) -> str:
    try:
        held = await card_port.get().cards(holder=agent["id"], columns=["in_progress"])
    except (card_port.CardsOff, sqlite3.Error, db.DatastoreUnreadableError, OSError) as exc:
        logger.info("swarm_ask_task_from_job", agent_id=agent["id"], error_type=type(exc).__name__)
        held = []
    title = next((str(c.get("title") or "").strip() for c in held if str(c.get("title") or "").strip()), "")
    return author_path.cut_at_word(title or agent.get("job") or "", MAX_TASK_CHARS)


async def caller_agent(view: Any, caller: AgentCaller) -> Dict[str, Any]:
    try:
        return await spawn.parent_agent(view, caller)
    except spawn.SpawnRefused as exc:
        raise QuestionRefused(str(exc)) from None


async def ask(view: Any, caller: AgentCaller, args: Dict[str, Any]) -> Dict[str, Any]:
    agent = await caller_agent(view, caller)
    text = _question_text(args)
    summary = _plain_line(args, "summary", MAX_SUMMARY_CHARS)
    if summary is None:
        raise QuestionRefused(SUMMARY_REQUIRED)
    refusal = author_path.summary_refusal(summary)
    if refusal:
        raise QuestionRefused(refusal)
    task = _plain_line(args, "task", MAX_TASK_CHARS) or await _derived_task(agent)
    port = thread_port.get()
    if port is None:
        raise QuestionRefused("the huddle plugin is off, so a question has nowhere to go")
    form = args.get("questions")
    if form is not None:
        try:
            flat = await port.check_form(form)
            memory.refuse_secrets(flat, "questions")
        except (SwarmError, memory.SwarmFileError) as exc:
            raise QuestionRefused(str(exc)) from None
        text = f"{text}\n\n{flat}"
    try:
        made = await body.run_db(lambda c: _create_or_join(c, agent, text, summary, task, joinable=form is None))
        if form is not None:
            await _stage_form(port, made["question_id"], form)
        if not made["joined"]:
            await advance(view.app.state, made["question_id"])
        state = await body.run_db(lambda c: c.execute("SELECT state FROM swarm_questions WHERE id = ?",
                                                      (made["question_id"],)).fetchone()[0])
    except (sqlite3.Error, db.DatastoreUnreadableError, fact_index.Fts5Missing) as exc:
        logger.warning("swarm_ask_failed", agent_id=agent["id"], error_type=type(exc).__name__)
        raise QuestionRefused("the question could not be saved; try again") from None
    await asyncio.to_thread(push.notify_agent, agent["id"])
    logger.info("swarm_asked", question_id=made["question_id"], agent_id=agent["id"], joined=made["joined"])
    return {"question_id": made["question_id"], "state": state, "joined": made["joined"]}


async def _stage_form(port: Any, question_id: int, form: Any) -> None:
    try:
        await port.stage_form(question_id, form)
    except (SwarmError, OSError) as exc:
        logger.warning("swarm_ask_form_not_staged", question_id=question_id, error_type=type(exc).__name__)


def _add_hop(conn: sqlite3.Connection, question_id: int, agent_id: int, coverage: Optional[float], outcome: str,
             at: Optional[str] = None) -> None:
    conn.execute("INSERT INTO swarm_question_hops (question_id, agent_id, coverage, outcome, at) VALUES (?, ?, ?, ?, ?)",
                 (question_id, agent_id, coverage, outcome, at or utc_now()))


def _next_step(conn: sqlite3.Connection, question_id: int, now: datetime) -> Optional[Step]:
    q = conn.execute("SELECT * FROM swarm_questions WHERE id = ?", (question_id,)).fetchone()
    if q is None or q["state"] not in WALKING:
        return None
    hops = conn.execute("SELECT * FROM swarm_question_hops WHERE question_id = ? ORDER BY id", (question_id,)).fetchall()
    if hops and hops[-1]["outcome"] == "timeout" and _parse(hops[-1]["at"]) > now:
        return None
    askers = askers_of(conn, question_id)
    if not askers:
        return None
    done = {h["agent_id"] for h in hops}
    min_coverage = settings.read_current().wake_hit_min_coverage
    for tier in chain_for(conn, askers[0]):
        if tier["id"] in done:
            continue
        hit = fact_index.best(conn, tier["id"], q["text"], min_coverage)
        return Step("hop", dict(q), tier, hit.coverage if hit else None, hit.doc_key if hit is not None and hit.hit else None,
                    askers)
    return Step("card", dict(q), askers=askers)


def hop_text(step: Step) -> str:
    names = ", ".join(shown_name(a) for a in step.askers or [])
    qid = step.question["id"]
    where = f"Your best match is {step.best_doc}. " if step.best_doc and step.best_doc.startswith("fact:") else ""
    return (f'Question {qid} from {names}, routed to you as the next tier up its chain (every tier is asked before the owner):'
            f'\n\n"{step.question["text"]}"\n\n'
            f"{where}Answer with swarm_answer (question_id {qid}, text, and the ids of YOUR stored facts you relied on in "
            f"fact_ids), or call swarm_pass (question_id {qid}) when you cannot answer well. A guess is worse than a pass.")


async def tell(app_state: Any, agent_id: int, text: str, *, source: str, authority: str, ref: str, reason: str,
               owner_message_ref: Optional[str] = None) -> bool:
    from src.core.swarm import delivery

    try:
        outcome = await delivery.deliver_text(app_state, agent_id, text, source=source, authority=authority,
                                              source_ref=ref, owner_message_ref=owner_message_ref)
        if outcome == "refused:asleep":
            await body.wake(app_state, agent_id, reason, authority, orders=text, owner_message_ref=owner_message_ref)
            return True
        return not outcome.startswith("refused:")
    except _WAKE_ERRORS as exc:
        logger.warning("swarm_tell_failed", agent_id=agent_id, ref=ref, error_type=type(exc).__name__, error=str(exc)[:200])
        return False


def push_text(step: Step) -> str:
    q = step.question
    names = ", ".join(shown_name(a) for a in step.askers or []) or "an agent"
    summary = q.get("summary") or author_path.summary_fallback(q["text"])
    task = q.get("task")
    return f"{names}: {summary}" + (f" (task: {task})" if task else "")


def owner_thread(conn: sqlite3.Connection, askers: List[Dict[str, Any]], relayers: List[int]) -> str:
    candidates: Dict[int, Dict[str, Any]] = {}
    for asker in askers:
        candidates.setdefault(asker["id"], asker)
        for tier in chain_for(conn, asker):
            candidates.setdefault(tier["id"], tier)
    live_relayers = [a for a in (store.get_agent(conn, rid) for rid in relayers) if a is not None and a["torn_down_at"] is None]
    for relayer in live_relayers:
        candidates.setdefault(relayer["id"], relayer)
    if not candidates:
        return ALL_THREAD
    marks = ",".join("?" * len(candidates))
    row = conn.execute(f"SELECT agent_id FROM swarm_deliveries WHERE authority = 'owner' AND source IN ({OWNER_TALK_MARKS}) "
                       f"AND agent_id IN ({marks}) ORDER BY delivered_at DESC, id DESC LIMIT 1",
                       (*OWNER_TALK, *candidates)).fetchone()
    if row is not None:
        return str(candidates[row[0]]["thread_key"])
    return str(live_relayers[0]["thread_key"]) if live_relayers else ALL_THREAD


async def _relayers(askers: List[Dict[str, Any]]) -> List[int]:
    out: List[int] = []
    for asker in askers:
        try:
            held = await card_port.get().cards(holder=asker["id"], columns=["in_progress"])
        except (card_port.CardsOff, sqlite3.Error, db.DatastoreUnreadableError, OSError) as exc:
            logger.info("swarm_question_relayer_unread", agent_id=asker["id"], error_type=type(exc).__name__)
            continue
        for card in held:
            origin = card.get("origin") or {}
            ref = str(origin.get("ref") or "")
            if origin.get("kind") == "agent" and ref.isdigit() and int(ref) not in out and int(ref) != asker["id"]:
                out.append(int(ref))
    return out


async def _post_nothing_hit(app_state: Any, step: Step) -> None:
    port = thread_port.get()
    qid = step.question["id"]
    if port is None:
        logger.warning("swarm_question_card_no_port", question_id=qid)
        return
    text = push_text(step)
    relayers = await _relayers(step.askers or [])
    thread = await body.run_db(lambda c: owner_thread(c, step.askers or [], relayers))
    try:
        item = await port.post_card(thread, "question", "a question for you", text, f"{QUESTION_PREFIX}{qid}")
    except Exception as exc:  # noqa: BLE001
        logger.warning("swarm_question_card_failed", question_id=qid, error_type=type(exc).__name__)
        return
    opened = await body.run_db(lambda c: c.execute("UPDATE swarm_questions SET state = 'open', card_ref = ? WHERE id = ? AND "
                                                   "state IN ('routing','reopened')", (str(item), qid)).rowcount)
    await asyncio.to_thread(push.notify_thread, thread)
    for asker in step.askers or []:
        activity.mark(asker["id"], "escalating")
    logger.info("swarm_question_open", question_id=qid, thread=thread)
    if opened == 1:
        await phone.question_climbed(app_state, int(item), qid, push_text(step))


async def advance(app_state: Any, question_id: int) -> None:
    lock = _locks.setdefault(question_id, asyncio.Lock())
    async with lock:
        while True:
            step = await body.run_db(lambda c: _next_step(c, question_id, datetime.now(timezone.utc)))
            if step is None:
                return
            if step.kind == "card":
                await _post_nothing_hit(app_state, step)
                break
            woken = await tell(app_state, step.tier["id"], hop_text(step), source="swarm_question", authority="data",
                               ref=f"{QUESTION_PREFIX}{question_id}", reason="question")
            deadline = _iso(datetime.now(timezone.utc) + timedelta(minutes=settings.read_current().hop_timeout_minutes))
            await body.run_db(lambda c: _add_hop(c, question_id, step.tier["id"], step.coverage,
                                                 "timeout" if woken else "skipped", deadline if woken else None))
            await asyncio.to_thread(push.notify_agent, step.tier["id"])
            if woken:
                break


async def sweep(app_state: Any) -> int:
    try:
        ids = await body.run_db(lambda c: [r[0] for r in c.execute(
            "SELECT id FROM swarm_questions WHERE state IN ('routing','reopened') ORDER BY id")])
    except (sqlite3.Error, db.DatastoreUnreadableError, OSError) as exc:
        logger.warning("swarm_sweep_unreadable", error_type=type(exc).__name__)
        return 0
    for qid in ids:
        try:
            await advance(app_state, qid)
        except (sqlite3.Error, db.DatastoreUnreadableError, OSError, fact_index.Fts5Missing) as exc:
            logger.warning("swarm_sweep_question_failed", question_id=qid, error_type=type(exc).__name__)
    return len(ids)


def list_questions(conn: sqlite3.Connection, state: Optional[str] = None) -> List[Dict[str, Any]]:
    sql = "SELECT * FROM swarm_questions" + (" WHERE state = ?" if state else "") + " ORDER BY id DESC"
    out = []
    for q in conn.execute(sql, (state,) if state else ()).fetchall():
        receipt = conn.execute("SELECT kind, fact_ids, rendered FROM swarm_receipts WHERE question_id = ? ORDER BY id DESC LIMIT 1",
                               (q["id"],)).fetchone()
        out.append({**{k: q[k] for k in ("id", "text", "state", "card_ref", "answer_text", "answered_by", "created_at",
                                         "answered_at")},
                    "askers": [r[0] for r in conn.execute(
                        "SELECT agent_id FROM swarm_question_askers WHERE question_id = ? ORDER BY asked_at, agent_id", (q["id"],))],
                    "receipt": None if receipt is None else {"kind": receipt["kind"], "rendered": receipt["rendered"],
                                                            "fact_ids": json.loads(receipt["fact_ids"])}})
    return out


for _source in (question_events, learned_events):
    if _source not in stream.EXTRA_SOURCES:
        stream.EXTRA_SOURCES.append(_source)
