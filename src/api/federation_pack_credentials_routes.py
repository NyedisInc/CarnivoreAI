
from __future__ import annotations

import asyncio
import os
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.api.peer_auth import Principal, open_db, require_peer
from src.config import settings
from src.core.pack.machines import capabilities, config_state, restrictions as restrictions_mod
from src.core.pack.relay import consent as consent_mod, owner_side, target_side, targets
from src.core.provider_ledger import accounts_store
from src.core.provider_ledger.credentials import claude_keychain_services

logger = structlog.get_logger()
router = APIRouter(prefix="/federation/pack", tags=["federation"])
capabilities.register(owner_side.CAP_CREDENTIALS)
_require_credentials = require_peer("credentials")
_NO_STORE = {"Cache-Control": "no-store"}


class CredentialBody(BaseModel):
    """One relayed credential. ``extra=forbid`` means a body that carries a refresh token is refused outright."""

    model_config = ConfigDict(extra="forbid", repr=False)

    account_key: str = Field(max_length=64)
    profile: str = Field(max_length=80)
    access_token: str = Field(max_length=1024, repr=False)
    expires_at: int = Field(ge=0, le=10 ** 14)
    scopes: List[str] = Field(default_factory=list, max_length=16)
    subscription_type: Optional[str] = Field(default=None, max_length=64)
    rate_limit_tier: Optional[str] = Field(default=None, max_length=64)


def _is_owner_of(account_key: str) -> bool:
    with closing(open_db()) as conn:
        return targets.is_owner_of(conn, account_key)


def _local_reservations() -> Tuple[Set[str], Set[str]]:
    names: Set[str] = set()
    services: Set[str] = set()
    try:
        accounts = accounts_store.list_accounts(Path(settings.auth_config_file).expanduser())
    except (OSError, ValueError):
        raise target_side.RelayRefused("accounts_unreadable", 503) from None
    for account in accounts:
        names.add(account.id)
        if account.provider == "claude" and account.claude_config_dir:
            names.add(os.path.basename(account.claude_config_dir.rstrip("/")))
            services.update(claude_keychain_services(account.claude_config_dir))
    return names, services


def _receive(principal_id: str, body: CredentialBody) -> int:
    names, services = _local_reservations()

    def accepted() -> bool:
        return consent_mod.accepts(config_state.default().relay_consent(), principal_id, body.account_key)

    with consent_mod.WRITE_LOCK:
        return target_side.receive(
            principal_id, body.account_key, body.profile, body.access_token, body.expires_at, scopes=body.scopes,
            subscription_type=body.subscription_type, rate_limit_tier=body.rate_limit_tier,
            reserved_names=names, reserved_services=services, authorize=accepted)


@router.post("/credentials")
async def receive_credential(request: Request, principal: Principal = Depends(_require_credentials),
                             _allowed: None = Depends(restrictions_mod.require_peer_allowed(
                                 restrictions_mod.ACTION_RECEIVE_CREDENTIALS))) -> JSONResponse:
    """Write the pushed access token and expiry into this machine's relay profile (no refresh token, ever)."""
    if not principal.is_peer or principal.grant is None:
        raise HTTPException(403, {"code": "peer_token_required", "detail": "only a paired computer relays a credential"})
    try:
        body = CredentialBody.model_validate(await request.json())
    except (ValidationError, ValueError):
        raise HTTPException(422, {"code": "bad_credential", "detail": "the credential body is not valid"}) from None
    consent = await asyncio.to_thread(config_state.default().relay_consent)
    if not consent_mod.accepts(consent, principal.grant.peer_install_id, body.account_key):
        logger.info("pack_relay_refused_not_accepted", sender=principal.grant.peer_install_id, account=body.account_key,
                    consent_mode=consent.mode)
        raise HTTPException(403, {"code": owner_side.NOT_ACCEPTED,
                                  "detail": "this computer's owner has not accepted that account from that computer"})
    if await asyncio.to_thread(_is_owner_of, body.account_key):
        raise HTTPException(409, {"code": "relay_owner_conflict",
                                  "detail": "this computer owns that login and does not receive it"})
    try:
        expiry = await asyncio.to_thread(_receive, principal.grant.peer_install_id, body)
    except target_side.RelayRefused as exc:
        raise HTTPException(exc.status, {"code": exc.code, "detail": "the credential was not written"}) from None
    out: Dict[str, Any] = {"ok": True, "profile": body.profile, "expires_at": expiry}
    return JSONResponse(out, headers=_NO_STORE)


@router.delete("/credentials/{account_key}")
async def revoke_credential(account_key: str, principal: Principal = Depends(_require_credentials)) -> JSONResponse:
    """Delete the relay item this sender wrote for the account (only one carrying its relay marker). A tightening, so it
    needs the scope but not the receive restriction."""
    if not principal.is_peer or principal.grant is None:
        raise HTTPException(403, {"code": "peer_token_required", "detail": "only a paired computer revokes a relay"})
    try:
        removed = await asyncio.to_thread(target_side.revoke, principal.grant.peer_install_id, account_key)
    except target_side.RelayRefused as exc:
        raise HTTPException(exc.status, {"code": exc.code, "detail": "the credential was not removed"}) from None
    return JSONResponse({"ok": True, "removed": removed}, headers=_NO_STORE)
