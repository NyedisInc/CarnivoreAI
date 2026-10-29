
from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Mapping, Optional

from src.core.swarm import naming_rules
from src.core.swarm.cards import dealer, port as card_port

MIN_SPECIALTY_KEY = 4


async def top_card(agent: Optional[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    if agent is None or agent.get("rank") != "project":
        return None
    cards = await card_port.get().cards(list_keys=[str(agent.get("thread_key"))], columns=["in_progress"])
    queued = dealer.queued_cards(cards)
    return dict(queued[0]) if queued else None


def specialists_for(conn: sqlite3.Connection, card: Mapping[str, Any]) -> List[Dict[str, Any]]:
    if card.get("project_id") is None:
        return []
    words = naming_rules.fold(f"{card.get('title') or ''} {card.get('summary') or ''}")
    rows = conn.execute("SELECT * FROM swarm_agents WHERE torn_down_at IS NULL AND rank = 'feature' AND project_id = ? AND specialty IS NOT NULL",
                        (card["project_id"],)).fetchall()
    return [dict(r) for r in rows if len(naming_rules.fold(r["specialty"])) >= MIN_SPECIALTY_KEY and naming_rules.fold(r["specialty"]) in words]


def misfit(conn: sqlite3.Connection, card: Mapping[str, Any], target: Mapping[str, Any]) -> Optional[str]:
    found = specialists_for(conn, card)
    if not found or any(a["id"] == target["id"] for a in found):
        return None
    names = ", ".join(f"{a['display_name']} (agent {a['id']}, specialty {a['specialty']})" for a in found)
    return f"card #{card['id']} is in the specialty of {names}; deal it there, or give a reason for dealing it to agent {target['id']}"
