
from __future__ import annotations

import asyncio
import sqlite3
import time
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional, Set, Tuple

import structlog

from src.core import db
from src.core.swarm import body, store
from src.core.swarm.cards import capacity, dealer, deliver, effects, lease, nudge, port as card_port
from src.cplugs.sdk.cards import CardRefused

logger = structlog.get_logger()

LEASE_S = 600.0
REFRESH_S = 1800.0
WORKING_S = 60.0
STOP_FRESH_S = 60.0
_ERRORS = (body.BodyError, sqlite3.Error, db.DatastoreUnreadableError, OSError, RuntimeError, CardRefused, ValueError, KeyError)


def _epoch(stamp: Optional[str]) -> Optional[float]:
    try:
        return datetime.fromisoformat(stamp).timestamp() if stamp else None
    except ValueError:
        return None


def _holder_facts(conn: sqlite3.Connection, agent_ids: Set[int]) -> Dict[int, Dict[str, Any]]:
    out: Dict[int, Dict[str, Any]] = {}
    for agent_id in agent_ids:
        agent = store.get_agent(conn, agent_id)
        last = conn.execute("SELECT end_reason FROM swarm_wakes WHERE agent_id = ? ORDER BY id DESC LIMIT 1", (agent_id,)).fetchone()
        dead = agent is None or agent["torn_down_at"] is not None or agent["state"] == "torn_down" or (
            agent["state"] == "asleep" and last is not None and last["end_reason"] == "died")
        asks = [_epoch(r["asked_at"]) for r in conn.execute(
            "SELECT k.asked_at FROM swarm_question_askers k JOIN swarm_questions q ON q.id = k.question_id "
            "WHERE k.agent_id = ? AND q.state IN ('routing', 'open', 'reopened')", (agent_id,))]
        out[agent_id] = {"dead": dead, "asleep": not dead and agent["state"] == "asleep", "asked_at": max((a for a in asks if a is not None), default=None)}
    return out


def _last_sign(card: Mapping[str, Any], beat: Optional[lease.Beat]) -> float:
    times = [card["beat_at"], card["held_since"], lease.BOOT_AT, beat.busy_at if beat else None, beat.stop_seen_at if beat else None]
    return max(t for t in times if t is not None)


async def _act(app_state: Any, card_id: int, op: str, args: Mapping[str, Any], *, drop_tells: bool = False) -> bool:
    try:
        result = await card_port.get().act(op, card_id, args, "server")
    except CardRefused as exc:
        logger.info("swarm_card_sweep_refused", card_id=card_id, op=op, code=exc.code)
        return False
    await effects.run(app_state, [e for e in result["effects"] if not (drop_tells and e["kind"] == "tell")])
    return True


async def _leases(app_state: Any, now: float, counts: Dict[str, int]) -> None:
    read = await card_port.get().policy_read("leases", {})
    if now - lease.BOOT_AT >= LEASE_S:
        counts["nudged"] += await nudge.run(app_state, read["leases"], now)
    if not read["leases"]:
        return
    facts = await body.run_db(lambda conn: _holder_facts(conn, {c["holder"] for c in read["leases"]}))
    grace = now - lease.BOOT_AT < LEASE_S
    for card in read["leases"]:
        holder, fact = card["holder"], facts[card["holder"]]
        beat = None if fact["asleep"] else lease.beat(holder)
        stopped = beat is not None and beat.stopped and now - (beat.stop_seen_at or 0.0) <= STOP_FRESH_S
        asking = fact["asked_at"] is not None and fact["asked_at"] >= (card["held_since"] or 0.0)
        if not fact["dead"] and (asking or stopped):
            if asking:
                lease.stop(holder, now)
            continue
        dealing_on = bool(read["dealing"].get(card["list_key"]))
        quiet = now - _last_sign(card, beat)
        if fact["dead"] or quiet > LEASE_S:
            if card["mark"] == "stalled" and not dealing_on:
                continue
            if grace and fact["dead"]:
                continue
            why = "its body is dead" if fact["dead"] else f"no sign of life for {int(quiet)} s"
            if await _act(app_state, card["id"], "lapse", {"reason": why, "seen": [card["beat_at"], card["held_since"]]}, drop_tells=fact["dead"]):
                counts["lapsed" if dealing_on else "stalled"] += 1
            continue
        since = max(t for t in (card["beat_at"], card["started_at"], card["held_since"]) if t is not None)
        working = beat is not None and beat.busy_at is not None and now - beat.busy_at <= WORKING_S
        asked = card["refresh_asked_at"]
        if not grace and working and now - since >= REFRESH_S and (asked is None or now - asked >= REFRESH_S):
            if await _act(app_state, card["id"], "asked_refresh", {}):
                counts["refreshed"] += 1


async def _deals(now: float, counts: Dict[str, int]) -> None:
    port = card_port.get()
    for row in (await port.policy_read("deals", {}))["deals"]:
        key = row["project_key"]
        if dealer.armed(key):
            continue
        waited = now - (row["requested_at"] if not row["attempts"] else row["delivered_at"] or row["requested_at"])
        if row["state"] == "waiting" and waited >= (dealer.RETRY_S if row["attempts"] else dealer.DEAL_DEBOUNCE_S):
            dealer.kick(key, due=True)
            counts["rearmed"] += 1
        elif row["state"] == "delivered" and now - (row["delivered_at"] or row["requested_at"]) >= dealer.RETRY_S:
            await port.policy("deal_state", {"project_key": key, "state": "waiting", "only_from": ["delivered"]}, "server")
            dealer.kick(key, due=True)
            counts["resent"] += 1


async def _slots(app_state: Any, counts: Dict[str, int]) -> None:
    port = card_port.get()
    by_project: Dict[str, List[Mapping[str, Any]]] = {}
    for card in (await port.policy_read("waiting", {}))["waiting"]:
        by_project.setdefault(card["list_key"], []).append(card)
    for key, cards in by_project.items():
        project_id = int(key) if key.isdigit() else None
        grants = await capacity.grants_by_scope()

        def judge(conn: sqlite3.Connection) -> Optional[Tuple[Mapping[str, Any], bool]]:
            for card in cards:
                agent = store.get_agent(conn, card["dealt_to"])
                if agent is None or agent["torn_down_at"] is not None:
                    return card, True
                if deliver.slot_refusal(conn, agent, project_id, grants) is None:
                    return card, False
            return None

        verdict = await body.run_db(judge)
        if verdict is None:
            continue
        if await _act(app_state, verdict[0]["id"], "complete_slot", {}, drop_tells=verdict[1]):
            counts["slotted"] += 1


async def run(app_state: Any, now: Optional[float] = None) -> Dict[str, int]:
    counts = {"lapsed": 0, "stalled": 0, "refreshed": 0, "rearmed": 0, "resent": 0, "slotted": 0, "nudged": 0}
    try:
        card_port.get()
    except card_port.CardsOff:
        return counts
    dealer.ensure_bound(app_state)
    await asyncio.to_thread(capacity.sample, time.monotonic())
    stamp = time.time() if now is None else now
    for name, job in (("leases", lambda: _leases(app_state, stamp, counts)), ("deals", lambda: _deals(stamp, counts)),
                      ("slots", lambda: _slots(app_state, counts))):
        try:
            await job()
        except _ERRORS as exc:
            logger.warning("swarm_card_sweep_job_failed", job=name, error_type=type(exc).__name__)
    if any(counts.values()):
        logger.info("swarm_card_sweep", **counts)
    return counts
