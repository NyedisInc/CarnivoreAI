
from __future__ import annotations

import asyncio
import os
from contextlib import closing
from typing import Any, Set

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from src.api.peer_auth import Principal, open_db, require_peer
from src.core import resource_push
from src.core.pack.machines import capabilities, config_state, restrictions as restrictions_mod
from src.core.pack.relay import consent as consent_mod, ledger_sync_store as store, targets
from src.core.pack.relay.ledger_sync_wire import CAP_LEDGER_STATUS, LedgerSessionsBody, LedgerStatusBody
from src.core.resource_push import topics as resource_topics

logger = structlog.get_logger()
router = APIRouter(prefix="/federation/pack", tags=["federation"])
capabilities.register(CAP_LEDGER_STATUS)
_require_credentials = require_peer("credentials")
_require_machine = require_peer("machine")
_NO_STORE = {"Cache-Control": "no-store"}
_TASKS: Set["asyncio.Task[Any]"] = set()


def _tell_ledger() -> None:
    resource_push.notify(resource_topics.PROVIDER_LEDGER)
    resource_push.notify(resource_topics.ACCOUNT_SWITCH)


def _evaluate_switch(app_state: Any) -> None:
    if os.environ.get("CLOUDE_TEST_MODE"):
        return
    from src.core.account_switch import auto_switch
    from src.core.provider_ledger import poller

    async def run() -> None:
        try:
            await auto_switch.after_pass(poller.snapshot(), app_state)
        except Exception as exc:  # noqa: BLE001
            logger.warning("pack_ledger_sync_switch_pass_failed", error=type(exc).__name__)

    task = asyncio.get_running_loop().create_task(run())
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)


def _peer(principal: Principal) -> str:
    if not principal.is_peer or principal.grant is None:
        raise HTTPException(403, {"code": "peer_token_required", "detail": "only a paired computer pushes ledger status"})
    return principal.grant.peer_install_id


async def _json(request: Request, model: Any) -> Any:
    try:
        return model.model_validate(await request.json())
    except (ValidationError, ValueError):
        raise HTTPException(422, {"code": "bad_ledger_body", "detail": "the ledger body is not valid"}) from None


@router.post("/ledger-status")
async def receive_ledger_status(request: Request, principal: Principal = Depends(_require_credentials),
                                _allowed: None = Depends(restrictions_mod.require_peer_allowed(
                                    restrictions_mod.ACTION_RECEIVE_CREDENTIALS))) -> JSONResponse:
    """Store the owner's latest status of one account and tell the ledger (and auto-switch) it moved."""
    sender = _peer(principal)
    body: LedgerStatusBody = await _json(request, LedgerStatusBody)
    consent = await asyncio.to_thread(config_state.default().relay_consent)
    if not consent_mod.accepts(consent, sender, body.account_key):
        raise HTTPException(403, {"code": "relay_not_accepted",
                                  "detail": "this computer's owner has not accepted that account from that computer"})
    await asyncio.to_thread(store.save_status, sender, body)
    _tell_ledger()
    _evaluate_switch(request.app.state)
    return JSONResponse({"ok": True}, headers=_NO_STORE)


def _relays_to(sender: str, account_key: str) -> bool:
    with closing(open_db()) as conn:
        return any(t.target_install_id == sender for t in targets.enabled_for(conn, account_key))


@router.post("/ledger-sessions")
async def receive_ledger_sessions(request: Request, principal: Principal = Depends(_require_machine)) -> JSONResponse:
    """Store which sessions a computer runs on its relayed copy of one of THIS computer's accounts."""
    sender = _peer(principal)
    body: LedgerSessionsBody = await _json(request, LedgerSessionsBody)
    if not await asyncio.to_thread(_relays_to, sender, body.account_key):
        raise HTTPException(403, {"code": "relay_not_enabled", "detail": "this computer does not relay that account to that computer"})
    await asyncio.to_thread(store.save_sessions, sender, body)
    _tell_ledger()
    return JSONResponse({"ok": True}, headers=_NO_STORE)
