
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterator, List, Optional, Tuple

from src.core.db import transaction
from src.core.mcp import family_signals
from src.core.trail_entry import utc_now

ROLES: Tuple[str, ...] = ("main", "member", "peer")
TRANSPORTS: Tuple[str, ...] = ("tls", "ssh")
_COLUMNS = (
    "peer_install_id", "role", "transport", "join_kind", "prev_initiator", "cert_der", "cert_sha256", "link_fid", "next_cert_der",
    "next_cert_sha256", "addresses", "link_port", "inbound_control", "joined_at", "first_link_at", "last_link_at", "updated_at",
)


@dataclass(frozen=True)
class LinkRow:

    peer_install_id: str
    role: str
    transport: str
    updated_at: str
    join_kind: Optional[str] = None
    prev_initiator: Optional[int] = None
    cert_der: Optional[bytes] = None
    cert_sha256: Optional[str] = None
    link_fid: Optional[str] = None
    next_cert_der: Optional[bytes] = None
    next_cert_sha256: Optional[str] = None
    addresses: Tuple[str, ...] = ()
    link_port: Optional[int] = None
    inbound_control: int = 1
    joined_at: Optional[str] = None
    first_link_at: Optional[str] = None
    last_link_at: Optional[str] = None

    @property
    def provisional(self) -> bool:
        return self.transport == "tls" and self.first_link_at is None


def _from_sql(raw: Tuple) -> LinkRow:
    data = dict(zip(_COLUMNS, raw))
    try:
        decoded = json.loads(data["addresses"] or "[]")
        addresses = tuple(str(a) for a in decoded) if isinstance(decoded, list) else ()
    except (TypeError, ValueError):
        addresses = ()
    data["addresses"] = addresses
    for key in ("cert_der", "next_cert_der"):
        if data[key] is not None:
            data[key] = bytes(data[key])
    return LinkRow(**data)


class LinkCache:

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rows: Dict[str, LinkRow] = {}
        self.loaded = False

    def replace(self, rows: List[LinkRow]) -> None:
        with self._lock:
            self._rows = {r.peer_install_id: r for r in rows}
            self.loaded = True

    def get(self, iid: str) -> Optional[LinkRow]:
        with self._lock:
            return self._rows.get(iid)

    def rows(self) -> List[LinkRow]:
        with self._lock:
            return sorted(self._rows.values(), key=lambda r: (r.joined_at or "", r.peer_install_id))

    def tls_main_for(self, iid: str) -> Optional[LinkRow]:
        row = self.get(iid)
        return row if row is not None and row.role == "main" and row.transport == "tls" else None


CACHE = LinkCache()


def list_rows(conn: sqlite3.Connection) -> List[LinkRow]:
    cur = conn.execute(f"SELECT {', '.join(_COLUMNS)} FROM computer_links ORDER BY COALESCE(joined_at, ''), peer_install_id")
    return [_from_sql(r) for r in cur.fetchall()]


def refresh(conn: sqlite3.Connection) -> None:
    CACHE.replace(list_rows(conn))
    family_signals.invalidate("pack")


def get(conn: sqlite3.Connection, iid: str) -> Optional[LinkRow]:
    cur = conn.execute(f"SELECT {', '.join(_COLUMNS)} FROM computer_links WHERE peer_install_id = ?", (iid,))
    raw = cur.fetchone()
    return _from_sql(raw) if raw is not None else None


@contextmanager
def _writing(conn: sqlite3.Connection) -> Iterator[None]:
    if conn.in_transaction:
        yield
    else:
        with transaction(conn):
            yield
    refresh(conn)


def put(conn: sqlite3.Connection, row: LinkRow) -> LinkRow:
    if row.role not in ROLES or row.transport not in TRANSPORTS:
        raise ValueError("unknown role or transport")
    stored = replace(row, updated_at=utc_now())
    values = {
        **{k: getattr(stored, k) for k in _COLUMNS},
        "addresses": json.dumps(list(stored.addresses)),
    }
    with _writing(conn):
        conn.execute(
            f"INSERT INTO computer_links ({', '.join(_COLUMNS)}) VALUES ({', '.join('?' for _ in _COLUMNS)}) "
            f"ON CONFLICT(peer_install_id) DO UPDATE SET {', '.join(f'{c} = excluded.{c}' for c in _COLUMNS[1:])}",
            tuple(values[c] for c in _COLUMNS),
        )
    return stored


def delete(conn: sqlite3.Connection, iid: str) -> bool:
    with _writing(conn):
        cur = conn.execute("DELETE FROM computer_links WHERE peer_install_id = ?", (iid,))
    return cur.rowcount > 0


def _update(conn: sqlite3.Connection, iid: str, sets: str, args: Tuple) -> bool:
    with _writing(conn):
        cur = conn.execute(f"UPDATE computer_links SET {sets}, updated_at = ? WHERE peer_install_id = ?", (*args, utc_now(), iid))
    return cur.rowcount > 0


def set_direction(conn: sqlite3.Connection, iid: str, inbound: bool, transport: str = "ssh", role: str = "peer") -> LinkRow:
    flag = 1 if inbound else 0
    if not _update(conn, iid, "inbound_control = ?", (flag,)):
        put(conn, LinkRow(iid, role, transport, "", inbound_control=flag))
    row = get(conn, iid)
    assert row is not None
    return row


def touch_link(conn: sqlite3.Connection, iid: str, first: bool = False) -> bool:
    now = utc_now()
    if first:
        return _update(conn, iid, "last_link_at = ?, first_link_at = COALESCE(first_link_at, ?)", (now, now))
    return _update(conn, iid, "last_link_at = ?", (now,))


def members_tls(conn: sqlite3.Connection) -> List[LinkRow]:
    return [r for r in list_rows(conn) if r.role == "member" and r.transport == "tls"]


def main_row(conn: sqlite3.Connection) -> Optional[LinkRow]:
    for r in list_rows(conn):
        if r.role == "main" and r.transport == "tls":
            return r
    return None


def provisional_older_than(conn: sqlite3.Connection, seconds: float) -> List[LinkRow]:
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return [r for r in list_rows(conn) if r.provisional and r.joined_at is not None and r.joined_at < cutoff]


def set_next_cert(conn: sqlite3.Connection, iid: str, cert_der: bytes, cert_sha256: str) -> bool:
    return _update(conn, iid, "next_cert_der = ?, next_cert_sha256 = ?", (cert_der, cert_sha256))


def promote_next_cert(conn: sqlite3.Connection, iid: str, link_fid: Optional[str] = None) -> bool:
    row = get(conn, iid)
    if row is None or row.next_cert_der is None:
        return False
    return _update(
        conn, iid,
        "cert_der = next_cert_der, cert_sha256 = next_cert_sha256, link_fid = COALESCE(?, link_fid), next_cert_der = NULL, next_cert_sha256 = NULL",
        (link_fid,),
    )


def set_link_address(conn: sqlite3.Connection, iid: str, addresses: Tuple[str, ...], link_port: Optional[int]) -> bool:
    return _update(conn, iid, "addresses = ?, link_port = ?", (json.dumps(list(addresses)), link_port))
