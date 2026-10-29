
from __future__ import annotations

import asyncio
import sqlite3
import time
from collections import deque
from contextlib import closing
from typing import Any, Deque, Dict, Iterable, List, Optional, Tuple

import structlog

from src.core import db
from src.core.notifications import contracts
from src.core.notifications.sources import common as notify_common
from src.core.swarm import owner_wait, push, settings as swarm_settings, store, thread_port
from src.core.swarm.names import shown_name

logger = structlog.get_logger()

ALERT_PREFIX = "alert:"
FLASH_REF = "alert:flash:"
IMMEDIATE_REF = "alert:immediate:"
DEAD_PREFIX = "dead:"
WAKE_FAILED_PREFIX = "wake_failed:"
WAKE_CARD_PREFIXES: Tuple[str, ...] = ("wake_refused:", WAKE_FAILED_PREFIX)
IMMEDIATE_PREFIXES: Tuple[str, ...] = ("wake_refused:", "wake_failed:", "stuck:", DEAD_PREFIX, IMMEDIATE_REF)
ACK_PREFIXES: Tuple[str, ...] = (ALERT_PREFIX, DEAD_PREFIX)
RUNGS = ("routine", "priority", "immediate", "flash")
ROSTER_REASON_CHARS = 160
HOUR_S = 3600.0
TYPE_PUSH = "swarm.alert"
TYPE_TEXT = "swarm.flash"


def rung_of(kind: str, swarm_ref: str) -> Optional[str]:
    if swarm_ref.startswith(FLASH_REF):
        return "flash"
    if swarm_ref.startswith(IMMEDIATE_PREFIXES):
        return "immediate"
    if kind in ("question", "waiting"):
        return "priority"
    if kind in ("done", "info"):
        return "routine"
    return None


def derive(cards: Iterable[Dict[str, Any]], agents: Iterable[Dict[str, Any]],
           live: Optional[Dict[int, Any]] = None) -> Dict[int, Dict[str, Optional[str]]]:
    from src.core.mcp.tools import redact_text

    agents = list(agents)
    by_thread = {a["thread_key"]: a["id"] for a in agents}
    alive = {a["id"] for a in agents}
    best: Dict[int, Tuple[int, str]] = {}
    for card in cards:
        agent_id = by_thread.get(card["thread_key"])
        rung = rung_of(card["kind"], card["swarm_ref"])
        if agent_id is None or rung is None or not owner_wait.asks_owner(card["kind"], card["swarm_ref"]):
            continue
        if owner_wait.subject_agent(card["swarm_ref"]) is not None and not owner_wait.card_counts(card["swarm_ref"], {}, alive):
            continue
        if live is not None and owner_wait.question_id(card["swarm_ref"]) is not None and not owner_wait.card_counts(card["swarm_ref"], live, alive):
            continue
        rank = RUNGS.index(rung)
        if agent_id not in best or rank > best[agent_id][0]:
            said = card["text"] if card["swarm_ref"].startswith(ALERT_PREFIX) else (card["title"] or card["text"])
            best[agent_id] = (rank, redact_text(" ".join(said.split()))[:ROSTER_REASON_CHARS])
    return {a["id"]: ({"alert": RUNGS[best[a["id"]][0]], "alert_reason": best[a["id"]][1]} if a["id"] in best
                      else {"alert": None, "alert_reason": None}) for a in agents}


class _Limits:

    def __init__(self) -> None:
        self.clock = time.monotonic
        self._stamps: Dict[Tuple[str, Optional[int]], Deque[float]] = {}

    def take(self, kind: str, agent_id: int, per_agent: int, per_swarm: int) -> bool:
        now = self.clock()
        mine = self._stamps.setdefault((kind, agent_id), deque())
        swarm = self._stamps.setdefault((kind, None), deque())
        for window in (mine, swarm):
            while window and now - window[0] >= HOUR_S:
                window.popleft()
        if len(mine) >= per_agent or len(swarm) >= per_swarm:
            return False
        mine.append(now)
        swarm.append(now)
        return True

    def reset(self) -> None:
        self._stamps.clear()


LIMITS = _Limits()


def _agent_for_thread(thread_key: str) -> Optional[Dict[str, Any]]:
    from src.config import settings as app_settings

    try:
        with closing(db.connect(db.db_path_for(app_settings.get_state_dir()), create=False)) as conn:
            agent = store.get_agent_by_thread_key(conn, thread_key)
            if agent is not None:
                body = conn.execute("SELECT session_uuid FROM sessions WHERE id = ?", (agent.get("session_row_id"),)).fetchone()
                agent["body_session_uuid"] = (body[0] or None) if body else None
            return agent
    except (db.DatastoreUnreadableError, sqlite3.Error, OSError) as exc:
        logger.warning("swarm_alert_agent_unreadable", error_type=type(exc).__name__)
        return None


