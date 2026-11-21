
from __future__ import annotations

import time
from typing import Any, Dict, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from starlette.concurrency import run_in_threadpool

from src.api.auth import require_auth
from src.core.argent import health, refresh, settings as settings_module
from src.core.argent import store as store_module
from src.core.argent.device_login import PENDING, LoginRefused
from src.core.argent.lifecycle import PORT_NAME
from src.core.argent.delegate import Delegates
from src.core.argent.runtime import get_runtime
from src.core.argent.settings import ArgentSettings, SettingsRefused
from src.plugins.sdk import ports

logger = structlog.get_logger()
router = APIRouter(prefix="", tags=["argent"], dependencies=[Depends(require_auth)])

LOGIN_SOON_SECONDS = store_module.LOGIN_SOON_SECONDS


class ArgentSettingsPatch(BaseModel):
    """A settings change; every field optional, only the ones sent change. Example: {"enabled": false}"""

    model_config = ConfigDict(extra="forbid")

    server_url: Optional[str] = None
    gateway_url: Optional[str] = None
    ca_path: Optional[str] = None
    enabled: Optional[bool] = None
    refuse_direct_launch: Optional[bool] = None


def feature_on() -> bool:
    return ports.get(PORT_NAME) is not None


def _login_view() -> Dict[str, Any]:
    runtime = get_runtime()
    flow = runtime.login.public()
    row = runtime.store.get_login()
    now = time.time()
    if flow["state"] == PENDING:
        state = "pending"
    elif row is None:
        state = "logged_out"
    elif runtime.store.login_expired() or float(row["expires_at"]) <= now:
        state = "login_expired"
    elif float(row["expires_at"]) - now <= LOGIN_SOON_SECONDS:
        state = "login_soon"
    else:
        state = "logged_in"
    return {"state": state, "display_name": row["display_name"] if row else "", "tenant_id": row["tenant_id"] if row else "",
            "expires_at": row["expires_at"] if row else None, "flow": flow}


def _status_sync() -> Dict[str, Any]:
    cfg = settings_module.read()
    login = _login_view()
    report = health.latest()
    state = health.LOGIN_EXPIRED if login["state"] == "login_expired" and report.state == health.UP else report.state
    refusal = health.switch_on_refusal(report, server_url=cfg.server_url, gateway_url=cfg.gateway_url,
                                       logged_in=login["state"] in ("logged_in", "login_soon"), login_expired=login["state"] == "login_expired")
    return {"feature_on": feature_on(), "settings": cfg.as_public(), "state": state,
            "refusal": {"code": refusal, "message": health.REFUSALS[refusal]} if refusal else None,
            "health": report.as_public(), "login": login}


@router.get("/status")
async def get_status() -> Dict[str, Any]:
    """The argent feature's status. Example: GET /api/v1/argent/status -> {"feature_on": true, "state": "up", ...}"""
    return await run_in_threadpool(_status_sync)


@router.get("/settings")
async def get_settings() -> Dict[str, Any]:
    """The stored settings. Example: GET /api/v1/argent/settings -> {"server_url": "", "enabled": false, ...}"""
    return (await run_in_threadpool(settings_module.read)).as_public()


def _refuse(code: str, message: str, status: int = 422) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


