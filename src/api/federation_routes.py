
from __future__ import annotations

import os
import stat
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field

from src.api import peer_auth
from src.api.auth import require_auth, security
from src.api.peer_auth import Principal, require_peer_sessions
from src.core import version
from src.core.computers import direction, membership, store as computer_links
from src.core.computers.this_label import this_label
from src.core.pack.machines import capabilities
from src.core.federation import (back_route, fed_key, grants, key_rotate, pair_sas, pairing, peer_client, peer_hosts,
                                 peer_links, peer_listing, peer_prove, peer_sockets, peer_token, shadow_rows)
from src.core.federation.peer_client import Route
from src.core.relay_identity.device_key import unb64url
from src.core.federation.grants import Grant, GrantError

logger = structlog.get_logger()

router = APIRouter(prefix="/federation", tags=["federation"])

def fed_dir() -> Path:
    return Path.home() / ".carnivore" / "fed"


_TOKEN_GRANT_WINDOWS = pairing.KeyedWindows(60, 60.0)
_TOKEN_STRANGER_WINDOWS = pairing.KeyedWindows(20, 60.0)
_PROVE_GRANT_WINDOWS = pairing.KeyedWindows(120, 60.0)
_PROVE_STRANGER_WINDOWS = pairing.KeyedWindows(30, 60.0)


def _error(status: int, code: str, detail: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "detail": detail})


def refuse_tls_pairing(peer_install_id: str) -> None:
    row = computer_links.CACHE.get(peer_install_id)
    if row is not None and row.transport == "tls":
        raise _error(409, "computer_linked_tls", "that computer is linked directly; remove it first to pair over ssh")


def _state_dir() -> Path:
    from src.config import settings

    return settings.get_state_dir()



class PairBeginResponse(BaseModel):
    nonce: str
    proof: str
    expires_in: int
    code: Optional[str] = None


class PairCompleteRequest(BaseModel):
    nonce: str = Field(max_length=64)
    code: str = Field(max_length=32)
    install_id: str = Field(max_length=64)
    label: str = Field(default="", max_length=128)
    public_key: str = Field(max_length=64)
    grant_id: str = Field(max_length=64, description="the grant the caller issued to this computer")
    protocol: int


class PairCompleteResponse(BaseModel):
    grant_id: str
    install_id: str
    public_key: str
    fid: str
    label: str
    protocol: int


class TokenRequest(BaseModel):
    grant_id: str = Field(max_length=64)
    ts: int
    nonce: str = Field(max_length=64)
    signature: str = Field(max_length=128)


class TokenResponse(BaseModel):
    token: str
    expires_in: int
    install_id: str


class HelloResponse(BaseModel):
    install_id: str
    label: str
    protocol: int
    protocol_minor: int = 0
    app_version: str
    principal: str
    capabilities: List[str] = Field(default_factory=list)
    restrictions_for_caller: List[str] = Field(default_factory=list)


class LinkRequest(BaseModel):
    kind: str = Field(pattern="^(unix|tcp)$")
    path: Optional[str] = Field(default=None, max_length=512)
    port: Optional[int] = Field(default=None, ge=1, le=65535)
    route_id: Optional[str] = Field(default=None, max_length=64)


class GrantModel(BaseModel):
    grant_id: str
    peer_install_id: str
    fid: str
    label: str
    scopes: List[str]
    created_at: str
    last_seen_at: Optional[str]
    revoked_at: Optional[str]


def _grant_model(g: Grant) -> GrantModel:
    return GrantModel(grant_id=g.grant_id, peer_install_id=g.peer_install_id, fid=g.fid, label=g.label,
                      scopes=list(g.scopes), created_at=g.created_at, last_seen_at=g.last_seen_at,
                      revoked_at=g.revoked_at)


def _local_key(install_id: str):
    return fed_key.load_key(install_id)


