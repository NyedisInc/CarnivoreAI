
from __future__ import annotations

import base64
import hashlib
import json
import os
import sqlite3
import threading
import time
from contextlib import closing
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

import structlog

from src.core.db import DatastoreUnreadableError, connect, db_path_for, transaction
from src.core.deepsearch import peer_air_gap
from src.core.stats import project_groups
from src.core.stats.plugin import revision
from src.core.stats.plugin.extract import project_key

logger = structlog.get_logger()

PAGE_BYTES = 900 * 1024
MAX_PAGE_BYTES = 1024 * 1024
_CHUNK = 200
_ENVELOPE_BYTES = 2048

USAGE_COLUMNS = ("model", "project", "input", "cache_write", "cache_read", "output", "cost_nano", "messages", "priced")
COUNTER_COLUMNS = ("model", "project", "counter", "key", "value")

_USAGE_SQL = (
    "SELECT m.name, p.name, SUM(u.input), SUM(u.cache_write), SUM(u.cache_read), SUM(u.output), SUM(u.cost_nano), "
    "SUM(u.messages), SUM(u.priced), MIN(s.provider), MIN(s.agent_kind) FROM usage_hour u "
    "JOIN dim_source s ON s.id = u.src JOIN dim_model m ON m.id = u.model JOIN dim_project p ON p.id = u.project "
    "WHERE u.t = ? AND u.src IN (SELECT id FROM dim_source WHERE conversation_id = ?) "
    "GROUP BY m.name, p.name ORDER BY m.name, p.name")
_COUNTER_SQL = (
    "SELECT m.name, p.name, n.name, k.name, SUM(c.value), MIN(s.provider), MIN(s.agent_kind) FROM counter_hour c "
    "JOIN dim_source s ON s.id = c.src JOIN dim_model m ON m.id = c.model JOIN dim_project p ON p.id = c.project "
    "JOIN dim_counter n ON n.id = c.counter JOIN dim_key k ON k.id = c.key "
    "WHERE c.t = ? AND c.src IN (SELECT id FROM dim_source WHERE conversation_id = ?) "
    "GROUP BY m.name, p.name, n.name, k.name "
    "ORDER BY m.name, p.name, n.name, k.name")
_NEXT_SQL = (
    "SELECT conversation_id, hour, rev FROM rollup_rev WHERE rev > ? AND rev <= ? "
    "AND (rev, hour, conversation_id) > (?, ?, ?) ORDER BY rev, hour, conversation_id LIMIT ?")


def scope_digest(excluded: FrozenSet[str], allowlist: bool = False) -> str:
    return hashlib.sha256(("\n".join(sorted(excluded)) + ("\0allowlist" if allowlist else "")).encode()).hexdigest()[:16]


def encode_cursor(rev: int, hour: int, conversation_id: str) -> str:
    raw = json.dumps([rev, hour, conversation_id], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: Optional[str]) -> Tuple[int, int, str]:
    """A cursor back to (rev, hour, conversation id); None is the start. Raises: ValueError for a cursor we did not issue."""
    if not cursor:
        return (-1, -1, "")
    try:
        rev, hour, conversation_id = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
    except (ValueError, TypeError) as exc:
        raise ValueError("bad rollup cursor") from exc
    if not (isinstance(rev, int) and isinstance(hour, int) and isinstance(conversation_id, str)):
        raise ValueError("bad rollup cursor")
    return (rev, hour, conversation_id)


def _group(conn: sqlite3.Connection, conversation_id: str, hour: int, rev: int,
           excluded: FrozenSet[str], allow: Optional[FrozenSet[str]] = None) -> Optional[Dict[str, Any]]:
    stored_usage = conn.execute(_USAGE_SQL, (hour, conversation_id)).fetchall()
    stored_counters = conn.execute(_COUNTER_SQL, (hour, conversation_id)).fetchall()
    usage = [r for r in stored_usage if r[1] not in excluded and (allow is None or r[1] in allow)]
    counters = [r for r in stored_counters if r[1] not in excluded and (allow is None or r[1] in allow)]
    if (stored_usage or stored_counters) and not (usage or counters):
        return None
    first = (usage[0][9], usage[0][10]) if usage else ((counters[0][5], counters[0][6]) if counters else (None, None))
    return {
        "conversation_id": conversation_id, "provider": first[0], "agent_kind": first[1], "hour": hour, "rev": rev,
        "usage": [list(r[:9]) for r in usage], "counters": [list(r[:5]) for r in counters],
    }


