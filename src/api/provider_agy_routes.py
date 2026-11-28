
from __future__ import annotations

import asyncio

import structlog
from fastapi import APIRouter, Depends, HTTPException

from src.api.auth import require_auth
from src.api.provider_ledger_routes import _config_path, _unreadable
from src.config import settings
from src.core.account_switch import agy_rotate
from src.core.agy import accounts as agy_accounts
from src.core.provider_ledger import poller

logger = structlog.get_logger()

router = APIRouter(tags=["provider-ledger"])

_CAPTURE_SENTENCES = {
    "no_identity": "no signed in email is known yet: start agy, sign in, let it draw its status line once, then capture",
    "no_live_login": "agy holds no login on this computer: sign in inside agy, then capture",
}


@router.post("/provider-ledger/agy/capture", dependencies=[Depends(require_auth)])
async def capture_agy_login() -> dict:
    """Capture the login agy holds right now as an antigravity account.

    Description: the account is named from the email in the newest agy status line state and gets its own id
      (``agy-<email slug>``); capturing the same login again refreshes that account's copy. The pointer moves to it.
    Output: ``{"account_id", "name", "created"}``.
    Raises: HTTPException(409) ``agy_no_identity`` (no agy has drawn its status line yet, so no email is known) or
      ``agy_no_live_login`` (agy holds no login) or ``agy_write_failed`` (the keychain refused); HTTPException(500) config.json unreadable.
    Example: POST /api/v1/provider-ledger/agy/capture -> {"account_id": "agy-alice-example-com", "name": "alice@example.com", "created": true}
    """
    try:
        account, created = await asyncio.to_thread(agy_rotate.capture_account, _config_path())
    except agy_rotate.CaptureError as exc:
        raise HTTPException(status_code=409, detail={"code": "agy_" + exc.code, "detail": _CAPTURE_SENTENCES[exc.code]}) from exc
    except agy_accounts.AgyAccountError as exc:
        raise HTTPException(status_code=409, detail={"code": "agy_" + exc.code, "detail": "the login could not be copied"}) from exc
    except (FileNotFoundError, ValueError) as exc:
        raise _unreadable(exc) from exc
    settings._auth_config_cache = None
    from src.api import session_account_listing

    session_account_listing.reset()
    poller.poll_soon(account.id)
    logger.info("agy_login_captured", account_id=account.id, created=created)
    return {"account_id": account.id, "name": account.name, "created": created}
