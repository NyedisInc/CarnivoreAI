
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, Iterable, List, Optional, Tuple

import structlog

from src.core.db import transaction
from src.core.pack.rollup_import import relay_store
from src.core.pack.rollup_import.ddl import COUNTER_TABLE, STATE_TABLE, USAGE_TABLE, delete_origin_rows, purge_rows

logger = structlog.get_logger()

MAX_ID_CHARS = 256
COST_AT = 6
MAX_NAME_CHARS = 200


@dataclass(frozen=True)
class State:

    peer_install_id: str
    revision: int
    scope_digest: str
    pulled_at: float
    via: str = ""
    hops: int = 1
    label: Optional[str] = None
    one_way: List[str] = field(default_factory=list)
    origin_pulled_at: float = 0.0
    v2_rev: Optional[int] = None


def get_state(conn: sqlite3.Connection, peer_install_id: str) -> Optional[State]:
    try:
        row = conn.execute(
            f"SELECT revision, scope_digest, pulled_at, via, hops, label, one_way, origin_pulled_at, v2_rev FROM {STATE_TABLE} "
            "WHERE peer_install_id = ?",
            (peer_install_id,),
        ).fetchone()
    except sqlite3.OperationalError:
        row = conn.execute(
            f"SELECT revision, scope_digest, pulled_at, via, hops, label, one_way, origin_pulled_at FROM {STATE_TABLE} "
            "WHERE peer_install_id = ?",
            (peer_install_id,),
        ).fetchone()
    return None if row is None else State(
        peer_install_id, int(row[0]), str(row[1]), float(row[2]), str(row[3]), int(row[4]),
        row[5], relay_store.id_list(row[6]), float(row[7]),
        None if len(row) < 9 or row[8] is None else int(row[8]),
    )


def purge_peer(conn: sqlite3.Connection, peer_install_id: str) -> None:
    purge_rows(conn, peer_install_id)


def reset_origin(conn: sqlite3.Connection, peer_install_id: str, scope_digest: str, now: float, *, via: str = "", hops: int = 1,
                 members: FrozenSet[str] = frozenset()) -> bool:
    if not relay_store.supplier_ok(conn, via or peer_install_id, members):
        return False
    delete_origin_rows(conn, peer_install_id)
    relay_store.restamp_origin(conn, peer_install_id)
    conn.execute(
        f"INSERT INTO {STATE_TABLE} (peer_install_id, revision, scope_digest, pulled_at, updated_at, via, hops) VALUES (?, 0, ?, 0, ?, ?, ?) "
        "ON CONFLICT(peer_install_id) DO UPDATE SET revision = 0, scope_digest = excluded.scope_digest, "
        "pulled_at = 0, updated_at = excluded.updated_at, via = excluded.via, hops = excluded.hops",
        (peer_install_id, scope_digest, now, via, hops))
    return True


def reset_peer(conn: sqlite3.Connection, peer_install_id: str, scope_digest: str, now: float, *, via: str = "", hops: int = 1,
               members: FrozenSet[str] = frozenset()) -> bool:
    with transaction(conn):
        return reset_origin(conn, peer_install_id, scope_digest, now, via=via, hops=hops, members=members)


def _int(value: Any) -> Optional[int]:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _text(value: Any) -> Optional[str]:
    return value if isinstance(value, str) and len(value) <= MAX_ID_CHARS else None


def _name(value: Any) -> Optional[str]:
    return value.strip() if isinstance(value, str) and value.strip() and len(value) <= MAX_NAME_CHARS else None


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


Normalized = Tuple[str, int, Optional[str], Optional[str], Optional[str], List[tuple], List[tuple]]


def normalized(group: Any) -> Optional[Normalized]:
    if not isinstance(group, dict):
        return None
    usage, counters = _usage_rows(group.get("usage")), _counter_rows(group.get("counters"))
    cid, hour = _text(group.get("conversation_id")), _int(group.get("hour"))
    if usage is None or counters is None or not cid or hour is None:
        return None
    return cid, hour, _text(group.get("provider")), _text(group.get("agent_kind")), _name(group.get("agent_name")), usage, counters


