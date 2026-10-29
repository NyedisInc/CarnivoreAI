"""Which card a dealer takes and whether the agent fits it (#1457, ``docs/swarm-cards.md`` 14): rules the server keeps, not the prompt.

A ``swarm_card_deal`` with no card id deals the top queued card of the dealer's own project, picked here. The fit check reads the stored
specialty of every live feature agent of the card's project: a card whose title or summary names one of those specialties goes to that
specialist, and a deal to anyone else needs a ``reason`` (kept in the card's history). The board order rule itself lives in the plugin
(``src/cplugs/huddle/cards/queue.py::deal``), inside the deal's own transaction.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Mapping, Optional

from src.core.swarm import naming_rules
from src.core.swarm.cards import dealer, port as card_port

MIN_SPECIALTY_KEY = 4


async def top_card(agent: Optional[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    """The top queued card of a project agent's own project (``dealer.queued_cards`` order), None when nothing is queued.

    Inputs: agent (the dealer's row; only a project agent has a project of its own to pick from, anyone else gets None).
    Output: CardView | None. Example: await top_card({"rank": "project", "thread_key": "17"}) -> {"id": 52, ...}
    """
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
