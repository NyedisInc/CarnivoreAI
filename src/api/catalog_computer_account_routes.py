
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from src.api.auth import require_auth
from src.api.error_response import api_error
from src.api.catalog_hosted_routes import _catalog, _state_dir
from src.api.catalog_signin_finish import key_provider_for
from src.api.catalog_rating_routes import _unauthorized
from src.core.catalog import catalog_auth, client_sessions as cs, hosted_api
from src.core.catalog.token_store import MODE_BOUND, MODE_OWN, open_token_store

router = APIRouter(tags=["catalog"])


class SignOutAllRequest(BaseModel):
    """``confirm`` must be true: the owner saw that every device, this one included, loses its sign in."""

    confirm: bool = False


class UseAccountRequest(BaseModel):
    """``switch`` is the handle a 409 ``computer_signed_in_as`` carried."""

    switch: str


def _device_level(request: Request) -> cs.ClientRef:
    ref = cs.client_ref(request)
    if ref.via_link or (ref.key or "").startswith(cs.APIKEY_PREFIX):
        raise HTTPException(403, detail={"code": "device_level", "detail": "do this on the computer itself"})
    return ref


@router.get("/catalog/computer-account/status", dependencies=[Depends(require_auth)])
async def computer_account_status(request: Request) -> Dict[str, Any]:
    """The computer's account and how many clients ride on it; never a token. Also the login a refused sign in waits to switch to."""
    ref = _device_level(request)
    views = await cs.session_views(_state_dir(request), _catalog(request).api_base_url(), ref)
    with open_token_store(_state_dir(request)) as store:
        entries = store.clients_all()
    return {
        "computer": views["computer"],
        "clients": {"bound": sum(e.mode == MODE_BOUND for e in entries), "own": sum(e.mode == MODE_OWN for e in entries)},
        "pending_switch": cs.switches.waiting_for(ref.key),
    }


@router.post("/catalog/computer-account/use", dependencies=[Depends(require_auth)])
async def computer_account_use(request: Request, body: UseAccountRequest) -> Dict[str, Any]:
    """Switch the computer to the account a refused sign in carried: the old device session is signed out on hosted, every
    client's link is cleared and the relay claims the device for the new account. A custom domain's configuration stays."""
    ref = _device_level(request)
    try:
        session = await cs.use_account(
            _state_dir(request), _catalog(request).api_base_url(), ref, body.switch, key_provider_for(request)
        )
    except LookupError:
        raise HTTPException(400, detail={"code": "unknown_switch", "detail": "that switch is gone; sign in again"}) from None
    return {"signed_in": True, "login": session.login, "provider": session.provider}


@router.post("/catalog/auth/signout-all", dependencies=[Depends(require_auth)])
async def catalog_auth_signout_all(request: Request, body: SignOutAllRequest) -> Dict[str, Any]:
    """Sign every client out of the carnivore account, everywhere (hosted ``revoke-all`` with ``include_self``, the
    computer's own device session kept on its keep list when it has one). Needs ``confirm: true``, also over the phone link."""
    if not body.confirm:
        raise HTTPException(403, detail={"code": "confirm_required",
                                         "detail": "confirm that every device, this one included, will be signed out"})
    ref = cs.client_ref(request)
    try:
        return await cs.sign_out_all(_state_dir(request), _catalog(request).api_base_url(), ref)
    except catalog_auth.UnknownClient:
        raise HTTPException(409, detail={
            "code": "refresh_and_retry", "detail": "refresh your session and try again"}) from None
    except catalog_auth.SignedOut:
        raise _unauthorized() from None
    except catalog_auth.RotationFailed as exc:
        raise api_error(exc.status, "catalog_refused", exc) from None
    except hosted_api.HostedUnavailable as exc:
        raise api_error(502, exc.code, exc) from None
