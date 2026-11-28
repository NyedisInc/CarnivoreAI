
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from src.core.federation import peer_hosts
from src.core.pack.machines.roster_v2 import RosterV2
from src.core.pack.rollup_import.ddl import COUNTER_TABLE, OFFERS_TABLE, PROJECTS_TABLE, REV_TABLE, STATE_TABLE, USAGE_TABLE, purge_rows, supplied_through

MARGIN_SECONDS = 24 * 3600
KINDS: Tuple[str, ...] = ("listed", "star_peer", "hosts_row", "recent", "leftover")
_ORIGIN_SQL = " UNION ".join(f"SELECT peer_install_id FROM {t}" for t in (USAGE_TABLE, COUNTER_TABLE, STATE_TABLE, REV_TABLE, PROJECTS_TABLE)) \
    + f" UNION SELECT origin_install_id FROM {OFFERS_TABLE}"


@dataclass(frozen=True)
class Finding:

    origins: Dict[str, List[str]]
    counts: Dict[str, int]


def _hosts_names(conn: sqlite3.Connection) -> set:
    names: set = set()
    for row in conn.execute("SELECT key, peer_install_id, machine_id FROM hosts"):
        names.update(v for v in row if v)
    return names


def _newest(conn: sqlite3.Connection, origin: str) -> Optional[float]:
    row = conn.execute(f"SELECT MAX(updated_at, pulled_at, origin_pulled_at) FROM {STATE_TABLE} WHERE peer_install_id = ?", (origin,)).fetchone()
    return float(row[0]) if row is not None and row[0] else None


def find_leftovers(conn: sqlite3.Connection, held: RosterV2) -> Finding:
    listed, hosts = set(held.order()), _hosts_names(conn)
    cutoff = held.issued_at - MARGIN_SECONDS
    out: Dict[str, List[str]] = {kind: [] for kind in KINDS}
    for (origin,) in conn.execute(_ORIGIN_SQL).fetchall():
        if not origin:
            continue
        if origin in listed:
            kind = "listed"
        elif peer_hosts.get(conn, origin) is not None:
            kind = "star_peer"
        elif origin in hosts:
            kind = "hosts_row"
        else:
            stamp = _newest(conn, origin)
            kind = "leftover" if stamp is not None and stamp < cutoff else "recent"
        out[kind].append(origin)
    for ids in out.values():
        ids.sort()
    return Finding(origins=out, counts={kind: len(ids) for kind, ids in out.items()})


_ROW_TABLES: Tuple[Tuple[str, str], ...] = (("usage", USAGE_TABLE), ("counters", COUNTER_TABLE), ("projects", PROJECTS_TABLE), ("groups", REV_TABLE))


class NotLeftover(Exception):

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def describe(conn: sqlite3.Connection, held: RosterV2) -> List[Dict[str, object]]:
    out: List[Dict[str, object]] = []
    for origin in find_leftovers(conn, held).origins["leftover"]:
        row = conn.execute(f"SELECT label FROM {STATE_TABLE} WHERE peer_install_id = ?", (origin,)).fetchone()
        rows = {word: int(conn.execute(f"SELECT COUNT(*) FROM {table} WHERE peer_install_id = ?", (origin,)).fetchone()[0]) for word, table in _ROW_TABLES}
        out.append({"install_id": origin, "name": (row[0] if row and row[0] else origin), "newest_at": _newest(conn, origin), "rows": rows})
    return out


def forget(conn: sqlite3.Connection, held: RosterV2, origin: str) -> None:
    conn.execute("BEGIN IMMEDIATE")
    try:
        if origin not in find_leftovers(conn, held).origins["leftover"]:
            raise NotLeftover("not_leftover")
        if supplied_through(conn, origin):
            raise NotLeftover("supplies_others")
        purge_rows(conn, origin, keep_floor=True)
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