async def _db(operation, *args):
    def run():
        with closing(peer_auth.open_db()) as conn:
            return operation(conn, *args)

    try:
        return await run_in_threadpool(run)
    except peer_auth._UNAVAILABLE as exc:
        logger.warning("federation_datastore_unavailable", error_type=type(exc).__name__)
        raise _error(503, "federation_unavailable", "the datastore could not answer") from None


def _install_id(conn: sqlite3.Connection) -> str:
    install_id = peer_auth.read_install_id(conn)
    if not install_id:
        raise _error(503, "federation_unavailable", "this install has no id yet")
    return install_id



@router.post("/pair/begin", response_model=PairBeginResponse)
async def pair_begin(request: Request,
                     credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> PairBeginResponse:
    """Start a pairing here. Owner login only: the typed code is answered for on-screen display."""
    if not await peer_auth.is_owner(request, credentials):
        raise _error(401, "owner_login_required", "sign in on this computer; the ssh step uses the pair socket")
    proof = pairing.PROOF_TYPED
    try:
        offer = await run_in_threadpool(pairing.OFFERS.begin, proof, _state_dir())
    except pairing.RateLimited:
        raise _error(429, "pair_rate_limited", "too many pairing starts, wait a minute") from None
    logger.info("federation_pair_begun", proof=proof)
    return PairBeginResponse(nonce=offer.nonce, proof=proof, expires_in=pairing.TYPED_TTL_SECONDS,
                             code=offer.code)


@router.post("/pair/complete", response_model=PairCompleteResponse)
async def pair_complete(body: PairCompleteRequest) -> PairCompleteResponse:
    """Redeem the code and HOLD the pairing for confirmation (P10). The code is the credential; it is single use.

    No grant exists yet: the pairing waits in ``pair_sas.ACCEPTING`` until its comparison code is confirmed
    (``federation_pending_routes``), so a man in the middle that relayed the code gets nothing by itself.
    """
    if body.protocol != pairing.PROTOCOL_MAJOR:
        raise _error(409, "protocol_mismatch", "the protocol major versions differ")
    refuse_tls_pairing(body.install_id)
    try:
        peer_raw = grants.decode_public_key(body.public_key)
        offer = pairing.OFFERS.redeem(body.nonce, body.code)
    except pairing.PairError:
        raise _error(401, pairing.PairError.code, "the pairing code was not accepted") from None
    except GrantError as exc:
        raise _error(400, exc.code, str(exc)) from None

    def read(conn: sqlite3.Connection) -> str:
        install_id = _install_id(conn)
        old = grants.live_for_peer(conn, body.install_id)
        if old is not None and old.public_key != body.public_key:
            raise _error(409, "peer_identity_changed", "a live grant for that install id holds a different key")
        return install_id

    install_id = await _db(read)
    try:
        key = await run_in_threadpool(_local_key, install_id)
    except fed_key.DeviceKeyUnavailable:
        raise _error(503, "federation_key_unavailable", "the login keychain did not answer") from None
    grant_id = uuid.uuid4().hex
    pair_sas.ACCEPTING.add(
        body.nonce, proof=offer.proof, sas=pair_sas.compute_sas(peer_raw, key.raw_pub, body.nonce),
        label="".join(c for c in body.label if c.isprintable()).strip()[:64], fid=fed_key.fid_for(peer_raw),
        install_id=body.install_id, public_key=body.public_key, grant_id=grant_id,
        remote_grant_id=body.grant_id, accepted=False, owner_ok=False)
    logger.info("federation_pair_pending", proof=offer.proof)
    return PairCompleteResponse(grant_id=grant_id, install_id=install_id,
                                public_key=fed_key.public_key_b64(key), fid=fed_key.fid_for(key.raw_pub),
                                label=this_label(), protocol=pairing.PROTOCOL_MAJOR)



@router.post("/token", response_model=TokenResponse)
async def token(body: TokenRequest, request: Request) -> TokenResponse:
    """Sign a challenge with the grant's key, get a 15 minute peer token. A wrong challenge is 401,
    too many for one grant (or from one client naming unknown grants) is 429."""
    import time

    def refuse():
        return _error(401, "grant_invalid", "the challenge was not accepted")

    client = request.client.host if request.client else "-"

    def mint(conn: sqlite3.Connection):
        install_id = _install_id(conn)
        grant = grants.get_live(conn, body.grant_id)
        window, key = (_TOKEN_STRANGER_WINDOWS, client) if grant is None else (_TOKEN_GRANT_WINDOWS, grant.grant_id)
        if not window.hit(key, time.monotonic()):
            raise _error(429, "token_rate_limited", "too many token requests")
        if grant is None:
            raise refuse()
        try:
            peer_token.verify_challenge(grant, install_id, body.ts, body.nonce, body.signature)
        except peer_token.PeerTokenError:
            raise refuse() from None
        grants.touch(conn, grant.grant_id)
        return install_id, peer_token.mint(grant, install_id)

    install_id, (jwt_token, ttl) = await _db(mint)
    return TokenResponse(token=jwt_token, expires_in=ttl, install_id=install_id)



@router.get("/hello", response_model=HelloResponse)
async def hello(principal: Principal = Depends(require_peer_sessions)) -> HelloResponse:
    """Who this Mac is. Peer or owner. The version gate (F13) reads ``protocol``."""
    install_id = await _db(_install_id)
    restricted: List[str] = []
    if principal.is_peer and principal.grant is not None:
        try:
            if not await _db(direction.inbound_allowed, principal.grant.peer_install_id):
                restricted = [direction.RESTRICTION_ONE_WAY]
        except sqlite3.Error:
            logger.warning("hello_direction_unknown")
    return HelloResponse(install_id=install_id, label=this_label(), protocol=pairing.PROTOCOL_MAJOR,
                         protocol_minor=pairing.PROTOCOL_MINOR,
                         app_version=version.resolve_version(), principal=principal.kind,
                         capabilities=capabilities.names(), restrictions_for_caller=restricted)


def _validate_back_route(grant: Grant, body: LinkRequest) -> Any:
    try:
        return back_route.validate(fed_dir(), grant.grant_id, body.kind, body.path, body.port, body.route_id)
    except back_route.BackRouteInvalid as exc:
        raise _error(400, "link_invalid", str(exc)) from None


@router.post("/link")
async def link(body: LinkRequest, principal: Principal = Depends(require_peer_sessions)) -> Dict[str, bool]:
    """Record where the peer's route back is, after checking it. Peer token only."""
    if not principal.is_peer or principal.grant is None:
        raise _error(400, "peer_token_required", "only a paired computer names a route back")
    if body.kind == "tcp" and (row := computer_links.CACHE.get(principal.grant.peer_install_id)) is not None \
            and row.transport == "tls":
        raise _error(403, "link_tcp_refused", "a computer linked over tls names no tcp route back")
    route = _validate_back_route(principal.grant, body)
    try:
        proven = await peer_client.prove_route(Route(*route), principal.grant.public_key,
                                               principal.grant.peer_install_id,
                                               grant_id=principal.grant.remote_grant_id or "")
    except peer_client.PeerUnreachable:
        proven = False
    if not proven:
        raise _error(400, "link_invalid", "the route back did not prove the paired key")
    if route[0] == "unix":
        prefix = f"in-{principal.grant.grant_id}-"
        sock_dir = Path(os.path.realpath(back_route.socket_dir(fed_dir(), principal.grant.grant_id)))
        for entry in sock_dir.iterdir():
            if entry.name.startswith(prefix) and str(entry) != route[1]:
                try:
                    if stat.S_ISSOCK(os.lstat(entry).st_mode):
                        entry.unlink()
                except OSError:
                    pass
    if peer_links.LINKS is None:
        raise _error(503, "federation_unavailable", "the peer link service is not running")
    await peer_links.LINKS.accept_route(principal.grant, route)
    return {"accepted": True}


class ProveRequest(BaseModel):
    nonce: str = Field(max_length=64)
    grant_id: Optional[str] = Field(default=None, max_length=64)
    route: Optional[str] = Field(default=None, max_length=64)


@router.post("/prove")
async def prove(body: ProveRequest, request: Request) -> Dict[str, str]:
    """Sign a caller's nonce (and, for a tcp back route, that live route's id) with this Mac's federation key."""
    import time

    raw = unb64url(body.nonce, 16)
    if raw is None:
        raise _error(400, "prove_refused", "the nonce was not accepted")
    client = request.client.host if request.client else "-"

    def look(conn: sqlite3.Connection):
        grant = grants.get_live(conn, body.grant_id) if body.grant_id else None
        window, key = (_PROVE_STRANGER_WINDOWS, client) if grant is None else (_PROVE_GRANT_WINDOWS, grant.grant_id)
        return _install_id(conn), window.hit(key, time.monotonic())

    install_id, allowed = await _db(look)
    if not allowed:
        raise _error(429, "prove_rate_limited", "too many proofs asked")
    if body.route and body.route not in peer_prove.LIVE_ROUTES:
        raise _error(404, "route_unknown", "that route is not held here")
    try:
        key = await run_in_threadpool(_local_key, install_id)
    except fed_key.DeviceKeyUnavailable:
        raise _error(503, "federation_key_unavailable", "the login keychain did not answer") from None
    return {"install_id": install_id, "signature": key.sign(peer_prove.prove_message(raw, install_id, body.route or ""))}


WS_RECHECK_SECONDS = 30.0


@router.websocket("/ws")
async def peer_ws(websocket: WebSocket) -> None:
    """A peer's control channel. ``Authorization: Bearer <peer token>``; registered under its grant so a
    revoke closes it with 4412, and the grant is re-read every 30 s. Sends ``{"hello": ...}`` then keeps
    the socket open, answering each text frame with ``{"pong": true}``."""
    import asyncio

    header = websocket.headers.get("authorization", "")
    token = header[7:] if header.lower().startswith("bearer ") else ""
    try:
        if not token or not peer_token.is_peer_token(token):
            raise HTTPException(status_code=401)
        grant = (await peer_auth._authorize_peer(token, "sessions")).grant
    except HTTPException:
        await websocket.close(code=4401)
        return
    await websocket.accept()
    peer_sockets.register(grant.grant_id, websocket)
    try:
        await websocket.send_json({"hello": True})
        next_check = asyncio.get_running_loop().time() + WS_RECHECK_SECONDS
        while True:
            try:
                await asyncio.wait_for(websocket.receive_text(),
                                       timeout=max(0.1, next_check - asyncio.get_running_loop().time()))
                await websocket.send_json({"pong": True})
            except asyncio.TimeoutError:
                pass
            if asyncio.get_running_loop().time() >= next_check:
                next_check = asyncio.get_running_loop().time() + WS_RECHECK_SECONDS
                if await _db(grants.get_live, grant.grant_id) is None:
                    await websocket.close(code=peer_sockets.PEER_REVOKED_CODE, reason=peer_sockets.PEER_REVOKED_REASON)
                    return
    except (WebSocketDisconnect, RuntimeError):
        return
    finally:
        peer_sockets.unregister(grant.grant_id, websocket)



@router.get("/grants", response_model=List[GrantModel], dependencies=[Depends(require_auth)])
async def list_grants() -> List[GrantModel]:
    """Every grant this Mac has issued, revoked ones included. Owner only."""
    return [_grant_model(g) for g in await _db(grants.list_grants)]


def _drop_peer(conn: sqlite3.Connection, grant_id: str, peer_install_id: str) -> None:
    grants.delete_grant(conn, grant_id)
    row = peer_hosts.get(conn, peer_install_id)
    if row is not None:
        shadow_rows.remove_peer(conn, row.key)
        peer_hosts.delete(conn, peer_install_id)


@router.delete("/grants/self")
async def unpair(principal: Principal = Depends(require_peer_sessions)) -> Dict[str, bool]:
    """A paired Mac ends its own grant here (F16 unpair). Peer token only."""
    if not principal.is_peer or principal.grant is None:
        raise _error(400, "peer_token_required", "use the grant id as the owner")
    gid, iid = principal.grant.grant_id, principal.grant.peer_install_id
    await _db(_drop_peer, gid, iid)
    peer_listing.forget(iid)
    if peer_links.LINKS is not None:
        await peer_links.LINKS.remove(iid)
    await peer_sockets.close_grant(gid)
    await membership.on_peer_unpaired(iid)
    return {"unpaired": True}


@router.delete("/grants/{grant_id}", dependencies=[Depends(require_auth)])
async def revoke_grant(grant_id: str) -> Dict[str, Any]:
    """Revoke one grant (F16 A) and close every socket it holds with 4412. Owner only."""
    revoked = await _db(lambda conn: (grants.get_live(conn, grant_id), grants.revoke(conn, grant_id)))
    if not revoked[1]:
        raise _error(404, "grant_not_found", "no live grant with that id")
    if revoked[0] is not None and peer_links.LINKS is not None:
        await peer_links.LINKS.remove(revoked[0].peer_install_id)
    closed = await peer_sockets.close_grant(grant_id)
    if revoked[0] is not None:
        await membership.on_peer_removed(revoked[0].peer_install_id)
    logger.info("federation_grant_revoked", grant=grant_id[:8], sockets_closed=closed)
    return {"revoked": True, "sockets_closed": closed}



class RotateResponse(BaseModel):
    fid: str
    announced: int
    not_announced: int


class AnnounceRequest(BaseModel):
    new_public_key: str = Field(max_length=64)
    signature: str = Field(max_length=128)


@router.post("/key/rotate", response_model=RotateResponse, dependencies=[Depends(require_auth)])
async def rotate_key(request: Request) -> RotateResponse:
    """Mint a new federation key, tell every live peer (signed by the old key) and switch. Owner only.

    ``not_announced`` peers were offline: they must be paired again (``key_rotate`` module docstring).
    """
    install_id = await _db(_install_id)
    live = len([g for g in await _db(grants.list_grants) if not g.revoked])
    try:
        result = await key_rotate.rotate(install_id=install_id, links=peer_links.LINKS, live_grants=live)
    except key_rotate.RotationBusy:
        raise _error(409, "rotation_in_progress", "a key rotation is already running") from None
    except fed_key.DeviceKeyUnavailable:
        raise _error(503, "federation_key_unavailable", "the login keychain did not answer") from None
    discovery = getattr(request.app.state, "federation_discovery", None)
    if discovery is not None:
        discovery.refresh_fid(result["fid"])
    return RotateResponse(**result)


@router.post("/key/announce")
async def announce_key(body: AnnounceRequest, principal: Principal = Depends(require_peer_sessions)) -> Dict[str, bool]:
    """A paired Mac announces its new key, signed by the key pinned in its grant here. Peer token only."""
    if not principal.is_peer or principal.grant is None:
        raise _error(400, "peer_token_required", "only a paired computer announces its key")
    grant = principal.grant
    try:
        key_rotate.verify_announcement(grant, body.new_public_key, body.signature)
    except GrantError as exc:
        raise _error(400, exc.code, str(exc)) from None

    def swap(conn: sqlite3.Connection) -> bool:
        if not grants.rotate_key(conn, grant.grant_id, grant.public_key, body.new_public_key):
            return False
        peer_hosts.set_fid(conn, grant.peer_install_id, fed_key.fid_for(grants.decode_public_key(body.new_public_key)))
        return True

    if not await _db(swap):
        raise _error(409, "rotation_stale", "the grant no longer holds the key that signed this")
    if peer_links.LINKS is not None:
        peer_links.LINKS.pin_peer_key(grant.peer_install_id, body.new_public_key)
    logger.info("federation_peer_key_rotated", grant=grant.grant_id[:8])
    return {"accepted": True}
