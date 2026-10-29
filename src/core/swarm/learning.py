
from __future__ import annotations

import asyncio
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import structlog

from src.core import db
from src.core.db import transaction
from src.core.swarm import fact_life, push, settings, store
from src.core.trail_entry import utc_now

logger = structlog.get_logger()

SHOWN_CHARS = 1500
_KIND_LABEL = {
    "sealed_answer": "the owner answered a question on the chain",
    "skip_level": "the owner wrote to one of your children",
    "discovery": "a child agent pushed up what it found",
    "conflict": "the owner decided a conflict",
}


def queue_skip_level(conn: sqlite3.Connection, child: Dict[str, Any], owner_message_ref: str, text: str) -> Optional[int]:
    parent = store.get_agent(conn, child["parent_id"]) if child.get("parent_id") is not None else None
    if parent is None or parent["torn_down_at"] is not None or not text.strip() or not owner_message_ref.startswith("huddle:msg:"):
        return None
    with transaction(conn):
        if conn.execute("SELECT 1 FROM swarm_learning WHERE agent_id = ? AND kind = 'skip_level' AND owner_message_ref = ?",
                        (parent["id"], owner_message_ref)).fetchone():
            return None
        item = int(conn.execute(
            "INSERT INTO swarm_learning (agent_id, kind, text, owner_message_ref, state, created_at) "
            "VALUES (?, 'skip_level', ?, ?, 'queued', ?)", (parent["id"], f"to {child['display_name']}: {text.strip()}",
                                                           owner_message_ref, utc_now())).lastrowid)
    logger.info("swarm_skip_level_queued", item=item, child_id=child["id"], parent_id=parent["id"])
    push.notify_agent(parent["id"])
    return item


def queued(conn: sqlite3.Connection, agent_id: int) -> List[Dict[str, Any]]:
    return [dict(r) for r in conn.execute(
        "SELECT id, kind, text, owner_message_ref, question_id, created_at FROM swarm_learning "
        "WHERE agent_id = ? AND state = 'queued' ORDER BY id", (agent_id,))]


def mark_delivered(conn: sqlite3.Connection, ids: List[int], wake_id: int) -> None:
    if not ids:
        return
    with transaction(conn):
        conn.execute(f"UPDATE swarm_learning SET state = 'delivered', delivered_wake_id = ? WHERE state = 'queued' "
                     f"AND id IN ({','.join('?' * len(ids))})", (wake_id, *ids))


QUOTE = "  | "


_CONTROL = re.compile("[\x00-\x1f\x7f-\x9f\u2028\u2029]+")


def one_line(text: Any) -> str:
    return " ".join(_CONTROL.sub(" ", str(text)).split())


def _cut(text: str) -> str:
    return text if len(text) <= SHOWN_CHARS else text[:SHOWN_CHARS - 3] + "..."


def render(items: List[Dict[str, Any]]) -> List[str]:
    if not items:
        return []
    lines = ["", f"learning inbox ({len(items)} waiting). Stamp an item with swarm_remember "
             "(title, scope craft or project, learning_id) ONLY if it meets the memory bar; the server copies the text, so the "
             "words stay exactly as written. Leave every other item. " + fact_life.MEMORY_BAR]
    for item in items:
        who = _KIND_LABEL.get(item["kind"], item["kind"])
        lines += [f"- item {item['id']} ({who}):", *(QUOTE + ln for ln in _cut(item["text"]).splitlines() or [""])]
    return lines


def due(conn: sqlite3.Connection, now: datetime, batch_size: int, max_age_hours: int) -> List[int]:
    cutoff = (now - timedelta(hours=max_age_hours)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return [r[0] for r in conn.execute(
        "SELECT agent_id FROM swarm_learning WHERE state = 'queued' GROUP BY agent_id "
        "HAVING COUNT(*) >= ? OR MIN(created_at) <= ? ORDER BY agent_id", (batch_size, cutoff))]


async def _wake_for_learning(app_state: Any, agent_id: int) -> bool:
    from src.core.swarm import body, delivery

    agent = await body.run_db(lambda c: store.get_agent(c, agent_id))
    if agent is None or agent["torn_down_at"] is not None:
        return False
    if agent["state"] == "asleep":
        return (await body.wake(app_state, agent_id, "learning", "data")).started
    if agent["state"] != "awake":
        return False
    items = await body.run_db(lambda c: queued(c, agent_id))
    if not items:
        return False
    text = "\n".join(["Your learning inbox has items waiting."] + render(items))
    outcome = await delivery.deliver_text(app_state, agent_id, text, source="learning", authority="data",
                                          source_ref=f"learning:{items[-1]['id']}")
    if outcome.startswith("refused:"):
        return False
    wake = await body.run_db(lambda c: store.get_open_wake(c, agent_id))
    if wake is not None:
        await body.run_db(lambda c: mark_delivered(c, [i["id"] for i in items], wake["id"]))
    return True


async def sweep(app_state: Any) -> int:
    from src.core.swarm import body

    try:
        cfg = await asyncio.to_thread(settings.read_current)
        tiers = await body.run_db(lambda c: due(c, datetime.now(timezone.utc), cfg.learning_batch_size, cfg.learning_max_age_hours))
    except (sqlite3.Error, db.DatastoreUnreadableError, OSError) as exc:
        logger.warning("swarm_learning_sweep_unreadable", error_type=type(exc).__name__)
        return 0
    woken = 0
    for agent_id in tiers:
        try:
            woken += 1 if await _wake_for_learning(app_state, agent_id) else 0
        except (body.BodyError, sqlite3.Error, db.DatastoreUnreadableError, OSError) as exc:
            logger.warning("swarm_learning_wake_failed", agent_id=agent_id, error_type=type(exc).__name__, error=str(exc)[:200])
    return woken
