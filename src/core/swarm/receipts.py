
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from typing import Any, Dict, List, Sequence

from src.core.swarm import store
from src.core.trail_entry import utc_now

MAX_FACT_IDS = 20
_FACT_ID_RE = re.compile(r"^f_[0-9a-f]{12}$")


@dataclass(frozen=True)
class Receipt:

    kind: str
    fact_ids: List[str]
    rendered: str


def _title(raw: str) -> str:
    return " ".join(str(raw).split())[:120]


def build(conn: sqlite3.Connection, agent: Dict[str, Any], fact_ids: Sequence[Any]) -> Receipt:
    wanted = [i for i in dict.fromkeys(fact_ids) if isinstance(i, str) and _FACT_ID_RE.match(i)][:MAX_FACT_IDS]
    rows: Dict[str, sqlite3.Row] = {}
    if wanted:
        marks = ",".join("?" * len(wanted))
        rows = {r["id"]: r for r in conn.execute(
            f"SELECT * FROM swarm_facts WHERE agent_id = ? AND state = 'live' AND id IN ({marks})", (agent["id"], *wanted))}
    kept = [rows[i] for i in wanted if i in rows]
    if not kept:
        return Receipt("judgment", [], f"{agent['display_name']}'s own judgment, no stored fact")
    parts = []
    for fact in kept:
        if fact["origin"] == "owner":
            parts.append(f"from {_title(fact['title'])}, taught by you on {str(fact['taught_at'])[:10]}")
        else:
            writer = store.get_agent(conn, fact["taught_by_agent_id"]) if fact["taught_by_agent_id"] is not None else None
            parts.append(f"{_title(fact['title'])}, discovered by {(writer or agent)['display_name']}")
    kind = "owner_fact" if any(f["origin"] == "owner" for f in kept) else "agent_fact"
    return Receipt(kind, [f["id"] for f in kept], "; ".join(parts))


def save(conn: sqlite3.Connection, question_id: int, agent_id: int, receipt: Receipt) -> int:
    return int(conn.execute(
        "INSERT INTO swarm_receipts (question_id, answering_agent_id, kind, fact_ids, rendered, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (question_id, agent_id, receipt.kind, json.dumps(receipt.fact_ids), receipt.rendered, utc_now())).lastrowid)
