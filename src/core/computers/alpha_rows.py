
from __future__ import annotations

import sqlite3
from typing import Dict, Optional, Tuple

import structlog

from src.core.computers import store
from src.core.computers.tls_identity import pinned_certs
from src.core.pack.machines.roster_doc import Roster, RosterComputer
from src.core.trail_entry import utc_now

log = structlog.get_logger(__name__)


def rewrite_rows(conn: sqlite3.Connection, *, own_iid: str, own_link_fid: str, own_link_port: int, roster: Roster, new_alpha: str) -> int:
    wanted: Dict[str, Tuple[str, RosterComputer]] = {}
    if new_alpha == own_iid:
        wanted = {e.install_id: ("member", e) for e in roster.computers if e.install_id != own_iid}
    elif roster.entry(new_alpha) is not None:
        wanted = {new_alpha: ("main", roster.entry(new_alpha))}  # type: ignore[dict-item]
    before = {r.peer_install_id: r for r in store.list_rows(conn)}
    for iid, row in before.items():
        if row.transport == "tls" and iid not in wanted:
            store.delete(conn, iid)
    written = 0
    for iid, (role, entry) in wanted.items():
        certs = pinned_certs(entry.ders(), own_link_fid=own_link_fid)
        if not certs:
            log.warning("alpha_rows_cert_not_pinned", iid=iid[:8])
            continue
        old: Optional[store.LinkRow] = before.get(iid)
        nxt = certs[1] if len(certs) > 1 else None
        store.put(conn, store.LinkRow(
            iid, role, "tls", "", join_kind=old.join_kind if old else "migrate", cert_der=certs[0].der, cert_sha256=certs[0].cert_sha256,
            link_fid=certs[0].link_fid, next_cert_der=nxt.der if nxt else None, next_cert_sha256=nxt.cert_sha256 if nxt else None,
            addresses=tuple(entry.addresses), link_port=own_link_port if role == "main" else entry.link_port,
            inbound_control=old.inbound_control if old else 1, joined_at=old.joined_at if old and old.joined_at else utc_now(),
            first_link_at=old.first_link_at if old else None, last_link_at=old.last_link_at if old else None))
        written += 1
    return written
