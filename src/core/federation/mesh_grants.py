
from __future__ import annotations

import hashlib
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from typing import Any, FrozenSet, Optional

import structlog
from fastapi.concurrency import run_in_threadpool

from src.core.computers import direction, mesh, mesh_choice
from src.core.federation import mesh_powers
from src.core.federation.fed_key import fid_for
from src.core.federation.grants import Grant, SCOPE_REPLICA, SCOPE_SESSIONS, decode_public_key
from src.core.pack.machines import capabilities, config_state, restrictions as restrictions_mod
from src.core.pack.machines.roster_v2 import RosterV2

log = structlog.get_logger(__name__)

_ID_DOMAIN = b"carnivore mesh grant v2\0"
_DATA_ERRORS = (sqlite3.Error, OSError, ValueError)


@dataclass(frozen=True)
class MeshGrant(Grant):

    powers: FrozenSet[str] = frozenset()
    one_way: bool = False
    generation: int = 0
    mesh_scopes: FrozenSet[str] = frozenset()
    issuer: str = ""
    cert_sha: str = ""

    def allows(self, scope: str) -> bool:
        return False


def grant_id_for(issuer: str, peer: str, fed_public_key: str, cert_sha: str) -> str:
    digest = hashlib.sha256(_ID_DOMAIN + issuer.encode() + b"\0" + peer.encode() + b"\0" + fed_public_key.encode() + b"\0" + cert_sha.encode()).hexdigest()
    return "mesh-" + digest[:40]


def derive(lst: Any, *, self_iid: str, peer_iid: str, cert_sha: str, restrictions: restrictions_mod.Restrictions, has_replica: bool) -> Optional[MeshGrant]:
    if not capabilities.mesh_on() or not isinstance(lst, RosterV2) or peer_iid not in mesh_choice.eligible_ids(lst, self_iid):
        return None
    entry = lst.entry(peer_iid)
    if entry is None or cert_sha not in entry.shas():
        return None
    one_way = direction.listed_one_way(lst, peer_iid)
    if one_way:
        powers, scopes = frozenset({mesh_powers.MESH_LINK}), {SCOPE_SESSIONS}
    else:
        powers, scopes = mesh_powers.ALL_POWERS, {SCOPE_SESSIONS, "machine"}
        if SCOPE_REPLICA in restrictions_mod.scopes_for(restrictions, tracks_master=False):
            scopes.add(SCOPE_REPLICA)
        own = lst.entry(self_iid)
        if "credentials" in restrictions_mod.scopes_for(restrictions, tracks_master=False) and own is not None and own.may_receive_logins \
                and not direction.listed_one_way(lst, self_iid):
            scopes.add("credentials")
        if direction.listed_one_way(lst, self_iid):
            powers = powers - {mesh_powers.MESH_JOBS}
    return MeshGrant(grant_id=grant_id_for(self_iid, peer_iid, entry.fed_public_key, cert_sha), peer_install_id=peer_iid, public_key=entry.fed_public_key,
                     fid=fid_for(decode_public_key(entry.fed_public_key)), label=entry.label, scopes=(), remote_grant_id=None,
                     created_at=str(lst.issued_at), last_seen_at=None, revoked_at=None, powers=powers, one_way=one_way, generation=lst.generation,
                     mesh_scopes=frozenset(scopes), issuer=self_iid, cert_sha=cert_sha)


def _read_local(peer_iid: str) -> Optional[tuple]:
    from src.api import peer_auth

    with closing(peer_auth.open_db()) as conn:
        own = peer_auth.read_install_id(conn)
        if not own:
            return None
        row = conn.execute("SELECT 1 FROM project_replicas WHERE install_id = ? LIMIT 1", (peer_iid,)).fetchone()
    return own, config_state.default().restrictions(), row is not None


async def current(peer_iid: str) -> Optional[MeshGrant]:
    pin = mesh.trusted_pin(peer_iid)
    if pin is None:
        return None
    lst, sha = pin
    try:
        local = await run_in_threadpool(_read_local, peer_iid)
    except _DATA_ERRORS as exc:
        log.warning("mesh_grant_read_failed", error_type=type(exc).__name__)
        return None
    if local is None:
        return None
    own, restrictions, has_replica = local
    return derive(lst, self_iid=own, peer_iid=peer_iid, cert_sha=sha, restrictions=restrictions, has_replica=has_replica)
