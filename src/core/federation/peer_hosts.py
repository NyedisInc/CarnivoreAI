
from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from typing import List, Optional

from src.core.db import transaction
from src.core.hosts import roster_push
from src.core.mcp import family_signals
from src.core.federation.ddl import HOST_KIND_PEER
from src.core.pack.machines import capabilities
from src.core.pack.rollup_import.ddl import purge_rows
from src.core.trail_entry import utc_now

MESH_BACK_KIND = "mesh"
_COLUMNS = ("key, label, ssh_target, ssh_port, peer_install_id, peer_grant_id, peer_fid, peer_protocol, "
            "peer_state, peer_initiator, peer_port, peer_back_kind")


@dataclass(frozen=True)
class PeerRow:

    key: str
    label: str
    ssh_target: str
    ssh_port: Optional[int]
    peer_install_id: str
    peer_grant_id: str
    peer_fid: str
    peer_protocol: Optional[int]
    peer_state: Optional[str]
    initiator: bool
    peer_port: Optional[int]
    back_kind: str


def host_key_for(install_id: str) -> str:
    return "peer-" + hashlib.sha256(install_id.encode()).hexdigest()[:20]


def _hydrate(row) -> PeerRow:
    return PeerRow(key=row[0], label=row[1], ssh_target=row[2] or "", ssh_port=row[3], peer_install_id=row[4],
                   peer_grant_id=row[5] or "", peer_fid=row[6] or "", peer_protocol=row[7], peer_state=row[8],
                   initiator=bool(row[9]), peer_port=row[10], back_kind=row[11] or "unix")


def _write(conn: sqlite3.Connection, *, install_id: str, label: str, grant_id: str, fid: str, initiator: bool,
           ssh_target: str, ssh_port: Optional[int], peer_port: Optional[int], protocol: Optional[int],
           back_kind: str) -> None:
    existing = conn.execute("SELECT key FROM hosts WHERE kind = 'peer' AND peer_install_id = ?", (install_id,)).fetchone()
    key, now = (existing[0] if existing else host_key_for(install_id)), utc_now()
    values = (label[:64] or key, ssh_target, ssh_port, install_id, grant_id, fid, protocol, int(initiator),
              peer_port, now, back_kind)
    if existing is None:
        conn.execute(
            "INSERT INTO hosts (key, label, ssh_target, ssh_port, socket, enabled, kind, peer_install_id, "
            "peer_grant_id, peer_fid, peer_protocol, peer_initiator, peer_port, peer_state, created_at, "
            "updated_at, peer_back_kind) VALUES (?, ?, ?, ?, '', 0, ?, ?, ?, ?, ?, ?, ?, 'disconnected', ?, ?, ?)",
            (key, values[0], ssh_target, ssh_port, HOST_KIND_PEER, install_id, grant_id, fid, protocol,
             int(initiator), peer_port, now, now, back_kind))
    else:
        conn.execute(
            "UPDATE hosts SET label = ?, ssh_target = ?, ssh_port = ?, peer_install_id = ?, "
            "peer_grant_id = ?, peer_fid = ?, peer_protocol = COALESCE(?, peer_protocol), peer_initiator = ?, "
            "peer_port = COALESCE(?, peer_port), updated_at = ?, peer_back_kind = ? WHERE key = ? AND kind = 'peer'",
            (*values, key))


def upsert(conn: sqlite3.Connection, *, install_id: str, label: str, grant_id: str, fid: str, initiator: bool,
           ssh_target: str = "", ssh_port: Optional[int] = None, peer_port: Optional[int] = None,
           protocol: Optional[int] = None, back_kind: str = "unix") -> PeerRow:
    with transaction(conn):
        _write(conn, install_id=install_id, label=label, grant_id=grant_id, fid=fid, initiator=initiator,
               ssh_target=ssh_target, ssh_port=ssh_port, peer_port=peer_port, protocol=protocol, back_kind=back_kind)
    family_signals.invalidate("pack")
    roster_push.announce()
    return get(conn, install_id)  # type: ignore[return-value]


