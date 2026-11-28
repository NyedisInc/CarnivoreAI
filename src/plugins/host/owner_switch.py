
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, StrictBool

from src.api.auth import require_auth
from src.plugins.host.peer_refusal import refuse_peer_token_writes
from src.plugins.host import registry_store

logger = structlog.get_logger()


def read(state_dir: Path) -> bool:
    doc, status = registry_store.load_registry(state_dir)
    if status != registry_store.STATUS_OK or doc is None:
        return False
    switches = doc.get("switches")
    return isinstance(switches, dict) and switches.get("third_party") is True


def write(state_dir: Path, enabled: bool) -> bool:
    if registry_store.read_only_reason(state_dir) is not None:
        logger.warning("cplug_owner_switch_write_failed", reason="registry_read_only", detail=registry_store.read_only_reason(state_dir))
        return False
    try:
        with registry_store.exclusive(state_dir):
            doc = registry_store.read_for_mutation(state_dir, log_event="cplug_owner_switch_write_failed")
            doc.setdefault("switches", {})["third_party"] = bool(enabled)
            return registry_store.save_document(state_dir, doc, log_event="cplug_owner_switch_write_failed")
    except registry_store.RegistryBusy as exc:
        logger.warning("cplug_owner_switch_write_failed", reason="registry_lock", error=str(exc)[:200])
        return False
    except registry_store.RegistryUnreadable as exc:
        logger.error("cplug_owner_switch_write_failed", reason="registry_unreadable", error_type=type(exc).__name__)
        return False


class SwitchBody(BaseModel):
    """The switch the owner chose."""

    model_config = ConfigDict(extra="forbid")
    enabled: StrictBool


class SafeModeBody(BaseModel):
    """The runtime safe mode the owner chose."""

    model_config = ConfigDict(extra="forbid")
    on: StrictBool


owner_router = APIRouter(prefix="/cplug-owner", tags=["cplugs"], dependencies=[Depends(refuse_peer_token_writes), Depends(require_auth)])
safe_mode_router = APIRouter()


def _runtime(request: Request) -> Any:
    found = getattr(request.app.state, "sidecar_runtime", None)
    if found is None:
        raise HTTPException(status_code=503, detail={"code": "cplug_runtime_unavailable", "detail": "the plugin runtime is not running"})
    return found


@owner_router.get("/switch")
async def get_switch(request: Request) -> Dict[str, Any]:
    """The switch, safe mode and the last sandbox probe (none until the switch was turned on). Output: status."""
    return _runtime(request).status()


@owner_router.put("/switch")
async def put_switch(body: SwitchBody, request: Request) -> Dict[str, Any]:
    """Turn third-party plugins on or off. Output: status; turning on includes a fresh sandbox probe."""
    runtime = _runtime(request)
    if not await runtime.set_switch(body.enabled):
        raise HTTPException(status_code=500, detail={"code": "switch_not_saved", "detail": "the switch could not be written; it is unchanged"})
    return runtime.status()


@safe_mode_router.put("/safe-mode")
async def put_safe_mode(body: SafeModeBody, request: Request) -> Dict[str, Any]:
    """Turn the runtime safe mode on (stops every third-party plugin) or off. Output: status."""
    runtime = _runtime(request)
    if not await runtime.set_safe_mode(body.on):
        raise HTTPException(status_code=409, detail={"code": "safe_mode_forced", "detail": "safe mode is forced on by the environment"})
    return runtime.status()
