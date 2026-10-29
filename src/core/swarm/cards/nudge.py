
from __future__ import annotations

import sqlite3
from typing import Any, Dict, Mapping, Optional, Sequence, Set, Tuple

from src.core.swarm import body, store
from src.core.swarm.cards import deliver, lease, port as card_port

IDLE_S = 120.0
_told_idle: Set[Tuple[int, float]] = set()
_told_review: Set[int] = set()


def reset() -> None:
    _told_idle.clear()
    _told_review.clear()


def idle_holder(card: Mapping[str, Any], beat: Optional[lease.Beat], now: float) -> bool:
    return (beat is not None and beat.busy_at is not None and not beat.stopped and not beat.stale and now - beat.busy_at >= IDLE_S
            and (card.get("beat_at") is None or now - card["beat_at"] >= IDLE_S))


def _reportless(conn: sqlite3.Connection, agent_id: Optional[int]) -> Optional[Dict[str, Any]]:
    agent = store.get_agent(conn, agent_id) if agent_id is not None else None
    if agent is None or agent["torn_down_at"] is not None or agent["parent_id"] is None:
        return None
    parent = store.get_agent(conn, agent["parent_id"])
    if parent is None or parent["torn_down_at"] is not None or store.list_reports(conn, agent_id=agent["id"]):
        return None
    return agent


async def run(app_state: Any, leases: Sequence[Mapping[str, Any]], now: float) -> int:
    told = 0
    for card in leases:
        holder = card["holder"]
        beat = lease.beat(holder)
        if not idle_holder(card, beat, now) or (card["id"], beat.busy_at) in _told_idle:
            continue
        agent = await body.run_db(lambda c: store.get_agent(c, holder))
        if agent is None or agent["torn_down_at"] is not None or agent["state"] != "awake":
            continue
        _told_idle.add((card["id"], beat.busy_at))
        await deliver.tell(app_state, holder, f"Your turn ended while you hold card #{card['id']}. If its work is done, finish it with "
                           "swarm_card_finish (result, how-to-validate and needs_owner), which files your report; if not, write your handoff with "
                           "swarm_card_handoff and keep going, or give it up with swarm_card_release.", ref=f"card:{card['id']}", wake=False)
        told += 1
    for card in await card_port.get().cards(columns=["review"]):
        if card.get("report_id") is not None or card["id"] in _told_review:
            continue
        agent = await body.run_db(lambda c: _reportless(c, card.get("last_holder")))
        if agent is None:
            continue
        _told_review.add(card["id"])
        await deliver.tell(app_state, agent["id"], f"Card #{card['id']} ({card['title']}) is in Review and you filed no report for it. "
                           "Report your work to your parent with swarm_report now.", ref=f"card:{card['id']}", wake=False)
        told += 1
    return told
