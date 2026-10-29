
from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from typing import List, Optional, Tuple

from src.core.db import transaction
from src.core.federation.ddl import FEDERATION_GRANTS_TABLE
from src.core.federation.fed_key import fid_for
from src.core.trail_entry import utc_now

SCOPE_SESSIONS = "sessions"
SCOPE_SETTINGS = "settings"
PACK_SCOPES = ("machine", "swarm-proxy", "replica", "migrate", "credentials", "refresh", "skills")
KNOWN_SCOPES = frozenset({SCOPE_SESSIONS, "archive", "ledger", SCOPE_SETTINGS, *PACK_SCOPES})
SCOPE_REPLICA = "replica"

_COLUMNS = ("grant_id, peer_install_id, public_key, fid, label, scopes, remote_grant_id, "
            "created_at, last_seen_at, revoked_at")


class GrantError(Exception):
    """A grant could not be made or found. ``code`` is the wire code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Grant:

    grant_id: str
    peer_install_id: str
    public_key: str
    fid: str
    label: str
    scopes: Tuple[str, ...]
    remote_grant_id: Optional[str]
    created_at: str
    last_seen_at: Optional[str]
    revoked_at: Optional[str]

    @property
    def revoked(self) -> bool:
        return self.revoked_at is not None

    def allows(self, scope: str) -> bool:
        return scope in self.scopes


def _hydrate(row) -> Grant:
    return Grant(row[0], row[1], row[2], row[3], row[4], tuple(s for s in row[5].split(",") if s),
                 row[6], row[7], row[8], row[9])


def decode_public_key(public_key: object) -> bytes:
    from src.core.relay_identity.device_key import unb64url

    raw = unb64url(public_key, 32)
    if raw is None:
        raise GrantError("public_key_invalid", "the public key is not 32 base64url bytes")
    return raw


def create_grant(conn: sqlite3.Connection, *, peer_install_id: str, public_key: str, label: str,
                 scopes: Tuple[str, ...] = (SCOPE_SESSIONS,), remote_grant_id: Optional[str] = None,
                 grant_id: Optional[str] = None) -> Grant:
    """Issue a grant to one peer; one live grant per peer install id.

    Inputs: the peer's install id, its public key (b64url), a label (trimmed to 64),
      scopes, the grant id the peer issued to us when known, and ``grant_id`` when the
      caller had to name it before the peer's key was known (the pairing driver).
    Output: Grant. Raises: GrantError - ``public_key_invalid`` / ``scope_unknown`` /
      ``peer_id_invalid`` / ``grant_exists`` (a live grant for that peer already exists).
    Example: create_grant(conn, peer_install_id=iid, public_key=pk, label="hosta")
    """
    fid = fid_for(decode_public_key(public_key))
    if not peer_install_id or len(peer_install_id) > 64 or not peer_install_id.isprintable():
        raise GrantError("peer_id_invalid", "the peer install id is not usable")
    if not scopes or not set(scopes) <= KNOWN_SCOPES:
        raise GrantError("scope_unknown", "an unknown scope was requested")
    label = "".join(c for c in str(label) if c.isprintable()).strip()[:64]
    grant_id = grant_id or uuid.uuid4().hex
    try:
        with transaction(conn):
            conn.execute(
                f"INSERT INTO {FEDERATION_GRANTS_TABLE} (grant_id, peer_install_id, public_key, fid, label, "
                "scopes, remote_grant_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (grant_id, peer_install_id, public_key, fid, label, ",".join(scopes),
                 remote_grant_id, utc_now()))
    except sqlite3.IntegrityError:
        raise GrantError("grant_exists", "that peer already holds a live grant") from None
    return get_grant(conn, grant_id)  # type: ignore[return-value]


def get_grant(conn: sqlite3.Connection, grant_id: str) -> Optional[Grant]:
    row = conn.execute(f"SELECT {_COLUMNS} FROM {FEDERATION_GRANTS_TABLE} WHERE grant_id = ?",
                       (str(grant_id)[:64],)).fetchone()
    return _hydrate(row) if row else None


def get_live(conn: sqlite3.Connection, grant_id: str) -> Optional[Grant]:
    grant = get_grant(conn, grant_id)
    return grant if grant and not grant.revoked else None


def live_for_peer(conn: sqlite3.Connection, peer_install_id: str) -> Optional[Grant]:
    row = conn.execute(f"SELECT {_COLUMNS} FROM {FEDERATION_GRANTS_TABLE} "
                       "WHERE peer_install_id = ? AND revoked_at IS NULL", (peer_install_id,)).fetchone()
    return _hydrate(row) if row else None


def list_grants(conn: sqlite3.Connection) -> List[Grant]:
    return [_hydrate(r) for r in conn.execute(
        f"SELECT {_COLUMNS} FROM {FEDERATION_GRANTS_TABLE} ORDER BY created_at DESC, grant_id")]


def revoke(conn: sqlite3.Connection, grant_id: str) -> bool:
    with transaction(conn):
        cur = conn.execute(f"UPDATE {FEDERATION_GRANTS_TABLE} SET revoked_at = ? "
                           "WHERE grant_id = ? AND revoked_at IS NULL", (utc_now(), str(grant_id)[:64]))
    return cur.rowcount == 1


def delete_grant(conn: sqlite3.Connection, grant_id: str) -> bool:
    with transaction(conn):
        cur = conn.execute(f"DELETE FROM {FEDERATION_GRANTS_TABLE} WHERE grant_id = ?",
                           (str(grant_id)[:64],))
    return cur.rowcount == 1


def set_scopes(conn: sqlite3.Connection, grant_id: str, scopes: Tuple[str, ...]) -> bool:
    if not scopes or not set(scopes) <= KNOWN_SCOPES:
        raise GrantError("scope_unknown", "an unknown scope was requested")
    wanted = ",".join(sorted(set(scopes), key=lambda s: (s != SCOPE_SESSIONS, s)))
    with transaction(conn):
        cur = conn.execute(f"UPDATE {FEDERATION_GRANTS_TABLE} SET scopes = ? "
                           "WHERE grant_id = ? AND revoked_at IS NULL AND scopes != ?",
                           (wanted, str(grant_id)[:64], wanted))
    return cur.rowcount == 1


def rotate_key(conn: sqlite3.Connection, grant_id: str, old_public_key: str, new_public_key: str) -> bool:
    fid = fid_for(decode_public_key(new_public_key))
    with transaction(conn):
        cur = conn.execute(f"UPDATE {FEDERATION_GRANTS_TABLE} SET public_key = ?, fid = ? "
                           "WHERE grant_id = ? AND public_key = ? AND revoked_at IS NULL",
                           (new_public_key, fid, str(grant_id)[:64], old_public_key))
    return cur.rowcount == 1


def touch(conn: sqlite3.Connection, grant_id: str) -> None:
    with transaction(conn):
        conn.execute(f"UPDATE {FEDERATION_GRANTS_TABLE} SET last_seen_at = ? "
                     "WHERE grant_id = ? AND revoked_at IS NULL", (utc_now(), grant_id))
