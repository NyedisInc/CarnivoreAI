
from __future__ import annotations

import hmac
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import structlog
from fastapi import Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.security import HTTPAuthorizationCredentials

from src.api.auth import require_auth, security
from src.core.computers import direction
from src.core.db import DatastoreUnreadableError, db_path_for, get_meta
from src.core.db_reuse.core_read import lend_pooled_or_raise
from src.core.db_models import META_INSTALL_ID
from src.core.federation import grants, peer_token
from src.core.pack.machines import capabilities
from src.core.federation.grants import Grant

logger = structlog.get_logger()

_UNAVAILABLE = (DatastoreUnreadableError, sqlite3.DatabaseError, OSError)


@dataclass(frozen=True)
class Principal:

    kind: str
    grant: Optional[Grant] = None

    @property
    def is_peer(self) -> bool:
        return self.kind == "peer"


OWNER = Principal("owner")


def open_db() -> sqlite3.Connection:
    from src.config import settings

    return lend_pooled_or_raise(db_path_for(settings.get_state_dir()))


def read_install_id(conn: sqlite3.Connection) -> Optional[str]:
    return get_meta(conn, META_INSTALL_ID)


def _live_grant_for(token: str, scope: str, also: Tuple[str, ...] = ()) -> Grant:
    with closing(open_db()) as conn:
        install_id = read_install_id(conn)
        if not install_id:
            raise peer_token.PeerTokenError("no install")
        claims = peer_token.decode(token, install_id)
        if claims.get("k") == peer_token.MESH_KIND:
            raise _MeshToken(claims)
        grant = grants.get_live(conn, str(claims["sub"]))
    if grant is None:
        raise peer_token.PeerTokenError("grant refused")
    if not any(grant.allows(s) for s in (scope, *also)):
        raise ScopeNotGranted(scope)
    return grant


class _MeshToken(Exception):

    def __init__(self, claims: Dict[str, object]) -> None:
        super().__init__("mesh token")
        self.claims = claims


class ScopeNotGranted(peer_token.PeerTokenError):
    pass


_SCOPE_ACTION = {"replica": "host_agents", "migrate": "receive_projects", "credentials": "receive_credentials",
                 "refresh": "update_carnivore", "global-setup": "receive_global_setup", "pack-ui": "receive_pack_ui"}


def _restriction_refusal(scope: str) -> Optional[HTTPException]:
    from src.core.pack.machines import config_state, restrictions

    action = _SCOPE_ACTION.get(scope)
    if action is None:
        return None
    rule = restrictions.check(config_state.default().restrictions(), action)
    return restrictions.refusal(rule) if rule else None


def _unauthorized() -> HTTPException:
    return HTTPException(status_code=401, detail="Invalid peer token", headers={"WWW-Authenticate": "Bearer"})


def _mesh_refused(why: str, tag: str, method: str, exc: HTTPException) -> HTTPException:
    logger.info("mesh_peer_refused", peer=tag[:8], method=method, why=why)
    return exc


async def _authorize_mesh(claims: Dict[str, object], scope: str, also: Tuple[str, ...], conn: Any) -> Principal:
    from src.core.federation import mesh_grants, mesh_powers

    method = "?"
    tag = getattr(conn, "scope", {}).get("mesh_peer") if conn is not None else None
    if not capabilities.mesh_on():
        raise _mesh_refused("switch", "", method, _unauthorized())
    if not isinstance(tag, str) or not tag:
        raise _mesh_refused("untagged", "", method, _unauthorized())
    method = "WS" if conn.scope.get("type") == "websocket" else str(conn.scope.get("method", "?"))
    power = mesh_powers.power_for(method, conn.url.path)
    if power is None:
        raise _mesh_refused("unclassified", tag, method, HTTPException(status_code=403, detail=_POWER_REFUSED))
    g = await mesh_grants.current(tag)
    if g is None:
        raise _mesh_refused("no_grant", tag, method, _unauthorized())
    if not hmac.compare_digest(str(claims.get("sub", "")), g.grant_id):
        raise _mesh_refused("sub", tag, method, _unauthorized())
    if g.one_way and power != mesh_powers.MESH_LINK:
        raise _mesh_refused("one_way", tag, method, HTTPException(status_code=403, detail={
            "code": direction.REFUSAL_CODE, "detail": "this computer is set to one way: it cannot change anything here"}))
    if power not in g.powers or power not in mesh_powers.OPEN_POWERS:
        raise _mesh_refused("closed", tag, method, HTTPException(status_code=403, detail=_POWER_REFUSED))
    if not any(s in (mesh_powers.POWER_SCOPES[power] & g.mesh_scopes) for s in (scope, *also)):
        refusal = await run_in_threadpool(_restriction_refusal, scope)
        raise _mesh_refused("scope", tag, method, refusal or _unauthorized())
    return Principal("peer", g)


