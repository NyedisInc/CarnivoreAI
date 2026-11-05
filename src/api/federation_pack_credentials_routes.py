
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
from src.core import resource_push
from src.core.pack.machines import capabilities, config_state, restrictions as restrictions_mod
from src.core.pack.relay import codex_target, consent as consent_mod, ledger_sync_store, owner_side, target_side, targets
from src.core.provider_ledger import accounts_store
from src.core.resource_push import topics as resource_topics
from src.core.provider_ledger.credentials import claude_keychain_services

logger = structlog.get_logger()
router = APIRouter(prefix="/federation/pack", tags=["federation"])
capabilities.register(owner_side.CAP_CREDENTIALS)
capabilities.register(owner_side.CAP_CREDENTIALS_CODEX)
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


class CodexCredentialBody(BaseModel):
    """One relayed Codex credential (#2794). ``extra=forbid``: a body carrying a refresh token (or anything else) is refused."""

    model_config = ConfigDict(extra="forbid", repr=False)

    account_key: str = Field(max_length=64)
    profile: str = Field(max_length=80)
    access_token: str = Field(max_length=codex_target.MAX_JWT_CHARS, repr=False)
    id_token: str = Field(max_length=codex_target.MAX_JWT_CHARS, repr=False)
    account_id: str = Field(max_length=128)
    expires_at: int = Field(ge=0, le=10 ** 14)
    plan: Optional[str] = Field(default=None, max_length=32)


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


def _local_codex_reservations() -> Tuple[Set[str], Set[str]]:
    names: Set[str] = set()
    homes: Set[str] = set()
    try:
        accounts = accounts_store.list_accounts(Path(settings.auth_config_file).expanduser())
    except (OSError, ValueError):
        raise target_side.RelayRefused("accounts_unreadable", 503) from None
    for account in accounts:
        names.add(account.id)
        if account.provider == "codex" and account.codex_home:
            home = os.path.expanduser(account.codex_home)
            names.add(os.path.basename(home.rstrip("/")))
            homes.add(os.path.realpath(home))
    return names, homes


def _tell_ledger() -> None:
    resource_push.notify(resource_topics.PROVIDER_LEDGER)
    resource_push.notify(resource_topics.ACCOUNT_SWITCH)


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
    _tell_ledger()
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
    await asyncio.to_thread(ledger_sync_store.forget, principal.grant.peer_install_id, "claude", account_key)
    if removed:
        _tell_ledger()
    return JSONResponse({"ok": True, "removed": removed}, headers=_NO_STORE)


def _receive_codex(principal_id: str, body: CodexCredentialBody) -> int:
    names, homes = _local_codex_reservations()

    def accepted() -> bool:
        return consent_mod.accepts(config_state.default().relay_consent(), principal_id, body.account_key)

    with consent_mod.WRITE_LOCK:
        return codex_target.receive_codex(
            principal_id, body.account_key, body.profile, body.access_token, body.id_token, body.account_id,
            body.expires_at, reserved_names=names, reserved_homes=homes, authorize=accepted)


@router.post("/credentials/codex")
async def receive_codex_credential(request: Request, principal: Principal = Depends(_require_credentials),
                                   _allowed: None = Depends(restrictions_mod.require_peer_allowed(
                                       restrictions_mod.ACTION_RECEIVE_CREDENTIALS))) -> JSONResponse:
    """Write the pushed Codex access token into this machine's Codex relay home (empty refresh token, ever)."""
    if not principal.is_peer or principal.grant is None:
        raise HTTPException(403, {"code": "peer_token_required", "detail": "only a paired computer relays a credential"})
    try:
        body = CodexCredentialBody.model_validate(await request.json())
    except (ValidationError, ValueError):
        raise HTTPException(422, {"code": "bad_credential", "detail": "the credential body is not valid"}) from None
    consent = await asyncio.to_thread(config_state.default().relay_consent)
    if not consent_mod.accepts(consent, principal.grant.peer_install_id, body.account_key):
        logger.info("pack_relay_refused_not_accepted", sender=principal.grant.peer_install_id, account=body.account_key,
                    consent_mode=consent.mode, provider="codex")
        raise HTTPException(403, {"code": owner_side.NOT_ACCEPTED,
                                  "detail": "this computer's owner has not accepted that account from that computer"})
    if await asyncio.to_thread(_is_owner_of, body.account_key):
        raise HTTPException(409, {"code": "relay_owner_conflict",
                                  "detail": "this computer owns that login and does not receive it"})
    try:
        expiry = await asyncio.to_thread(_receive_codex, principal.grant.peer_install_id, body)
    except target_side.RelayRefused as exc:
        raise HTTPException(exc.status, {"code": exc.code, "detail": "the credential was not written"}) from None
    return JSONResponse({"ok": True, "profile": body.profile, "expires_at": expiry}, headers=_NO_STORE)


@router.delete("/credentials/codex/{account_key}")
async def revoke_codex_credential(account_key: str, principal: Principal = Depends(_require_credentials)) -> JSONResponse:
    """Delete the Codex relay auth.json this sender wrote (only one with its marker and an empty refresh token)."""
    if not principal.is_peer or principal.grant is None:
        raise HTTPException(403, {"code": "peer_token_required", "detail": "only a paired computer revokes a relay"})
    try:
        removed = await asyncio.to_thread(codex_target.revoke_codex, principal.grant.peer_install_id, account_key)
    except target_side.RelayRefused as exc:
        raise HTTPException(exc.status, {"code": exc.code, "detail": "the credential was not removed"}) from None
    await asyncio.to_thread(ledger_sync_store.forget, principal.grant.peer_install_id, "codex", account_key)
    _tell_ledger()
    return JSONResponse({"ok": True, "removed": removed}, headers=_NO_STORE)
