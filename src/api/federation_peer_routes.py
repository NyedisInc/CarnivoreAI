
from __future__ import annotations

import asyncio
import hashlib
from contextlib import closing
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from src.api import federation_routes, peer_auth
from src.api.auth import require_auth
from src.core.computers import membership
from src.core.computers.this_label import this_label
from src.core.federation import fed_key, grants, pair_driver, pair_sas, peer_hosts, peer_links, peer_listing, shadow_rows
from src.core.federation.peer_client import PeerClient, PeerRefused, PeerUnreachable, Route
from src.core.federation.peer_dial import BACK_TCP, BACK_UNIX, InitiatorTransport
from src.core.federation.peer_link import LinkDown
from src.core.hosts.ssh_exec import SshArgumentError, SshDestination
from src.core.hosts.ssh_master import SshTransportError

logger = structlog.get_logger()

router = APIRouter(prefix="/federation/peers", tags=["federation"], dependencies=[Depends(require_auth)])


class PairRequest(BaseModel):
    ssh_target: str = Field(max_length=254)
    ssh_port: Optional[int] = Field(default=None, ge=1, le=65535)
    remote_port: int = Field(default=8000, ge=1, le=65535)
    typed_nonce: Optional[str] = Field(default=None, max_length=32)
    typed_code: Optional[str] = Field(default=None, max_length=16)
    same_user: bool = True
    discovered_name: Optional[str] = Field(default=None, max_length=128)


def _error(status: int, code: str, detail: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "detail": detail})


def _links() -> peer_links.PeerLinks:
    if peer_links.LINKS is None:
        raise _error(503, "federation_unavailable", "the peer link service is not running")
    return peer_links.LINKS


def _peer_json(row: peer_hosts.PeerRow, links: peer_links.PeerLinks) -> Dict[str, Any]:
    return {"key": row.key, "label": row.label, "peer_install_id": row.peer_install_id, "fid": row.peer_fid,
            "initiator": row.initiator, "state": links.state(row.peer_install_id), "protocol": row.peer_protocol}


def _pinned_fid(request: Request, name: Optional[str]) -> str:
    service = getattr(request.app.state, "federation_discovery", None)
    if not name or service is None:
        return ""
    seen = next((p for p in service.discovered() if p["name"] == name and p["state"] == "pinned"), None)
    return str(seen["fid"]) if seen and seen.get("fid") else ""


def _transport(links: peer_links.PeerLinks, dest: SshDestination, remote_port: int, same_user: bool) -> InitiatorTransport:
    provisional = "pair-" + hashlib.sha256(f"{dest.target}:{dest.port}".encode()).hexdigest()[:8]

    def make(route: Route) -> PeerClient:
        return PeerClient(route, grant_id="", peer_install_id="", sign=lambda _m: "")

    try:
        return InitiatorTransport(host_key=provisional, dest=dest, remote_port=remote_port,
                                  listener_path=links._listener, make_client=make,
                                  back_kind=BACK_UNIX if same_user else BACK_TCP)
    except (SshArgumentError, SshTransportError) as exc:
        raise _error(400, "link_socket_unusable", str(exc)[:200]) from None


@router.post("/pair")
async def pair(body: PairRequest, request: Request) -> Dict[str, Any]:
    links = _links()
    try:
        dest = SshDestination(body.ssh_target, body.ssh_port)
    except SshArgumentError as exc:
        raise _error(400, "ssh_target_invalid", str(exc)) from None
    typed = (pair_driver.TypedCode(body.typed_nonce, body.typed_code)
             if body.typed_nonce and body.typed_code else None)
    pinned = await pair_driver.host_key_pinned(dest)
    expected_fid = _pinned_fid(request, body.discovered_name)
    try:
        key = await links._signer()
    except fed_key.DeviceKeyUnavailable:
        raise _error(503, "federation_key_unavailable", "the login keychain did not answer") from None
    with closing(peer_auth.open_db()) as conn:
        install_id = peer_auth.read_install_id(conn)
    transport = _transport(links, dest, body.remote_port, body.same_user)
    try:
        pending = await pair_driver.pair(
            transport=transport, open_db=peer_auth.open_db, install_id=install_id or "", key=key,
            label=this_label(), remote_port=body.remote_port, pinned_before=pinned,
            fid_matches_pinned=bool(expected_fid), expected_fid=expected_fid, typed=typed)
    except pair_driver.NeedsTypedCode as exc:
        raise _error(409, "typed_code_required", exc.reason) from None
    except pair_driver.PairingFailed as exc:
        raise _error(400, exc.code, str(exc)) from None
    except (LinkDown, SshTransportError, PeerUnreachable, PeerRefused) as exc:
        raise _error(502, "peer_unreachable", str(exc)[:200]) from None
    finally:
        await transport.close()
    pair_sas.INITIATING.add(pending.nonce, proof=pending.proof, sas=pending.sas, label=pending.answer.get("label", ""),
                            fid=pending.answer["fid"], pending=pending, dest=dest, remote_port=body.remote_port,
                            same_user=body.same_user)
    return {"pending": True, "nonce": pending.nonce, "sas": pending.sas, "label": pending.answer.get("label", ""),
            "fid": pending.answer["fid"], "proof": pending.proof, "peer_owner_confirms": pending.proof == "typed",
            "expires_in": pair_sas.PENDING_TTL_SECONDS}


