
from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional, Sequence, Set

import structlog

from src.core import db
from src.core.swarm import author_path, body, owner_wait, routing, store, stream, thread_port
from src.core.swarm.views import AgentMissing
from src.core.swarm.cards import port as card_port

logger = structlog.get_logger()

NEEDS_YOU = "needs you:"
KINDS = ("card", "review", "approval")


def scope_ids(agents: Sequence[Dict[str, Any]], root_id: int, chains: Optional[Dict[int, List[int]]] = None) -> List[int]:
    if chains is not None:
        under = [(chains.get(int(a["id"]), []).index(root_id), int(a["id"])) for a in agents
                 if int(a["id"]) != root_id and root_id in chains.get(int(a["id"]), [])]
        return [root_id] + [agent_id for _depth, agent_id in sorted(under)]
    kids: Dict[int, List[int]] = {}
    for agent in agents:
        if agent.get("parent_id") is not None:
            kids.setdefault(int(agent["parent_id"]), []).append(int(agent["id"]))
    out, seen = [root_id], {root_id}
    for agent_id in out:
        for child in kids.get(agent_id, []):
            if child not in seen:
                seen.add(child)
                out.append(child)
    return out


def chains_of(conn: sqlite3.Connection) -> Dict[int, List[int]]:
    return {int(a["id"]): [int(t["id"]) for t in routing.chain_for(conn, a)] for a in store.list_agents(conn)}


def needs_owner(card: Dict[str, Any]) -> bool:
    return card.get("column") == "review" and str(card.get("result") or "").startswith(NEEDS_YOU)


def card_agent(card: Dict[str, Any]) -> Optional[int]:
    held = card.get("holder") or {}
    if held.get("agent_id") is not None:
        return int(held["agent_id"])
    last = card.get("last_holder")
    return int(last) if last is not None else None


def order(items: List[Dict[str, Any]], root_id: int) -> List[Dict[str, Any]]:
    return sorted(items, key=lambda i: (i["agent_id"] != root_id, i.get("at") or 0))


def _epoch(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value) / 1000.0 if value > 1e12 else float(value)
    from datetime import datetime
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _asker_in_scope(entry: Dict[str, Any], live: Dict[int, Set[int]], ids: Sequence[int]) -> Optional[int]:
    qid = owner_wait.question_id(str((entry.get("item") or {}).get("swarm_ref") or ""))
    if qid is None:
        return None
    askers = [int(a["agent_id"]) for a in (entry.get("question") or {}).get("askers") or [] if a.get("agent_id") is not None]
    mine = live.get(qid, set())
    return next((a for a in [*askers, *ids] if a in mine and a in ids), None)


async def _card_items(rows: Dict[int, Dict[str, Any]], ids: Sequence[int]) -> List[Dict[str, Any]]:
    port = thread_port.get()
    if port is None:
        return []
    live = await body.run_db(owner_wait.live_questions)
    wanted = {qid for qid, askers in live.items() if askers & set(ids)}
    threads = {rows[i]["thread_key"]: i for i in ids}
    owners = {row["thread_key"]: agent_id for agent_id, row in rows.items()}
    open_ids: Dict[str, List[int]] = {}
    for c in await port.open_cards():
        if c["thread_key"] in owners and (c["thread_key"] in threads or owner_wait.question_id(str(c.get("swarm_ref") or "")) in wanted):
            open_ids.setdefault(c["thread_key"], []).append(int(c["id"]))
    out: List[Dict[str, Any]] = []
    for key in sorted(open_ids):
        for entry in await stream.card_entries(rows[owners[key]], open_ids[key]):
            if not entry.get("waits_on_owner"):
                continue
            asker = _asker_in_scope(entry, live, ids)
            agent_id = asker if asker is not None else threads.get(key)
            if agent_id is not None:
                out.append({"kind": "card", "id": f"card:{entry['id']}", "agent_id": agent_id,
                            "author_path": entry.get("author_path") or [], "at": _epoch(entry.get("at")), "entry": entry})
    return out


async def _review_items(ids: Set[int]) -> List[Dict[str, Any]]:
    try:
        cards = await card_port.get().cards(columns=("review",))
    except card_port.CardsOff:
        return []
    return [{"kind": "review", "id": f"review:{c['id']}", "agent_id": card_agent(c), "at": _epoch(c.get("updated_at")), "card": c}
            for c in cards if needs_owner(c) and card_agent(c) in ids]


async def _approval_items(manager: Any, inbox: Any, rows: Dict[int, Dict[str, Any]], ids: Set[int]) -> List[Dict[str, Any]]:
    if inbox is None or manager is None:
        return []
    by_row = {int(rows[i]["session_row_id"]): i for i in ids if rows[i].get("session_row_id") is not None}
    by_session: Dict[str, int] = {}
    for info in await manager.list_session_infos():
        row_id = getattr(info, "session_row_id", None)
        if row_id is not None and int(row_id) in by_row and getattr(info, "host_key", None) in (None, "local"):
            by_session[info.session.id] = by_row[int(row_id)]
    out: List[Dict[str, Any]] = []
    for item in await inbox.list_items():
        raw = item.model_dump() if hasattr(item, "model_dump") else dict(item)
        agent_id = by_session.get(str(raw.get("session_id")))
        if agent_id is not None:
            out.append({"kind": "approval", "id": f"approval:{raw['id']}", "agent_id": agent_id,
                        "at": _epoch(raw.get("created_at")), "approval": raw})
    return out


async def feed(agent_id: int, *, manager: Any, inbox: Any) -> Dict[str, Any]:
    agents = await body.run_db(store.list_agents)
    rows = {int(a["id"]): a for a in agents}
    if agent_id not in rows:
        raise AgentMissing(str(agent_id))
    ids = scope_ids(agents, agent_id, await body.run_db(chains_of))
    items = await _card_items(rows, ids) + await _review_items(set(ids)) + await _approval_items(manager, inbox, rows, set(ids))
    paths: Dict[int, List[Dict[str, Any]]] = {}

    def read_paths(conn: sqlite3.Connection) -> None:
        for wanted in {i["agent_id"] for i in items if not i.get("author_path")}:
            paths[wanted] = author_path.path_for_agent(conn, rows[wanted])

    try:
        await body.run_db(read_paths)
    except (sqlite3.Error, db.DatastoreUnreadableError) as exc:
        logger.warning("swarm_waiting_paths_unreadable", agent_id=agent_id, error_type=type(exc).__name__)
    for item in items:
        if not item.get("author_path"):
            item["author_path"] = paths.get(item["agent_id"], [])
    ordered = order(items, agent_id)
    return {"agent_id": agent_id, "items": ordered, "count": len(ordered)}


def brief(item: Dict[str, Any]) -> Dict[str, Any]:
    if item["kind"] == "card":
        entry = item.get("entry") or {}
        found = entry.get("item") or {}
        ask = ((entry.get("question") or {}).get("summary") or found.get("title") or found.get("text") or "")
    elif item["kind"] == "review":
        card = item.get("card") or {}
        ask = str(card.get("result") or "")[len(NEEDS_YOU):].split("\n", 1)[0].strip() or str(card.get("title") or "")
    else:
        approval = item.get("approval") or {}
        ask = str(approval.get("question") or approval.get("kind") or "")
    from src.core.mcp.tools import redact_text

    return {"kind": item["kind"], "id": item["id"], "agent_id": item["agent_id"],
            "path": " > ".join(str(c.get("name") or "") for c in item.get("author_path") or []), "at": item.get("at"),
            "ask": redact_text(" ".join(ask.split()))[:300]}