def announce(thread_key: str, swarm_ref: str) -> None:
    flash = swarm_ref.startswith(FLASH_REF)
    if not flash and not swarm_ref.startswith(IMMEDIATE_PREFIXES):
        return
    agent = _agent_for_thread(thread_key)
    if agent is None:
        return
    if swarm_ref.startswith(IMMEDIATE_REF):
        cfg = swarm_settings.read_current()
        if not LIMITS.take("push", agent["id"], cfg.flash_per_agent_per_hour, cfg.flash_per_swarm_per_hour):
            logger.info("swarm_alert_push_limited", agent_id=agent["id"])
            return
    type_id = TYPE_TEXT if flash else TYPE_PUSH
    contracts.emit(contracts.NotifyEvent(
        type_id=type_id, kind="swarm", title=notify_common.type_title(type_id), ts=notify_common.now(),
        session_ref=shown_name(agent), session_uuid=agent.get("body_session_uuid"), severity=contracts.SEVERITY_ERROR,
        instance_key=swarm_ref, open_item=True))
    logger.info("swarm_alert_announced", agent_id=agent["id"], type_id=type_id)


def episode_prefix(swarm_ref: str) -> str:
    if swarm_ref.startswith(WAKE_FAILED_PREFIX):
        return swarm_ref.rpartition(":")[0] + ":"
    return swarm_ref


class AlertingPort:

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    @property
    def inner(self) -> Any:
        return self._inner

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def post_card(self, thread_key: str, kind: str, title: str, text: str, swarm_ref: str) -> int:
        if swarm_ref.startswith(IMMEDIATE_PREFIXES) or swarm_ref.startswith(FLASH_REF):
            episode = episode_prefix(swarm_ref)
            for card in await self._inner.open_cards():
                if card["thread_key"] == thread_key and card["swarm_ref"].startswith(episode):
                    return int(card["id"])
        item_id = await self._inner.post_card(thread_key, kind, title, text, swarm_ref)
        await asyncio.to_thread(announce, thread_key, swarm_ref)
        return item_id


async def roster_alerts(agents: List[Dict[str, Any]], live: Optional[Dict[int, Any]] = None) -> Dict[int, Dict[str, Optional[str]]]:
    port = thread_port.get()
    cards = await port.open_cards() if port is not None else []
    return derive(cards, agents, live)


async def post_dead_card(agent: Dict[str, Any], wake_id: int) -> None:
    port = thread_port.get()
    if port is None:
        return
    ref = f"{DEAD_PREFIX}{agent['id']}:{wake_id}"
    text = f"{shown_name(agent)} stopped while it still had work open. Wake it to carry on."
    try:
        await port.post_card(agent["thread_key"], "info", "body died", text, ref)
    except Exception as exc:  # noqa: BLE001
        logger.warning("swarm_dead_card_failed", agent_id=agent["id"], error_type=type(exc).__name__)


async def sweep(app_state: Any) -> int:
    from src.core.swarm import body

    try:
        awake = await body.run_db(lambda c: [a for a in store.list_agents(c) if a["state"] == "awake"])
    except (sqlite3.Error, db.DatastoreUnreadableError, OSError) as exc:
        logger.warning("swarm_alert_sweep_unreadable", error_type=type(exc).__name__)
        return 0
    for agent in awake:
        try:
            await body.detect_death(app_state, agent)
        except (sqlite3.Error, db.DatastoreUnreadableError, OSError, RuntimeError) as exc:
            logger.warning("swarm_alert_sweep_agent_failed", agent_id=agent["id"], error_type=type(exc).__name__)
    await settle_stale()
    return len(awake)


def _close_questions(conn: sqlite3.Connection) -> List[int]:
    stale = owner_wait.stale_questions(conn)
    for qid in stale:
        conn.execute("UPDATE swarm_questions SET state = 'closed' WHERE id = ? AND state IN ('routing', 'open', 'reopened')", (qid,))
    conn.commit()
    return stale


async def settle_stale() -> int:
    from src.core.swarm import body

    port = thread_port.get()
    if port is None:
        return 0
    try:
        closed = await body.run_db(_close_questions)
        agents = await body.run_db(store.list_agents)
        alive = {a["id"] for a in agents}
        awake = {a["id"] for a in agents if a["state"] == "awake"}
        refs = [f"{owner_wait.QUESTION_REF}{qid}" for qid in closed]
        for c in await port.open_cards():
            subject = owner_wait.subject_agent(c["swarm_ref"])
            if subject is not None and (not owner_wait.card_counts(c["swarm_ref"], {}, alive)
                                        or (subject in awake and c["swarm_ref"].startswith(WAKE_CARD_PREFIXES))):
                refs.append(c["swarm_ref"])
        for ref in dict.fromkeys(refs):
            await port.settle_cards(ref, resolve=True)
    except (sqlite3.Error, db.DatastoreUnreadableError, OSError) as exc:
        logger.warning("swarm_stale_settle_failed", error_type=type(exc).__name__)
        return 0
    if closed or refs:
        logger.info("swarm_stale_settled", questions=len(closed), cards=len(refs))
    return len(refs)