class ConfirmRequest(BaseModel):
    nonce: str = Field(max_length=64)
    match: bool


@router.post("/pair/confirm")
async def pair_confirm(body: ConfirmRequest) -> Dict[str, Any]:
    links = _links()
    held = pair_sas.INITIATING.get(body.nonce)
    if held is None:
        raise _error(404, "pair_pending_gone", "this pairing expired or was already answered; start it again")
    pending: pair_driver.PairPending = held.data["pending"]
    try:
        key = await links._signer()
    except fed_key.DeviceKeyUnavailable:
        raise _error(503, "federation_key_unavailable", "the login keychain did not answer") from None
    dest, remote_port = held.data["dest"], held.data["remote_port"]
    transport = _transport(links, dest, remote_port, held.data["same_user"])
    if not body.match:
        pair_sas.INITIATING.pop(body.nonce)
        try:
            await pair_driver.finish(transport=transport, key=key, nonce=body.nonce, accept=False)
        except (pair_driver.PairingFailed, LinkDown, SshTransportError, PeerUnreachable, PeerRefused) as exc:
            logger.info("federation_pair_cancel_peer_unreached", error_type=type(exc).__name__)
        finally:
            await transport.close()
        return {"cancelled": True}
    try:
        await pair_driver.finish(transport=transport, key=key, nonce=body.nonce, accept=True)
        result = await pair_driver.activate(pending=pending, dest=dest, back_kind=transport.back_kind,
                                            open_db=peer_auth.open_db, remote_port=remote_port)
    except pair_driver.PairingFailed as exc:
        if exc.code == "pair_pending_gone":
            pair_sas.INITIATING.pop(body.nonce)
        raise _error(404 if exc.code == "pair_pending_gone" else 400, exc.code, str(exc)) from None
    except (LinkDown, SshTransportError, PeerUnreachable, PeerRefused) as exc:
        raise _error(502, "peer_unreachable", str(exc)[:200]) from None
    finally:
        await transport.close()
    pair_sas.INITIATING.pop(body.nonce)
    with closing(peer_auth.open_db()) as conn:
        row = peer_hosts.get(conn, result.peer_install_id)
    await links.start_initiator(row)  # type: ignore[arg-type]
    return _peer_json(row, links)  # type: ignore[arg-type]


@router.get("")
async def list_peers() -> List[Dict[str, Any]]:
    """Every paired Mac with its live link state."""
    links = _links()

    def read():
        with closing(peer_auth.open_db()) as conn:
            return peer_hosts.list_peers(conn)

    return [_peer_json(r, links) for r in await run_in_threadpool(read)]


@router.delete("/{key}")
async def unpair(key: str) -> Dict[str, bool]:
    """End the pairing: tell the peer to drop its grant (best effort), delete ours and the host row."""
    links = _links()

    def find():
        with closing(peer_auth.open_db()) as conn:
            row = next((r for r in peer_hosts.list_peers(conn) if r.key == key), None)
            return row, (grants.live_for_peer(conn, row.peer_install_id) if row else None)

    row, grant = await run_in_threadpool(find)
    if row is None:
        raise _error(404, "peer_not_found", "no paired computer with that key")
    make = await links._client_factory(row.peer_grant_id, row.peer_install_id, grant.public_key if grant else None)
    link_route = links._transports.get(row.peer_install_id)
    if grant is not None and link_route is not None and links.state(row.peer_install_id) == "connected":
        try:
            await make(Route("unix", link_route.out_path)).request("DELETE", "/federation/grants/self")
        except (PeerUnreachable, PeerRefused):
            logger.info("federation_unpair_peer_unreached", peer=row.peer_install_id[:8])
    await links.remove(row.peer_install_id)

    def drop():
        with closing(peer_auth.open_db()) as conn:
            if grant is not None:
                grants.delete_grant(conn, grant.grant_id)
            shadow_rows.remove_peer(conn, row.key)
            peer_hosts.delete(conn, row.peer_install_id)

    await run_in_threadpool(drop)
    peer_listing.forget(row.peer_install_id)
    if grant is not None:
        await federation_routes.peer_sockets.close_grant(grant.grant_id)
    await membership.on_peer_removed(row.peer_install_id)
    return {"unpaired": True}
