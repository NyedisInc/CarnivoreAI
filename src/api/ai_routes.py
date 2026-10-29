
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field

from src.api.ai_common import api_errors, connection_view, publish_changed
from src.api.auth import require_auth
from src.api.skill_card_art_backfill import queue_missing as queue_card_art
from src.config import settings
from src.config.byoai import TargetRef
from src.core.byoai import gateway as gateway_module
from src.core.byoai import registry
from src.core.byoai.presets import list_presets
from src.core.byoai.serialize import jsonable
from src.core.skill_manager import card_art, card_summary
from src.core.launch_profiles.store import LaunchProfileError, LaunchProfileStore
from src.core.launch_profiles.usage import profiles_using_connection

router = APIRouter(prefix="/ai", tags=["ai"], dependencies=[Depends(require_auth)])

MAX_CALLS = 500


class ConnectionCreate(BaseModel):
    """``POST /ai/connections``. ``key`` is write-only."""

    model_config = ConfigDict(extra="forbid")

    preset: str
    label: str = ""
    base_url: str = ""
    options: Dict[str, Any] = Field(default_factory=dict)
    key: Optional[str] = Field(default=None, repr=False)
    expected_revision: Optional[int] = None


class ConnectionUpdate(BaseModel):
    """``PATCH /ai/connections/{id}``: only the fields sent change."""

    model_config = ConfigDict(extra="forbid")

    label: Optional[str] = None
    base_url: Optional[str] = None
    options: Optional[Dict[str, Any]] = None
    enabled: Optional[bool] = None
    models: Optional[Dict[str, Dict[str, Any]]] = None
    key: Optional[str] = Field(default=None, repr=False)
    expected_revision: Optional[int] = None


class KeyBody(BaseModel):
    """``PUT /ai/connections/{id}/key``."""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(repr=False)
    expected_revision: Optional[int] = None


class TestBody(BaseModel):
    """``POST /ai/connections/{id}/test``."""

    __test__ = False

    model_config = ConfigDict(extra="forbid")

    capability: str
    model: Optional[str] = None


class RouteBody(BaseModel):
    """``PUT /ai/routing/...``: the target, or null to clear the route."""

    model_config = ConfigDict(extra="forbid")

    target: Optional[TargetRef] = None
    expected_revision: Optional[int] = None


def _profiles_using(connection_id: str) -> list:
    return profiles_using_connection(LaunchProfileStore(Path(settings.auth_config_file).expanduser()).list(), connection_id)


async def _write(gw: Any, fn: Any, *args: Any, **kwargs: Any) -> Any:
    with api_errors(gw):
        return await run_in_threadpool(fn, *args, **kwargs)


def _done(request: Request, item: Any = None) -> Dict[str, Any]:
    gw = gateway_module.get_gateway()
    revision = gw.store.read().revision
    publish_changed(request, revision)
    return {"revision": revision, **({"connection": connection_view(item)} if item is not None else {})}


@router.get("/presets")
async def list_ai_presets() -> Dict[str, Any]:
    """Every provider preset, as data (the settings picker)."""
    return {"presets": jsonable(list(list_presets()))}


@router.get("/connections")
async def list_connections() -> Dict[str, Any]:
    """The revision, every connection (no keys) and the routing tables."""
    block = gateway_module.get_gateway().store.read()
    return {"revision": block.revision, "connections": [connection_view(c) for c in block.connections],
            "defaults": block.model_dump(mode="json")["defaults"], "features": block.model_dump(mode="json")["features"]}


@router.post("/connections", status_code=201)
async def create_connection(body: ConnectionCreate, request: Request) -> Dict[str, Any]:
    """Add a connection (and its key). 409 on a stale revision."""
    gw = gateway_module.get_gateway()
    item = await _write(gw, gw.store.add_connection, preset=body.preset, label=body.label, base_url=body.base_url,
                        options=body.options, key=body.key, expected_revision=body.expected_revision)
    return _done(request, item)


@router.patch("/connections/{connection_id}")
async def update_connection(connection_id: str, body: ConnectionUpdate, request: Request) -> Dict[str, Any]:
    """Change a connection. A new base URL host without a new key clears the key (D3)."""
    gw = gateway_module.get_gateway()
    item = await _write(gw, gw.store.update_connection, connection_id, label=body.label, base_url=body.base_url,
                        options=body.options, enabled=body.enabled, models=body.models, key=body.key,
                        expected_revision=body.expected_revision)
    await run_in_threadpool(gw.calllog.clear_models, connection_id)
    return _done(request, item)


@router.delete("/connections/{connection_id}")
async def delete_connection(connection_id: str, request: Request,
                            expected_revision: Optional[int] = None) -> Dict[str, Any]:
    """Delete a connection, its key and every route pointing at it. 409 ``in_use`` while a launch profile's endpoint uses it (the profiles are named)."""
    gw = gateway_module.get_gateway()
    try:
        using = await run_in_threadpool(_profiles_using, connection_id)
    except (LaunchProfileError, ValueError) as exc:  # could not
        raise HTTPException(503, {"error": "usage_unknown", "detail": f"which launch profiles use this connection could not be read: {exc}"})
    if using:
        names = ", ".join(f"{p.label} ({p.id})" for p in using)
        raise HTTPException(409, {"error": "in_use", "profiles": [{"id": p.id, "label": p.label} for p in using],
                                  "detail": f"launch profiles use this connection: {names}; change their endpoint first"})
    await _write(gw, gw.store.delete_connection, connection_id, expected_revision=expected_revision)
    await run_in_threadpool(gw.calllog.clear_models, connection_id)
    return _done(request)