_POWER_REFUSED = {"code": "mesh_power_refused", "detail": "another member computer cannot do that here"}


async def _authorize_peer(token: str, scope: str, also: Tuple[str, ...] = (), *, conn: Any = None) -> Principal:
    try:
        grant = await run_in_threadpool(_live_grant_for, token, scope, also)
    except _MeshToken as m:
        return await _authorize_mesh(m.claims, scope, also, conn)
    except ScopeNotGranted:
        refusal = await run_in_threadpool(_restriction_refusal, scope)
        if refusal is not None:
            raise refusal from None
        raise _unauthorized() from None
    except peer_token.PeerTokenError:
        raise _unauthorized() from None
    except _UNAVAILABLE as exc:
        logger.warning("peer_auth_datastore_unavailable", error_type=type(exc).__name__)
        raise _unauthorized() from None
    if conn is not None and conn.scope.get("mesh_peer") is not None:
        raise _unauthorized()
    return Principal("peer", grant)


def _direction_refusal(path: str, peer_install_id: str) -> Optional[HTTPException]:
    if direction.path_allowed(path):
        return None
    try:
        with closing(open_db()) as conn:
            allowed = direction.inbound_allowed(conn, peer_install_id)
    except _UNAVAILABLE as exc:
        logger.warning("peer_direction_unknown", error_type=type(exc).__name__)
        return HTTPException(status_code=503, detail={"code": "computer_direction_unknown",
                                                      "detail": "the datastore could not say if this computer may control this one"})
    if allowed:
        return None
    return HTTPException(status_code=403, detail={"code": direction.REFUSAL_CODE,
                                                  "detail": "this computer is set to one way: it cannot change anything here"})


async def enforce_direction(path: str, grant: Grant) -> None:
    from src.core.federation.mesh_grants import MeshGrant

    if isinstance(grant, MeshGrant):
        return
    refusal = await run_in_threadpool(_direction_refusal, path, grant.peer_install_id)
    if refusal is not None:
        raise refusal


async def owner_check(request: Request, credentials: Optional[HTTPAuthorizationCredentials]) -> None:
    check: Any = request.app.dependency_overrides.get(require_auth, require_auth)
    result = check(credentials) if check is require_auth else check()
    if hasattr(result, "__await__"):
        await result


async def is_owner(request: Request, credentials: Optional[HTTPAuthorizationCredentials]) -> bool:
    override = request.app.dependency_overrides.get(require_auth)
    if credentials is None and override is None:
        return False
    await owner_check(request, credentials)
    return True


def require_peer(scope: str, also: Tuple[str, ...] = ()):

    async def dependency(request: Request,
                         credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> Principal:
        token = credentials.credentials if credentials else None
        if token and peer_token.is_peer_token(token):
            if request.scope.get("via_link"):
                raise HTTPException(status_code=403, detail="peer tokens are not accepted over the link")
            principal = await _authorize_peer(token, scope, also, conn=request)
            await enforce_direction(request.url.path, principal.grant)
            request.state.peer_grant = principal.grant
            return principal
        await owner_check(request, credentials)
        return OWNER

    dependency.peer_scope = scope  # type: ignore[attr-defined]
    return dependency


require_peer_sessions = require_peer("sessions")
