
from __future__ import annotations

import asyncio
import sqlite3
from contextlib import closing
from typing import Any, List, Optional, Tuple

import structlog

from src.core.pack.jobs.types import JobError
from src.core.pack.transport import blobs

log = structlog.get_logger(__name__)

JOB_CONNECT_SECONDS = 3.0
UNREACHABLE = "{label} cannot be reached from this computer right now"
NOT_CONNECTED = "that computer is not connected"


def on() -> bool:
    from src.core.federation import mesh_peers
    from src.core.pack.machines import capabilities

    return capabilities.mesh_on() and mesh_peers.REGISTRY is not None


class _MemberClient:

    def __init__(self, client: Any) -> None:
        self._client = client

    async def request(self, method: str, path: str, **kw: Any) -> Any:
        from src.core.federation.peer_client import PeerUnreachable

        reply = await self._client.request(method, path, **kw)
        if reply.status_code == 401:
            raise PeerUnreachable("passing")
        if reply.status_code == 403:
            try:
                detail = reply.json().get("detail")
            except (ValueError, AttributeError):
                detail = None
            if not (isinstance(detail, dict) and detail.get("code")):
                raise PeerUnreachable("passing")
        return reply


def client_for(iid: str, *, members: bool = True) -> Optional[Any]:
    from src.core.federation import mesh_peers, peer_links

    links = peer_links.LINKS
    star = links.client(iid) if links is not None else None
    if star is not None or not members or not on():
        return star
    client = mesh_peers.REGISTRY.client(iid)
    return None if client is None else _MemberClient(client)


def copy_refusal(iid: str, label: str) -> Optional[Tuple[int, str, str]]:
    from src.core.computers import direction, mesh_choice
    from src.core.federation import peer_links
    from src.core.pack.machines import runtime as machines_runtime
    from src.core.pack.relay import member_reach

    if not on():
        return None
    if peer_links.LINKS is not None and peer_links.LINKS.client(iid) is not None:
        return None
    lst = member_reach.held_v2()
    wired = machines_runtime.wiring()
    if lst is None or wired is None:
        return 502, "member_list_unreadable", f"the list of computers cannot be read here, so {label} cannot take a copy right now"
    entry = lst.entry(iid)
    if entry is not None and direction.listed_one_way(lst, iid):
        return 409, direction.REFUSAL_CODE, f"{label} is set to one way and holds no replicas"
    switch = mesh_choice.own_switch(lst, wired.runtime.install_id)
    if switch == "alpha":
        return 502, "machine_unreachable", UNREACHABLE.format(label=label)
    if switch != "on":
        return 502, "own_link_off", "this computer's link switch is off, so it cannot copy to another member"
    if entry is None:
        return 502, "member_not_listed", f"{label} is not on the list of computers"
    if iid in (lst.alpha, wired.runtime.install_id):
        return 502, "machine_unreachable", UNREACHABLE.format(label=label)
    if not entry.mesh:
        return 502, "member_not_mesh", f"{label} runs a version that does not take copies from another member"
    if not entry.link_peers:
        return 502, "member_link_off", f"{label} has its link switch off, so it cannot take a copy from another member"
    return None


def caps_for(iid: str) -> List[str]:
    from src.core.federation import mesh_peers, peer_links

    links = peer_links.LINKS
    star_live = links is not None and links.client(iid) is not None
    star = list(links.capabilities(iid)) if links is not None else []
    if star_live or not on():
        return star
    return mesh_peers.REGISTRY.capabilities(iid) or star


def _row(iid: str) -> Any:
    from src.api import peer_auth
    from src.core.federation import peer_hosts

    try:
        with closing(peer_auth.open_db()) as conn:
            return peer_hosts.get(conn, iid, include_mesh=True)
    except sqlite3.Error as exc:
        log.info("pack_member_row_unreadable", error_type=type(exc).__name__)
        return None


async def connect_for(iid: str) -> Tuple[Optional[Any], str]:
    from src.core.federation import mesh_peers, peer_hosts, peer_links

    links = peer_links.LINKS
    star = links.client(iid) if links is not None else None
    if star is not None:
        return star, ""
    if not on():
        return None, NOT_CONNECTED
    reg = mesh_peers.REGISTRY
    live = reg.client(iid)
    if live is not None:
        return _MemberClient(live), ""
    row = await asyncio.to_thread(_row, iid)
    if row is not None and row.back_kind != peer_hosts.MESH_BACK_KIND:
        return None, NOT_CONNECTED
    got = await reg.connect(iid, JOB_CONNECT_SECONDS)
    if got is None:
        log.info("pack_member_unreachable", peer=iid[:8])
        return None, UNREACHABLE.format(label=row.label if row is not None else "that computer")
    return _MemberClient(got), ""


def request_for(iid: str, timeout: float) -> blobs.Request:
    async def request(method: str, path: str, **kw: Any) -> Tuple[int, Any]:
        client, words = await connect_for(iid)
        if client is None:
            raise JobError("unreachable", words, 502)
        return await blobs.request_via(client, timeout)(method, path, **kw)

    return request


def hold(iid: str) -> Optional["asyncio.Task[None]"]:
    from src.core.computers import mesh
    from src.core.federation import mesh_peers, peer_links
    from src.core.pack.jobs import target

    if not on() or not iid or target.is_ssh(iid):
        return None
    star = peer_links.LINKS.client(iid) if peer_links.LINKS is not None else None
    if star is not None:
        return None

    async def keep() -> None:
        while True:
            mesh.touch(iid)
            await asyncio.sleep(mesh_peers.TOUCH_SECONDS)

    return asyncio.get_running_loop().create_task(keep(), name="pack-job-keep-alive")


def find_rows() -> List[Any]:
    from src.api import peer_auth
    from src.core.federation import peer_hosts

    with closing(peer_auth.open_db()) as conn:
        return peer_hosts.list_peers(conn, include_mesh=True)
