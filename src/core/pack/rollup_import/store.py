
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any, Iterable, List, Optional

import structlog

from src.core.db import transaction
from src.core.federation import peer_hosts
from src.core.pack.rollup_import.ddl import COUNTER_TABLE, STATE_TABLE, USAGE_TABLE, purge_rows

logger = structlog.get_logger()

MAX_ID_CHARS = 256
COST_AT = 6


@dataclass(frozen=True)
class State:

    peer_install_id: str
    revision: int
    scope_digest: str
    pulled_at: float


def get_state(conn: sqlite3.Connection, peer_install_id: str) -> Optional[State]:
    row = conn.execute(f"SELECT revision, scope_digest, pulled_at FROM {STATE_TABLE} WHERE peer_install_id = ?",
                       (peer_install_id,)).fetchone()
    return None if row is None else State(peer_install_id, int(row[0]), str(row[1]), float(row[2]))


def purge_peer(conn: sqlite3.Connection, peer_install_id: str) -> None:
    purge_rows(conn, peer_install_id)


def reset_peer(conn: sqlite3.Connection, peer_install_id: str, scope_digest: str, now: float) -> bool:
    with transaction(conn):
        if peer_hosts.get(conn, peer_install_id) is None:
            return False
        purge_rows(conn, peer_install_id, keep_state=True)
        conn.execute(
            f"INSERT INTO {STATE_TABLE} (peer_install_id, revision, scope_digest, pulled_at, updated_at) VALUES (?, 0, ?, 0, ?) "
            "ON CONFLICT(peer_install_id) DO UPDATE SET revision = 0, scope_digest = excluded.scope_digest, "
            "pulled_at = 0, updated_at = excluded.updated_at", (peer_install_id, scope_digest, now))
    return True


def _int(value: Any) -> Optional[int]:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _text(value: Any) -> Optional[str]:
    return value if isinstance(value, str) and len(value) <= MAX_ID_CHARS else None


def _usage_rows(raw: Any) -> Optional[List[tuple]]:
    out = []
    for row in raw if isinstance(raw, list) else [None]:
        if not (isinstance(row, list) and len(row) == 9 and _text(row[0]) and _text(row[1])
                and all(_int(v) is not None for i, v in enumerate(row[2:], 2) if i != COST_AT or v is not None)):
            return None
        out.append(tuple(0 if i == COST_AT and v is None else v for i, v in enumerate(row)))
    return out


def _counter_rows(raw: Any) -> Optional[List[tuple]]:
    out = []
    for row in raw if isinstance(raw, list) else [None]:
        if not (isinstance(row, list) and len(row) == 5 and all(_text(v) is not None for v in row[:4]) and _int(row[4]) is not None
                and row[0] and row[1] and row[2]):
            return None
        out.append(tuple(row))
    return out


def apply_page(conn: sqlite3.Connection, peer_install_id: str, groups: Iterable[Any]) -> Optional[int]:
    applied = skipped = 0
    with transaction(conn):
        if peer_hosts.get(conn, peer_install_id) is None:
            return None
        for group in groups:
            usage = _usage_rows(group.get("usage")) if isinstance(group, dict) else None
            counters = _counter_rows(group.get("counters")) if isinstance(group, dict) else None
            cid, hour = (_text(group.get("conversation_id")), _int(group.get("hour"))) if isinstance(group, dict) else (None, None)
            if usage is None or counters is None or not cid or hour is None:
                skipped += 1
                continue
            for table in (USAGE_TABLE, COUNTER_TABLE):
                conn.execute(f"DELETE FROM {table} WHERE peer_install_id = ? AND conversation_id = ? AND hour = ?",
                             (peer_install_id, cid, hour))
            provider, kind = _text(group.get("provider")), _text(group.get("agent_kind"))
            conn.executemany(
                f"INSERT OR REPLACE INTO {USAGE_TABLE} (peer_install_id, conversation_id, hour, provider, agent_kind, model, project, "
                "input, cache_write, cache_read, output, cost_nano, messages, priced) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [(peer_install_id, cid, hour, provider, kind, *row) for row in usage])
            conn.executemany(
                f"INSERT OR REPLACE INTO {COUNTER_TABLE} (peer_install_id, conversation_id, hour, provider, agent_kind, model, project, "
                "counter, key, value) VALUES (?,?,?,?,?,?,?,?,?,?)",
                [(peer_install_id, cid, hour, provider, kind, *row) for row in counters])
            applied += 1
    if skipped:
        logger.warning("pack_rollup_groups_skipped", peer=peer_install_id[:8], skipped=skipped)
    return applied


def finish(conn: sqlite3.Connection, peer_install_id: str, revision: int, scope_digest: str, now: float) -> bool:
    with transaction(conn):
        if peer_hosts.get(conn, peer_install_id) is None:
            return False
        conn.execute(
            f"INSERT INTO {STATE_TABLE} (peer_install_id, revision, scope_digest, pulled_at, updated_at) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(peer_install_id) DO UPDATE SET revision = excluded.revision, scope_digest = excluded.scope_digest, "
            "pulled_at = excluded.pulled_at, updated_at = excluded.updated_at", (peer_install_id, revision, scope_digest, now, now))
    return True