def upsert_mesh(conn: sqlite3.Connection, *, install_id: str, label: str, grant_id: str, fid: str) -> Optional[PeerRow]:
    with transaction(conn):
        existing = conn.execute("SELECT peer_back_kind FROM hosts WHERE kind = 'peer' AND peer_install_id = ?",
                                (install_id,)).fetchone()
        if existing is not None and (existing[0] or "unix") != MESH_BACK_KIND:
            return None
        _write(conn, install_id=install_id, label=label, grant_id=grant_id, fid=fid, initiator=False, ssh_target="",
               ssh_port=None, peer_port=None, protocol=None, back_kind=MESH_BACK_KIND)
    family_signals.invalidate("pack")
    roster_push.announce()
    return get(conn, install_id, include_mesh=True)


def get(conn: sqlite3.Connection, install_id: str, include_mesh: bool = False) -> Optional[PeerRow]:
    where = "" if include_mesh else f" AND COALESCE(peer_back_kind, '') != '{MESH_BACK_KIND}'"
    row = conn.execute(f"SELECT {_COLUMNS} FROM hosts WHERE kind = 'peer' AND peer_install_id = ?{where}",
                       (install_id,)).fetchone()
    return _hydrate(row) if row else None


def list_peers(conn: sqlite3.Connection, include_mesh: bool = False) -> List[PeerRow]:
    where = "" if include_mesh and capabilities.mesh_on() else f" AND COALESCE(peer_back_kind, '') != '{MESH_BACK_KIND}'"
    return [_hydrate(r) for r in conn.execute(f"SELECT {_COLUMNS} FROM hosts WHERE kind = 'peer'{where} ORDER BY key")]


def set_state(conn: sqlite3.Connection, install_id: str, state: str, protocol: Optional[int] = None) -> None:
    with transaction(conn):
        conn.execute("UPDATE hosts SET peer_state = ?, peer_protocol = COALESCE(?, peer_protocol), updated_at = ? "
                     "WHERE kind = 'peer' AND peer_install_id = ?", (state, protocol, utc_now(), install_id))
    roster_push.announce()


def set_mesh_state(conn: sqlite3.Connection, install_id: str, state: str) -> None:
    with transaction(conn):
        conn.execute("UPDATE hosts SET peer_state = ?, updated_at = ? WHERE kind = 'peer' AND peer_install_id = ? "
                     "AND peer_back_kind = ?", (state, utc_now(), install_id, MESH_BACK_KIND))
    roster_push.announce()


def set_initiator(conn: sqlite3.Connection, install_id: str, initiator: bool) -> bool:
    with transaction(conn):
        changed = conn.execute("UPDATE hosts SET peer_initiator = ?, updated_at = ? WHERE kind = 'peer' AND peer_install_id = ?",
                               (int(initiator), utc_now(), install_id)).rowcount > 0
    roster_push.announce()
    return changed


def set_fid(conn: sqlite3.Connection, install_id: str, fid: str) -> None:
    with transaction(conn):
        conn.execute("UPDATE hosts SET peer_fid = ?, updated_at = ? WHERE kind = 'peer' AND peer_install_id = ?",
                     (fid, utc_now(), install_id))
    roster_push.announce()


def delete(conn: sqlite3.Connection, install_id: str, purge: bool = True) -> bool:
    with transaction(conn):
        if purge:
            purge_rows(conn, install_id)
        gone = conn.execute("DELETE FROM hosts WHERE kind = 'peer' AND peer_install_id = ?",
                            (install_id,)).rowcount > 0
    family_signals.invalidate("pack")
    roster_push.announce()
    return gone


def delete_mesh(conn: sqlite3.Connection, install_id: str) -> bool:
    with transaction(conn):
        gone = conn.execute("DELETE FROM hosts WHERE kind = 'peer' AND peer_install_id = ? AND peer_back_kind = ?",
                            (install_id, MESH_BACK_KIND)).rowcount > 0
    family_signals.invalidate("pack")
    roster_push.announce()
    return gone
