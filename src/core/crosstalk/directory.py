
from __future__ import annotations

import asyncio
import difflib
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from typing import Any, Optional

import structlog

from src.core.hosts.ddl import LOCAL_HOST_KEY

logger = structlog.get_logger()

FUZZY_MIN_RATIO = 0.75
TIERS = ("session_uuid", "id", "label", "normalized", "prefix", "substring", "fuzzy")
_IGNORED = re.compile(r"[\s\-_.]+")


@dataclass
class Resolution:

    matches: list = field(default_factory=list)
    tier: Optional[str] = None
    ambiguous: bool = False


def normalize(text: str) -> str:
    return _IGNORED.sub("", text.strip().lstrip("@").casefold())


def _aliases(former_names: Optional[str]) -> list[str]:
    from src.core.swarm.naming_rules import former_names as parse

    return parse({"former_names": former_names})


def _session_details(row_ids: list[int]) -> dict[int, tuple[str, Optional[str], list[str]]]:
    if not row_ids:
        return {}
    from src.config import settings
    from src.core.db import DatastoreUnreadableError, connect, db_path_for

    marks = ",".join("?" * len(row_ids))
    try:
        with closing(connect(db_path_for(settings.get_state_dir()), create=False)) as conn:
            rows = conn.execute(f"SELECT s.id, s.session_uuid, s.claude_title, a.former_names FROM sessions s LEFT JOIN swarm_agents a "
                                f"ON a.session_row_id = s.id AND a.torn_down_at IS NULL WHERE s.id IN ({marks})", row_ids).fetchall()
    except (DatastoreUnreadableError, sqlite3.Error) as exc:
        logger.warning("crosstalk.directory.details_lookup_failed", error=type(exc).__name__)
        return {}
    return {int(r[0]): (str(r[1]), r[2], _aliases(r[3])) for r in rows}


def agent_session_uuid(agent_id: int) -> Optional[str]:
    from src.config import settings
    from src.core.db import DatastoreUnreadableError, connect, db_path_for

    try:
        with closing(connect(db_path_for(settings.get_state_dir()), create=False)) as conn:
            row = conn.execute(
                "SELECT s.session_uuid FROM swarm_agents a JOIN sessions s ON s.id = a.session_row_id WHERE a.id = ?",
                (agent_id,)).fetchone()
    except (DatastoreUnreadableError, sqlite3.Error) as exc:
        logger.warning("crosstalk.directory.agent_lookup_failed", error=type(exc).__name__)
        return None
    return str(row[0]) if row and row[0] else None


def _card(info: Any, details: dict[int, tuple[str, Optional[str], list[str]]], self_tmux: Optional[str]) -> dict:
    local = info.host_key == LOCAL_HOST_KEY
    detail = details.get(info.session_row_id) if info.session_row_id is not None else None
    name = (info.label or "").strip() or ((detail[1] or "").strip() if detail else "") or (info.claude_title or "").strip() or info.tmux_session or info.session.id
    uuid = detail[0] if local and detail else info.session_uuid
    provider = info.agent_family or info.agent_type or info.session.agent_type
    reachable = ["paste"] if info.host_state == "up" and provider and provider != "shell" else []
    return {
        "handle": "@" + name,
        "name": name,
        "id": info.session.id,
        "tmux_name": info.tmux_session,
        "session_uuid": uuid,
        "provider": provider,
        "model": info.session.model,
        "host": info.host_label,
        "host_state": info.host_state,
        "project": info.project_name,
        "working_dir": info.session.working_dir,
        "status": info.activity_status,
        "reachable_via": reachable,
        "is_you": bool(local and self_tmux and info.tmux_session == self_tmux),
        "former_names": detail[2] if local and detail else [],
    }


def _asleep_rows() -> list[dict]:
    return _stored_rows("asleep_rows")


def _closed_rows() -> list[dict]:
    """Every CLOSED local row with a known conversation id (#1980), shaped like :func:`_asleep_rows`. On a worker thread."""
    return _stored_rows("closed_rows")


def _stored_rows(reader: str) -> list[dict]:
    from src.config import settings
    from src.core import session_sleep
    from src.core.db import DatastoreUnreadableError, connect, db_path_for

    try:
        with closing(connect(db_path_for(settings.get_state_dir()), create=False)) as conn:
            rows = [r for r in getattr(session_sleep, reader)(conn) if (r.get("host_key") or LOCAL_HOST_KEY) == LOCAL_HOST_KEY]
            agents = {int(a[0]): (int(a[1]), a[2], a[3]) for a in conn.execute(
                "SELECT session_row_id, id, torn_down_at, former_names FROM swarm_agents WHERE session_row_id IS NOT NULL")}
    except (DatastoreUnreadableError, sqlite3.Error) as exc:
        logger.warning("crosstalk.directory.asleep_lookup_failed", error=type(exc).__name__)
        return []
    out = []
    for row in rows:
        agent = agents.get(int(row["id"]))
        if agent is not None and agent[1] is not None:
            continue
        out.append({**row, "swarm_agent_id": agent[0] if agent else None, "former_names": _aliases(agent[2]) if agent else []})
    return out


def _asleep_card(row: dict, host_label: str) -> dict:
    name = ((row.get("title") or "").strip() or (row.get("claude_title") or "").strip()
            or (row.get("tmux_name") or "").strip() or str(row["session_uuid"]))
    card = {
        "handle": "@" + name, "name": name, "id": str(row["session_uuid"]), "tmux_name": row.get("tmux_name"),
        "session_uuid": str(row["session_uuid"]), "provider": row.get("agent_type"), "model": row.get("model"),
        "host": host_label, "host_state": "up", "project": row.get("project_name"), "working_dir": row.get("working_dir"),
        "status": "asleep", "reachable_via": ["wake"], "is_you": False, "asleep": True, "former_names": row.get("former_names") or [],
    }
    if row.get("swarm_agent_id") is not None:
        card["swarm_agent_id"] = row["swarm_agent_id"]
    return card


