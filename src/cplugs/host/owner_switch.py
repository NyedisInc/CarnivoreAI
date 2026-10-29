
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, StrictBool

from src.api.auth import require_auth
from src.core.json_artifact import atomic_write_json

logger = structlog.get_logger()

FILE_NAME = "third-party.json"


def switch_path(state_dir: Path) -> Path:
    return Path(state_dir) / "cplugs" / FILE_NAME


def read(state_dir: Path) -> bool:
    try:
        data = json.loads(switch_path(state_dir).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return False
    except (OSError, ValueError) as exc:
        logger.warning("cplug_owner_switch_unreadable", error_type=type(exc).__name__)
        return False
    return isinstance(data, dict) and data.get("enabled") is True


def write(state_dir: Path, enabled: bool) -> bool:
    return atomic_write_json(switch_path(state_dir), {"enabled": bool(enabled)}, log_event="cplug_owner_switch_write_failed")


class SwitchBody(BaseModel):
    """The switch the owner chose."""

    model_config = ConfigDict(extra="forbid")
    enabled: StrictBool


class SafeModeBody(BaseModel):
    """The runtime safe mode the owner chose."""

    model_config = ConfigDict(extra="forbid")
    on: StrictBool


owner_router = APIRouter(prefix="/cplug-owner", tags=["cplugs"], dependencies=[Depends(require_auth)])
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