def apply_page(conn: sqlite3.Connection, peer_install_id: str, groups: Iterable[Any], via: str = "",
               signed: Optional[Dict[Tuple[str, int], Tuple[int, str, int]]] = None, *, members: FrozenSet[str] = frozenset()) -> Optional[int]:
    applied = skipped = replayed = 0
    with transaction(conn):
        if not relay_store.supplier_ok(conn, via or peer_install_id, members):
            return None
        held = get_state(conn, peer_install_id)
        if (held.via if held is not None else "") != via:
            return None
        for group in groups:
            norm = normalized(group)
            if norm is None:
                skipped += 1
                continue
            cid, hour, provider, kind, name, usage, counters = norm
            origin_rev: Optional[int] = None
            sig: Optional[str] = None
            epoch: Optional[int] = None
            if signed is not None:
                proof = signed.get((cid, hour))
                if proof is None:
                    skipped += 1
                    continue
                origin_rev, sig, epoch = proof
                if not relay_store.admit_epoch(conn, peer_install_id, epoch):
                    replayed += 1
                    continue
                floor = relay_store.origin_rev(conn, peer_install_id, cid, hour)
                if floor > origin_rev:
                    replayed += 1
                    continue
                if floor == origin_rev and relay_store.held_sig(conn, peer_install_id, cid, hour) == sig:
                    continue
            for table in (USAGE_TABLE, COUNTER_TABLE):
                conn.execute(f"DELETE FROM {table} WHERE peer_install_id = ? AND conversation_id = ? AND hour = ?",
                             (peer_install_id, cid, hour))
            conn.executemany(
                f"INSERT OR REPLACE INTO {USAGE_TABLE} (peer_install_id, conversation_id, hour, provider, agent_kind, model, project, "
                "input, cache_write, cache_read, output, cost_nano, messages, priced, agent_name) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [(peer_install_id, cid, hour, provider, kind, *row, name) for row in usage])
            conn.executemany(
                f"INSERT OR REPLACE INTO {COUNTER_TABLE} (peer_install_id, conversation_id, hour, provider, agent_kind, model, project, "
                "counter, key, value) VALUES (?,?,?,?,?,?,?,?,?,?)",
                [(peer_install_id, cid, hour, provider, kind, *row) for row in counters])
            relay_store.stamp(conn, peer_install_id, cid, hour, origin_rev=origin_rev, sig=sig, epoch=epoch)
            if origin_rev is not None:
                relay_store.raise_origin_rev(conn, peer_install_id, cid, hour, origin_rev)
            applied += 1
    if skipped:
        logger.warning("pack_rollup_groups_skipped", peer=peer_install_id[:8], skipped=skipped)
    if replayed:
        logger.warning("pack_rollup_groups_replayed", peer=peer_install_id[:8], replayed=replayed)
    return applied


def finish(conn: sqlite3.Connection, peer_install_id: str, revision: int, scope_digest: str, now: float, *,
           via: str = "", hops: int = 1, label: Optional[str] = None, one_way: Optional[List[str]] = None,
           origin_pulled_at: Optional[float] = None, members: FrozenSet[str] = frozenset()) -> bool:
    with transaction(conn):
        if not relay_store.supplier_ok(conn, via or peer_install_id, members):
            return False
        held = get_state(conn, peer_install_id)
        if held is not None and held.via != via:
            return False
        conn.execute(
            f"INSERT INTO {STATE_TABLE} (peer_install_id, revision, scope_digest, pulled_at, updated_at, via, hops, label, one_way, origin_pulled_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(peer_install_id) DO UPDATE SET revision = excluded.revision, scope_digest = excluded.scope_digest, "
            "pulled_at = excluded.pulled_at, updated_at = excluded.updated_at, via = excluded.via, hops = excluded.hops, "
            f"label = COALESCE(excluded.label, {STATE_TABLE}.label), "
            f"one_way = CASE WHEN ? THEN excluded.one_way ELSE {STATE_TABLE}.one_way END, origin_pulled_at = excluded.origin_pulled_at",
            (peer_install_id, revision, scope_digest, now, now, via, hops, label, json.dumps(relay_store.id_list(one_way or [])),
             now if origin_pulled_at is None else origin_pulled_at, 1 if one_way is not None else 0))
    return True
