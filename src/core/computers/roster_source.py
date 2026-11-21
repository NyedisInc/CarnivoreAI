
from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import Callable, List, Optional

import structlog

from src.core.computers import store
from src.core.pack.machines.roster_doc import RosterInput
from src.core.computers.tls_identity import pinned_certs
from src.core.federation import grants

log = structlog.get_logger(__name__)


class RosterUnavailable(RuntimeError):
    pass


def build_inputs(open_db: Callable[[], sqlite3.Connection], *, own: RosterInput, own_link_fid: str,
                 relay_id_for: Callable[[str], Optional[str]], laptop_for: Callable[[str], bool]) -> Optional[List[RosterInput]]:
    out = [own]
    try:
        with closing(open_db()) as conn:
            rows = store.members_tls(conn)
            for row in rows:
                grant = grants.live_for_peer(conn, row.peer_install_id)
                certs = pinned_certs([d for d in (row.cert_der, row.next_cert_der) if d], own_link_fid=own_link_fid)
                if grant is None or not certs or certs[0].cert_sha256 != row.cert_sha256:
                    continue
                out.append(RosterInput(
                    install_id=row.peer_install_id, label=grant.label or "", fed_public_key=grant.public_key, cert=certs[0].der,
                    next_cert=certs[1].der if len(certs) > 1 else None, addresses=tuple(row.addresses), link_port=row.link_port,
                    relay_id=relay_id_for(row.peer_install_id), laptop=laptop_for(row.peer_install_id), joined_at=row.joined_at or ""))
    except (sqlite3.Error, grants.GrantError) as exc:
        log.warning("pack_roster_inputs_unreadable", error_type=type(exc).__name__)
        return None
    return out
