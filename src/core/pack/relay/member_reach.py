
from __future__ import annotations

import asyncio
import sqlite3
import time
from contextlib import closing
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import structlog

from src.core.computers import direction, mesh_choice
from src.core.federation import mesh_peers, peer_links
from src.core.pack.machines import capabilities as caps_mod
from src.core.pack.machines import roster_v2
from src.core.pack.machines import runtime as machines_runtime
from src.core.pack.machines.exchange import post_via
from src.core.pack.relay import login_gate, targets
from src.core.pack.relay.owner_side import PeerFn, PostFn

log = structlog.get_logger(__name__)

MAX_DIALS_PER_PASS = 4
DIAL_BACKOFF_SECONDS = 300.0
_dialed: Dict[str, float] = {}
_READ_ERRORS = (OSError, ValueError, sqlite3.Error)


def held_v2() -> Optional[roster_v2.RosterV2]:
    if not caps_mod.mesh_on():
        return None
    wired = machines_runtime.wiring()
    if wired is None:
        return None
    try:
        held = wired.runtime.custody.held_lists()
    except _READ_ERRORS as exc:
        log.warning("pack_relay_member_ids_unreadable", error_type=type(exc).__name__)
        return None
    lst = held[0] if held else None
    return lst if isinstance(lst, roster_v2.RosterV2) else None


def ids_in(lst: roster_v2.RosterV2) -> List[str]:
    wired = machines_runtime.wiring()
    if wired is None:
        return []
    return [iid for iid in mesh_choice.eligible_ids(lst, wired.runtime.install_id) if not direction.listed_one_way(lst, iid)]


def listed_ids_held() -> Optional[List[str]]:
    lst = held_v2()
    wired = machines_runtime.wiring()
    if lst is None or wired is None:
        return None
    me = wired.runtime.install_id
    return [m.install_id for m in lst.computers if m.install_id != me and not direction.listed_one_way(lst, m.install_id)]


def member_ids_held() -> Optional[List[str]]:
    lst = held_v2()
    return None if lst is None else ids_in(lst)


_LAST_GOOD: Optional[Tuple[str, List[str]]] = None


def list_state() -> Tuple[str, Optional[roster_v2.RosterV2]]:
    if not caps_mod.mesh_on():
        return "off", None
    wired = machines_runtime.wiring()
    if wired is None:
        return "unwired", None
    custody = wired.runtime.custody
    try:
        held = custody.held_lists()
        lst = held[0] if held else None
        if isinstance(lst, roster_v2.RosterV2):
            return "ok", lst
        return ("unknown" if custody.roster_v2() is not None else "none"), None
    except _READ_ERRORS as exc:
        log.warning("pack_relay_member_ids_unreadable", error_type=type(exc).__name__)
        return "unknown", None


def list_unknown() -> bool:
    return list_state()[0] == "unknown"


def member_ids() -> List[str]:
    global _LAST_GOOD
    state, lst = list_state()
    if state == "ok" and lst is not None:
        ids = ids_in(lst)
        _LAST_GOOD = (lst.alpha, ids)
        return list(ids)
    cached = _LAST_GOOD
    if state == "unknown" and cached is not None:
        wired = machines_runtime.wiring()
        try:
            if wired is not None and wired.runtime.custody.settings().master_install_id == cached[0]:
                return list(cached[1])
        except _READ_ERRORS as exc:
            log.warning("pack_relay_member_ids_unreadable", error_type=type(exc).__name__)
            return []
    _LAST_GOOD = None
    return []


def _member_caps(iid: str) -> Optional[List[str]]:
    reg = mesh_peers.REGISTRY
    if not caps_mod.mesh_on() or reg is None:
        return None
    return reg.capabilities(iid)


def lookup(links_getter: Callable[[], Optional[peer_links.PeerLinks]]) -> PeerFn:
    def peer(install_id: str) -> Optional[Tuple[PostFn, List[str]]]:
        links = links_getter()
        client = links.client(install_id) if links is not None else None
        if client is not None:
            return post_via(client, 10.0), links.capabilities(install_id)
        member = _member_caps(install_id)
        reg = mesh_peers.REGISTRY
        client = reg.peek(install_id) if member is not None else None
        if member is None or client is None:
            return None
        send = post_via(client, 10.0)

        async def post(method: str, path: str, body: Optional[dict] = None) -> Tuple[int, Any]:
            reg.touch(install_id)
            return await send(method, path, body)
        return post, member
    return peer


