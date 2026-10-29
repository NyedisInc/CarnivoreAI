
from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from src.api.auth import require_auth
from src.core import resource_push
from src.core.pack.machines import runtime as machines_runtime
from src.core.pack.relay import consent as consent_mod, offers as offers_mod
from src.core.resource_push import topics

logger = structlog.get_logger()
router = APIRouter(prefix="/pack/relay-consent", tags=["pack-relay"], dependencies=[Depends(require_auth)])


class ConsentBody(BaseModel):
    """The answer. ``accounts`` names offer keys (``<sender install id>:<account key>``) and only goes with ``list``."""

    model_config = ConfigDict(extra="forbid")

    mode: str = Field(max_length=8)
    accounts: List[str] = Field(default_factory=list, max_length=consent_mod.MAX_ACCOUNTS)


def _wired() -> machines_runtime.Wiring:
    wired = machines_runtime.wiring()
    if wired is None:
        raise HTTPException(503, {"code": "pack_unavailable", "detail": "the Pack machine layer is not running"})
    return wired


def _read(wired: machines_runtime.Wiring) -> Dict[str, Any]:
    paired = {p.install_id for p in wired.peers()}
    return offers_mod.view(wired.runtime.roster.entries, wired.state.relay_consent(),
                           wired.state.restrictions().may_receive_credentials, paired)


@router.get("")
async def get_consent() -> Dict[str, Any]:
    """The offered accounts, this computer's acceptance (``mode`` null until answered) and the pending keys."""
    return await asyncio.to_thread(_read, _wired())


@router.put("")
async def put_consent(body: ConsentBody) -> Dict[str, Any]:
    """Record the answer. 422 for a bad mode, an empty list (that is ``none``), or an account no computer offers now."""
    wired = _wired()

    def write() -> Dict[str, Any]:
        paired = {p.install_id for p in wired.peers()}
        offered = [o["key"] for o in offers_mod.peer_offers(wired.runtime.roster.entries, paired)]
        try:
            value = consent_mod.answer(body.mode, body.accounts, offered)
        except ValueError as exc:
            raise HTTPException(422, {"code": str(exc), "detail": "that answer is not valid"}) from None
        before = wired.state.relay_consent()
        try:
            with consent_mod.WRITE_LOCK:
                wired.state.save_relay_consent(value)
            wired.runtime.set_restrictions({"may_receive_credentials": value.mode != consent_mod.MODE_NONE}, from_peer=False,
                                           sync_consent=False)
        except (OSError, ValueError) as exc:
            raise HTTPException(500, {"code": "config_unwritable", "detail": type(exc).__name__}) from None
        gone = consent_mod.revoked(before, value, [o["key"] for o in offers_mod.peer_offers(wired.runtime.roster.entries)])
        offers_mod.revoke_keys(gone)
        logger.info("pack_relay_consent_set", mode=value.mode, accepted=len(value.accounts), offered=len(offered))
        return _read(wired)

    out = await asyncio.to_thread(write)
    await asyncio.to_thread(wired.sync_scopes)
    resource_push.notify(topics.PACK_RELAY_OFFER)
    return out