async def list_cards(manager: Any, *, self_tmux: Optional[str] = None, include_remote: bool = True,
                     include_asleep: bool = False) -> list[dict]:
    infos = [i for i in await manager.list_session_infos() if i.host_key == LOCAL_HOST_KEY]
    if include_remote:
        infos += await manager.list_peer_infos()
    ids = [i.session_row_id for i in infos if i.session_row_id is not None]
    details = await asyncio.to_thread(_session_details, ids)
    cards = [_card(i, details, self_tmux) for i in infos]
    if include_asleep:
        live = {c["session_uuid"] for c in cards if c["session_uuid"]}
        label = next((i.host_label for i in infos if i.host_key == LOCAL_HOST_KEY), None) or "this"
        cards += [_asleep_card(r, label) for r in await asyncio.to_thread(_asleep_rows) if str(r["session_uuid"]) not in live]
    return cards


async def local_identity(manager: Any, session_id: str) -> Optional[dict]:
    """The minimal card (``id``, ``session_uuid``) of ONE local session, without building every card.

    Inputs: manager (``SessionManager``-like with ``get_session_info``); session_id (str).
    Output: dict | None. None when the session is gone or has no stored row; ``session_uuid`` is the row's stored uuid.
    """
    info = await manager.get_session_info(session_id=session_id)
    if info is None or info.session_row_id is None:
        return None
    detail = (await asyncio.to_thread(_session_details, [info.session_row_id])).get(info.session_row_id)
    return {"id": info.session.id, "session_uuid": detail[0] if detail else info.session_uuid}


def _tier(query: str, card: dict) -> tuple[Optional[str], float]:
    q = query.strip()
    if card.get("session_uuid") and q == card["session_uuid"]:
        return "session_uuid", 1.0
    if q in (card["id"], card.get("tmux_name")):
        return "id", 1.0
    former = card.get("former_names") or []
    if q.lstrip("@").casefold() in [n.casefold() for n in (card["name"], *former)]:
        return "label", 1.0
    nq = normalize(q)
    if not nq:
        return None, 0.0
    names = _card_names(card)
    if nq in names or nq in [normalize(n) for n in former]:
        return "normalized", 1.0
    if any(n.startswith(nq) for n in names):
        return "prefix", nq and len(nq) / max(len(n) for n in names)
    if any(nq in n for n in names):
        return "substring", len(nq) / max(len(n) for n in names)
    return None, 0.0


def _card_names(card: dict) -> list[str]:
    return [normalize(card["name"])] + ([normalize(card["tmux_name"])] if card.get("tmux_name") else [])


def _fuzzy_tier(query: str, card: dict) -> tuple[Optional[str], float]:
    nq = normalize(query.strip())
    if not nq:
        return None, 0.0
    ratio = max(difflib.SequenceMatcher(None, nq, n).ratio() for n in _card_names(card))
    return ("fuzzy", ratio) if ratio >= FUZZY_MIN_RATIO else (None, 0.0)


def _rank(scored: list[tuple[str, float, dict]]) -> Resolution:
    if not scored:
        return Resolution()
    best = min(TIERS.index(t) for t, _, _ in scored)
    top = sorted((x for x in scored if TIERS.index(x[0]) == best), key=lambda x: -x[1])
    return Resolution(matches=[c for _, _, c in top], tier=TIERS[best], ambiguous=len(top) > 1)


def _resolve_exact(query: str, cards: list[dict]) -> Optional[Resolution]:
    scored = [(t, s, c) for c in cards for t, s in [_tier(query, c)] if t]
    return _rank(scored) if scored else None


def _resolve_fuzzy(query: str, cards: list[dict]) -> Resolution:
    return _rank([(t, s, c) for c in cards for t, s in [_fuzzy_tier(query, c)] if t])


def resolve_handle(query: str, cards: list[dict]) -> Resolution:
    return _resolve_exact(query, cards) or _resolve_fuzzy(query, cards)


async def resolve_handle_async(query: str, cards: list[dict]) -> Resolution:
    exact = _resolve_exact(query, cards)
    return exact if exact is not None else await asyncio.to_thread(_resolve_fuzzy, query, cards)


async def lookup(manager: Any, *, query: Optional[str] = None, provider: Optional[str] = None,
                 include_remote: bool = True, include_self: bool = False, limit: int = 25,
                 self_tmux: Optional[str] = None) -> dict:
    cards = await list_cards(manager, self_tmux=self_tmux, include_remote=include_remote, include_asleep=True)
    if not include_self:
        cards = [c for c in cards if not c["is_you"]]
    if provider and provider.strip():
        want = provider.strip().casefold()
        cards = [c for c in cards if (c["provider"] or "").casefold() == want]
    limit = max(1, min(int(limit), 100))
    if query and query.strip():
        res = await resolve_handle_async(query, cards)
        matches, tier, ambiguous = res.matches, res.tier, res.ambiguous
    else:
        matches, tier, ambiguous = sorted(cards, key=lambda c: (c["host"], c["name"].casefold())), None, False
    return {"agents": matches[:limit], "match": tier, "ambiguous": ambiguous,
            "truncated": len(matches) > limit, "query": query}