def export_rollup(conn: sqlite3.Connection, since_revision: int, *, until_revision: Optional[int] = None,
                  cursor: Optional[str] = None, exclude_projects: FrozenSet[str] = frozenset(),
                  allow_projects: Optional[FrozenSet[str]] = None, revoked_projects: FrozenSet[str] = frozenset(),
                  max_bytes: int = PAGE_BYTES) -> Dict[str, Any]:
    current = revision.current(conn)
    reset = since_revision > current or since_revision < 0
    since = 0 if reset else since_revision
    until = current if until_revision is None else max(0, min(until_revision, current))
    withheld = exclude_projects | revoked_projects
    budget = max(4096, min(int(max_bytes), MAX_PAGE_BYTES)) - _ENVELOPE_BYTES
    after = decode_cursor(cursor)
    groups: List[Dict[str, Any]] = []
    used, last, complete = 0, after, True
    more = revision.exists(conn)
    while more and complete:
        chunk = conn.execute(_NEXT_SQL, (since, until, *last, _CHUNK)).fetchall()
        for conversation_id, hour, rev in chunk:
            group = _group(conn, conversation_id, hour, rev, exclude_projects, allow_projects)
            size = len(json.dumps(group, separators=(",", ":"))) if group is not None else 0
            if groups and used + size > budget:
                complete = False
                break
            last = (rev, hour, conversation_id)
            if group is not None:
                groups.append(group)
                used += size
        more = len(chunk) == _CHUNK
    return {
        "revision": current, "since_revision": since, "until_revision": until, "reset": reset,
        "scope_digest": scope_digest(withheld, allow_projects is not None), "complete": complete,
        "next_cursor": None if complete else encode_cursor(*last),
        "usage_columns": list(USAGE_COLUMNS), "counter_columns": list(COUNTER_COLUMNS), "groups": groups,
    }


_INDEX_SECONDS = 30.0
_index_lock = threading.Lock()
_index_cache: Dict[str, Tuple[float, List[Tuple[str, str]]]] = {}


def _folder_index(store: Any) -> List[Tuple[str, str]]:
    now = time.monotonic()
    with _index_lock:
        hit = _index_cache.get(str(store.state_dir))
        if hit is not None and now - hit[0] < _INDEX_SECONDS:
            return hit[1]
    folders = peer_air_gap.ledger_folders(store.state_dir)
    try:
        with closing(connect(db_path_for(store.state_dir), create=False)) as app_db:
            folders.update(project_groups.known_folders(app_db))
    except (DatastoreUnreadableError, sqlite3.Error) as exc:
        logger.info("stats_rollup_known_folders_unreadable", error_type=type(exc).__name__)
    index = [(project_key(f), peer_air_gap.fold(f)) for f in sorted(folders) if os.path.isabs(f)]
    with _index_lock:
        _index_cache[str(store.state_dir)] = (now, index)
    return index


def forget_index() -> None:
    with _index_lock:
        _index_cache.clear()


def allowed_projects(store: Any) -> Optional[FrozenSet[str]]:
    gate = peer_air_gap.load_gate(store.state_dir)
    if not gate.active:
        return None
    index = _folder_index(store)
    inside = {key for key, folded in index if gate.inside_folded(folded)}
    return frozenset(key for key, folded in index if not gate.inside_folded(folded)) - inside


def serve(store: Any, *, since_revision: int, until_revision: Optional[int], cursor: Optional[str],
          max_bytes: int) -> Dict[str, Any]:
    from src.core.stats import config

    if not config.get_settings(store)["enabled"]:
        return {"available": False, "reason": "stats_off"}
    try:
        allow = allowed_projects(store)
    except peer_air_gap.AirGapUnreadable:
        logger.warning("stats_rollup_air_gap_unreadable")
        return {"available": False, "reason": "projects_unreadable"}
    with store.connect() as conn:
        if not revision.exists(conn):
            with transaction(conn):
                revision.ensure(conn)
        revoked = revision.settle(conn, allow)
        page = export_rollup(conn, since_revision, until_revision=until_revision, cursor=cursor,
                             allow_projects=allow, revoked_projects=revoked, max_bytes=max_bytes)
    return {"available": True, **page}


def advertised_revisions(store: Any) -> Dict[str, int]:
    from src.core.stats import config

    if store is None:
        return {}
    try:
        if not config.get_settings(store)["enabled"]:
            return {}
        with store.connect(readonly=True) as conn:
            current = revision.current(conn)
    except (sqlite3.Error, OSError) as exc:
        logger.info("stats_rollup_revision_unreadable", error_type=type(exc).__name__)
        return {}
    return {"stats": current} if current else {}