def caps_of(links_getter: Callable[[], Optional[peer_links.PeerLinks]]) -> Callable[[str], List[str]]:
    def caps(install_id: str) -> List[str]:
        links = links_getter()
        if links is not None and links.client(install_id) is not None:
            return list(links.capabilities(install_id))
        member = _member_caps(install_id)
        if member is not None:
            return member
        return list(links.capabilities(install_id)) if links is not None else []
    return caps


def gate_caps_of(links_getter: Callable[[], Optional[peer_links.PeerLinks]]) -> Callable[[str], List[str]]:
    plain = caps_of(links_getter)

    def caps(install_id: str) -> List[str]:
        if not caps_mod.mesh_on():
            return plain(install_id)
        links = links_getter()
        if (links is not None and links.client(install_id) is not None) or _member_caps(install_id) is not None:
            return plain(install_id)
        return [caps_mod.CAP_CREDENTIALS_MESH]
    return caps


def allows(install_id: str) -> Optional[bool]:
    heard = machines_runtime.peer_restriction(install_id, "may_receive_credentials")
    if heard is not None or not caps_mod.mesh_on():
        return heard
    member = _member_caps(install_id)
    return None if member is None else caps_mod.CAP_CREDENTIALS_MESH in member


def _due(open_db: Callable[[], sqlite3.Connection], links: Optional[peer_links.PeerLinks], account_key: str, expiry_ms: int, now: float,
         dialed: Dict[str, float], accepts: Optional[Callable[[str, str], bool]] = None) -> List[str]:
    ids = [iid for iid in member_ids() if (links is None or links.client(iid) is None) and _member_caps(iid) is None
           and now - dialed.get(iid, -DIAL_BACKOFF_SECONDS) >= DIAL_BACKOFF_SECONDS]
    ids = [i for i in ids if accepts is None or accepts(i, account_key)]
    if not ids:
        return []
    approved = login_gate.gate(open_db, caps_of=lambda _iid: [caps_mod.CAP_CREDENTIALS_MESH])
    with closing(open_db()) as conn:
        if not targets.effective_on(conn, account_key):
            return []
        rows = {r.target_install_id: r for r in targets.enabled_for(conn, account_key) if r.target_install_id in ids}
        refused = {r.target_install_id for r in targets.list_all(conn) if r.account_key == account_key and r.state in ("refused", "off")}
    out = []
    for iid in ids:
        row = rows.get(iid)
        if iid in refused or (row is not None and row.state == "pushed" and row.last_expiry_pushed is not None and row.last_expiry_pushed >= expiry_ms):
            continue
        if approved(iid):
            out.append(iid)
    return out[:MAX_DIALS_PER_PASS]


async def dial_due(open_db: Callable[[], sqlite3.Connection], links_getter: Callable[[], Optional[peer_links.PeerLinks]], account_key: str,
                   provider: str, expiry_ms: int, accepts: Optional[Callable[[str, str], bool]] = None) -> None:
    if not caps_mod.mesh_on() or mesh_peers.REGISTRY is None:
        return
    try:
        now = time.monotonic()
        due = await asyncio.to_thread(_due, open_db, links_getter(), account_key, expiry_ms, now, dict(_dialed), accepts)
        for iid in due:
            _dialed[iid] = now
        results: Sequence[object] = await asyncio.gather(*(mesh_peers.connect(links_getter(), iid) for iid in due), return_exceptions=True)
    except Exception as exc:  # noqa: BLE001
        log.warning("pack_relay_dial_failed", provider=provider, error_type=type(exc).__name__)
        return
    for result in results:
        if isinstance(result, BaseException):
            log.info("pack_relay_dial_error", provider=provider, error_type=type(result).__name__)


def via_member(links_getter: Callable[[], Optional[peer_links.PeerLinks]]) -> Callable[[str], bool]:
    def member(install_id: str) -> bool:
        if not caps_mod.mesh_on():
            return False
        links = links_getter()
        if links is not None and links.client(install_id) is not None:
            return False
        return _member_caps(install_id) is not None
    return member