@router.put("/settings")
async def put_settings(body: ArgentSettingsPatch) -> Dict[str, Any]:
    """Change settings. Switching ON needs the feature on, a login and a fresh probe that says ready (409 ``switch_refused`` names why).

    Inputs: body. Output: the status after the write. Raises: HTTPException 422 (bad address or path), 409 (``feature_off``,
      ``switch_refused``), 500 (config.json could not be written).
    Example: PUT /api/v1/argent/settings {"server_url": "https://argent.example"}
    """
    current = await run_in_threadpool(settings_module.read)
    try:
        server = settings_module.clean_url(body.server_url, "server_url") if body.server_url is not None else current.server_url
        gateway = settings_module.clean_url(body.gateway_url, "gateway_url") if body.gateway_url is not None else current.gateway_url
        ca_path = settings_module.clean_ca_path(body.ca_path) if body.ca_path is not None else current.ca_path
    except SettingsRefused as exc:
        raise _refuse(exc.code, str(exc)) from exc
    enabled = current.enabled if body.enabled is None else body.enabled
    candidate = ArgentSettings(server_url=server, gateway_url=gateway, ca_path=ca_path)
    if current.enabled and enabled:
        if not server or not gateway:
            raise _refuse("address_required", "turn the switch off before you clear an address", 409)
        if (server, gateway, ca_path) != (current.server_url, current.gateway_url, current.ca_path):
            await _check_switch_on(candidate)
    if not server:
        enabled = False
    if body.enabled is True and not current.enabled:
        await _check_switch_on(candidate)

    def mutate(block: Dict[str, Any]) -> None:
        block.update(serverUrl=server, gatewayUrl=gateway, caPath=ca_path, enabled=enabled)
        if body.refuse_direct_launch is not None:
            block["refuseDirectLaunch"] = body.refuse_direct_launch

    try:
        await run_in_threadpool(settings_module.update, mutate)
    except (OSError, ValueError) as exc:
        logger.error("argent_settings_unwritable", error_type=type(exc).__name__)
        raise HTTPException(status_code=500, detail="config.json could not be updated") from exc
    health.poke()
    return await get_status()


async def _check_switch_on(candidate: ArgentSettings) -> None:
    if not feature_on():
        raise _refuse("feature_off", "turn the argent feature on first", 409)
    login = await run_in_threadpool(_login_view)
    expired = login["state"] == "login_expired"
    report = await health.probe(candidate.gateway_url, candidate.server_url, ca_path=candidate.ca_path, login_expired=expired)
    health.remember(report)
    reason = health.switch_on_refusal(report, server_url=candidate.server_url, gateway_url=candidate.gateway_url,
                                      logged_in=login["state"] in ("logged_in", "login_soon"), login_expired=expired)
    if reason:
        logger.info("argent_switch_on_refused", code=reason)
        raise _refuse("switch_refused", health.REFUSALS[reason], 409)


@router.post("/login/start")
async def login_start() -> Dict[str, Any]:
    """Begin a device login. Output: the flow (pending, user_code, verification_uri, expires_at). Raises: 409 ``feature_off``; 422 with the reason."""
    if not feature_on():
        raise _refuse("feature_off", "turn the argent feature on first", 409)
    cfg = await run_in_threadpool(settings_module.read)
    try:
        return await get_runtime().login.start(cfg.server_url)
    except LoginRefused as exc:
        raise _refuse(exc.code, str(exc)) from exc


@router.get("/login")
async def get_login() -> Dict[str, Any]:
    """The login state and flow (resync). Example: GET /api/v1/argent/login -> {"state": "logged_out", "flow": {"state": "idle"}}"""
    return await run_in_threadpool(_login_view)


@router.delete("/login")
async def delete_login() -> Dict[str, Any]:
    """Cancel a pending login, or log out: the token leaves the Keychain, the login is forgotten and the switch turns off. Output: the status."""
    runtime = get_runtime()
    await runtime.login.cancel()
    cfg = await run_in_threadpool(settings_module.read)
    account = (cfg.token_pointer or {}).get("account", "")
    refresh.forget_unsaved()
    await Delegates(runtime.store, runtime.tokens).revoke_all()
    if account:
        await run_in_threadpool(runtime.tokens.delete, account)
    await run_in_threadpool(runtime.store.clear_login)

    def mutate(block: Dict[str, Any]) -> None:
        block.pop("tokenPointer", None)
        block["enabled"] = False

    await run_in_threadpool(settings_module.update, mutate)
    health.poke()
    return await get_status()
