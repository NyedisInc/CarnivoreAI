
from __future__ import annotations

import sqlite3
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence

import structlog

from src.core import db
from src.core.swarm import author_path, body, stream_sources, thread_port
from src.cplugs.sdk import chat_category

logger = structlog.get_logger()

MAX_LIMIT = 200
EXTRA_SOURCES: List[Callable[[Dict[str, Any], int], Awaitable[List[Dict[str, Any]]]]] = []


def merge(*streams: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted((e for s in streams for e in s), key=lambda e: (e["at"], e["id"]))


def window(entries: List[Dict[str, Any]], since: Optional[str], limit: int,
           keep: Optional[Callable[[Dict[str, Any]], bool]] = None) -> List[Dict[str, Any]]:
    if since:
        at = next((i for i, e in enumerate(entries) if e["id"] == since), None)
        if at is not None:
            entries = entries[at + 1:]
    return [e for e in entries if keep is None or keep(e)][-limit:]


EXTRA_SOURCES.extend(stream_sources.SOURCES)

VIEWS = ("all", "shown")


async def page(agent: Dict[str, Any], *, since: Optional[str] = None, limit: int = MAX_LIMIT, view: str = "all",
               muted: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    limit = max(1, min(int(limit), MAX_LIMIT))
    port = thread_port.get()
    thread = await port.read_thread(agent["thread_key"], MAX_LIMIT) if port is not None else []
    extra = [await source(agent, MAX_LIMIT) for source in EXTRA_SOURCES]
    merged = merge(thread, *extra)
    for entry in merged:
        if not entry.get("category"):
            entry["category"] = chat_category.derive(entry)
    keep = None if view == "all" else (lambda e: chat_category.is_shown(e["category"], muted))
    entries = window(merged, since, limit, keep)
    try:
        await body.run_db(lambda c: author_path.annotate(c, agent, entries))
    except (sqlite3.Error, db.DatastoreUnreadableError) as exc:
        logger.warning("swarm_author_path_unreadable", agent_id=agent.get("id"), error_type=type(exc).__name__)
        for entry in entries:
            entry.setdefault("author_path", [])
            entry.pop("peer_key", None)
    return {"entries": entries, "cursor": entries[-1]["id"] if entries else None}