@router.put("/connections/{connection_id}/key")
async def set_key(connection_id: str, body: KeyBody, request: Request) -> Dict[str, Any]:
    """Store a key for the connection's CURRENT host. The answer says ``has_key`` and the last four characters."""
    gw = gateway_module.get_gateway()
    item = await _write(gw, gw.store.update_connection, connection_id, key=body.key,
                        expected_revision=body.expected_revision)
    return _done(request, item)


@router.delete("/connections/{connection_id}/key")
async def clear_key(connection_id: str, request: Request,
                    expected_revision: Optional[int] = None) -> Dict[str, Any]:
    """Remove the connection's key."""
    gw = gateway_module.get_gateway()
    item = await _write(gw, gw.store.clear_key, connection_id, expected_revision=expected_revision)
    return _done(request, item)


@router.post("/connections/{connection_id}/test")
async def test_connection(connection_id: str, body: TestBody) -> Dict[str, Any]:
    """A live try-it for one capability. Always 200: a failure is ``ok: false`` with the scrubbed reason."""
    gw = gateway_module.get_gateway()
    with api_errors(gw):
        gw.connection(connection_id)
    return jsonable(await gw.test(connection_id, body.capability, body.model))


@router.get("/connections/{connection_id}/models")
async def connection_models(connection_id: str, refresh: bool = False, cached_only: bool = False) -> Dict[str, Any]:
    gw = gateway_module.get_gateway()
    with api_errors(gw):
        fetched_at, models = await gw.list_models(connection_id, refresh=refresh, cached_only=cached_only)
    recent = await run_in_threadpool(gw.calllog.recent_models, connection_id)
    return {"fetched_at": fetched_at, "models": jsonable(models), "recent": recent}


@router.get("/features")
async def list_features() -> Dict[str, Any]:
    return await run_in_threadpool(_features_view)


def _features_view() -> Dict[str, Any]:
    block = gateway_module.get_gateway().store.read()
    routed = block.model_dump(mode="json")["features"]
    return {"revision": block.revision, "features": [
        {**registry.feature_view(f, block), "target": routed.get(f.id)} for f in registry.list_features()]}


@router.get("/routing")
async def get_routing() -> Dict[str, Any]:
    """The per-capability defaults and the per-feature targets."""
    block = gateway_module.get_gateway().store.read().model_dump(mode="json")
    return {"revision": block["revision"], "defaults": block["defaults"], "features": block["features"]}


@router.put("/routing/defaults/{capability}")
async def set_default(capability: str, body: RouteBody, request: Request) -> Dict[str, Any]:
    """Point a capability's default at a connection and model, or clear it (``target: null``)."""
    gw = gateway_module.get_gateway()
    await _write(gw, gw.store.set_default, capability, body.target, expected_revision=body.expected_revision)
    if capability == "chat" and body.target is not None:
        request.app.state.card_art_backfill = asyncio.create_task(queue_card_art(request.app))
    return _done(request)


@router.put("/routing/features/{feature_id}")
async def set_feature(feature_id: str, body: RouteBody, request: Request) -> Dict[str, Any]:
    """Point a registered feature at a connection and model, or clear it (``target: null``)."""
    gw = gateway_module.get_gateway()
    if registry.get_feature(feature_id) is None:
        raise HTTPException(404, {"error": "not_configured", "detail": f"no registered feature {feature_id}"})
    await _write(gw, gw.store.set_feature, feature_id, body.target, expected_revision=body.expected_revision)
    if feature_id in (card_art.FEATURE_ID, card_summary.FEATURE_ID) and body.target is not None:
        request.app.state.card_art_backfill = asyncio.create_task(queue_card_art(request.app))
    return _done(request)


@router.get("/calls")
async def recent_calls(limit: int = Query(50, ge=1, le=MAX_CALLS), before: Optional[int] = Query(None, ge=0),
                       after: Optional[int] = Query(None, ge=0), range: Optional[str] = Query(None, pattern="^(24h|7d|30d)$"),
                       feature: Optional[str] = None, connection: Optional[str] = None, model: Optional[str] = None,
                       result: Optional[str] = Query(None, pattern="^(ok|error)$")) -> Dict[str, Any]:
    """One page of calls, newest first: time, feature, connection, model, latency, tokens, cost, error. Never content.

    ``before`` / ``after`` are row-id cursors (the ``next`` / ``prev`` of the last answer); the filters compose.
    Answers ``calls``, ``total`` (rows matching), ``start`` (1-based position of the first row), ``next``, ``prev``.
    """
    log = gateway_module.get_gateway().calllog
    return await run_in_threadpool(lambda: log.page(
        limit=limit, before=before, after=after, range_name=range, feature=feature, connection_id=connection,
        model=model, ok=None if result is None else result == "ok"))


@router.get("/calls/summary")
async def calls_summary(range: str = Query("24h", pattern="^(24h|7d|30d)$")) -> Dict[str, Any]:
    """Totals, latency percentiles, spend by feature and model, and the filter options for one range."""
    return await run_in_threadpool(gateway_module.get_gateway().calllog.summary, range)
