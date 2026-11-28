from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime
from typing import Any, Awaitable, Callable, Literal, NoReturn, ParamSpec, TypeVar
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.routing import APIRoute
from starlette.responses import Response
from pydantic import ValidationError

from src.api.auth import require_auth
from src.core.session_change_notice import publish
from src.core.stats import catalog, config, live_view, pack_scope, queries, query_buckets
from src.core.stats.store import StatsStore
from src.models.stats import (
    AnnotationPatch, AnnotationWrite, BackfillRequest, ChartPatch, ChartWrite,
    Dimension, QueryBatchRequest, QueryRequest, SettingsPatch, StatsFilters,
)
from src.api.error_response import api_error

MAX_BODY_BYTES = 32 * 1024
logger = structlog.get_logger()

P = ParamSpec("P")
T = TypeVar("T")


def _wake_mesh_workspace() -> None:
    from src.core.pack.machines import capabilities

    if capabilities.mesh_on():
        from src.core.pack.meshdata import gossip

        gossip.wake()


async def _chart_changed(request: Request) -> None:
    revision = await asyncio.to_thread(_store(request).revision)
    publish(request.app.state, {"type": "stats.changed", "revision": revision, "source_health": "ok"})
    _wake_mesh_workspace()


class _BoundedBodyRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Awaitable[Response]]:
        handler = super().get_route_handler()

        async def bounded(request: Request) -> Response:
            if request.method in ("POST", "PATCH", "PUT"):
                length = request.headers.get("content-length")
                if length is not None:
                    try:
                        if int(length) > MAX_BODY_BYTES:
                            raise HTTPException(413, detail={"code": "stats_body_too_large"})
                    except ValueError as exc:
                        raise HTTPException(400, detail={"code": "invalid_content_length"}) from exc
                body = bytearray()
                async for chunk in request.stream():
                    body.extend(chunk)
                    if len(body) > MAX_BODY_BYTES:
                        raise HTTPException(413, detail={"code": "stats_body_too_large"})
                request._body = bytes(body)
            return await handler(request)

        return bounded


router = APIRouter(prefix="/stats", tags=["stats"], route_class=_BoundedBodyRoute,
                   dependencies=[Depends(require_auth)])


def _store(request: Request) -> StatsStore:
    store = getattr(request.app.state, "stats_store", None)
    if store is None:
        raise HTTPException(503, detail={"code": "stats_unavailable"})
    return store


def _error(exc: Exception) -> NoReturn:
    if isinstance(exc, config.NotFound):
        raise HTTPException(404, detail={"code": "not_found"}) from exc
    if isinstance(exc, config.StatsOff):
        raise HTTPException(409, detail={"code": "stats_off", "message": "stats off"}) from exc
    if isinstance(exc, config.RevisionConflict):
        raise HTTPException(409, detail={"code": "revision_conflict"}) from exc
    if isinstance(exc, (ValueError, query_buckets.QueryLimit)):
        raise api_error(422, "invalid_stats_request", exc) from exc
    raise exc


async def _on(request: Request) -> StatsStore:
    store = _store(request)
    await _run(config.require_enabled, store)
    return store


async def _run(fn: Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> T:
    try:
        return await asyncio.to_thread(fn, *args, **kwargs)
    except (ValueError, config.NotFound, config.RevisionConflict, config.StatsOff, query_buckets.QueryLimit) as exc:
        _error(exc)


@router.get("/catalog", response_model=None)
async def get_catalog() -> dict[str, Any]:
    """The metric catalog: every metric id with its unit and supported operations."""
    return catalog.catalog()


@router.get("/coverage", response_model=None)
async def get_coverage(request: Request) -> dict[str, Any]:
    """How much of the history the stats store covers, plus the collector's status and progress (1 threadpool hop, #3289)."""
    store = _store(request)
    scheduler = getattr(request.app.state, "stats_scheduler", None)
    status = None
    if scheduler is not None:
        status = scheduler.status()
        if asyncio.iscoroutine(status):
            status = await status

    def _read() -> dict[str, Any]:
        value = queries.coverage(store)
        if status is not None:
            from src.core.stats.plugin.progress import cached_progress
            value["collector"] = {**status, "collector": cached_progress(store.state_dir)}
        return value

    return await _run(_read)


@router.get("/live", response_model=None)
async def get_live(request: Request, scope: Literal["local", "pack"] = Query("pack")) -> dict[str, Any]:
    """The live snapshot: scheduler metrics, plus the cached v2 view (with Pack mesh telemetry when ``scope='pack'``) when stats are on."""
    scheduler = getattr(request.app.state, "stats_scheduler", None)
    if scheduler is None:
        value = {"available": False, "observed_at": None, "metrics": {}}
    else:
        value = scheduler.live_snapshot()
        if asyncio.iscoroutine(value):
            value = await value
    store = getattr(request.app.state, "stats_store", None)
    if store is not None:
        def _read_live() -> dict[str, Any]:
            if not config.get_settings(store)["enabled"]:
                return {}
            try:
                return live_view.live_v2_cached(store, scope=scope)
            except sqlite3.Error as exc:
                logger.warning("stats_live_v2_failed", error=type(exc).__name__)
                return {}

        extra = await _run(_read_live)
        if extra:
            value = {**value, **extra}
    return value


@router.get("/settings", response_model=None)
async def get_settings(request: Request) -> dict[str, Any]:
    """The stats settings (enabled flag and revision)."""
    return await _run(config.get_settings, _store(request))


@router.patch("/settings", response_model=None)
async def patch_settings(request: Request, value: SettingsPatch) -> dict[str, Any]:
    """Turn stats on or off (revision-checked) and tell the scheduler; returns the new settings."""
    result = await _run(config.update_settings, _store(request),
                        enabled=value.enabled, revision=value.revision)
    scheduler = getattr(request.app.state, "stats_scheduler", None)
    if scheduler is not None and hasattr(scheduler, "settings_changed"):
        changed = scheduler.settings_changed(result)
        if asyncio.iscoroutine(changed):
            await changed
    _wake_mesh_workspace()
    return result


@router.post("/query", response_model=None)
async def post_query(request: Request, value: QueryRequest) -> dict[str, Any]:
    """Run one stats query and return its answer."""
    return await _run(queries.execute, await _on(request), value)


@router.post("/query-batch", response_model=None)
async def post_query_batch(request: Request, value: QueryBatchRequest) -> dict[str, Any]:
    """Run several stats queries in one call (1 threadpool hop, #3289); each item answers on its own (all report `stats_off` while stats are off)."""
    store = _store(request)
    has_pack = any(item.get("scope") == "pack" for item in value.items)

    def _run_all() -> dict[str, Any]:
        if not config.get_settings(store)["enabled"]:
            off = {"ok": False, "error": {"code": "stats_off", "message": "stats off"}}
            return {"results": [off for _ in value.items], "revision": store.revision()}
        answer = queries.execute_batch(store, value.items)
        if has_pack:
            self_label, online = pack_scope.roster_view()
            answer = {**answer, "results": pack_scope.annotate(store, answer["results"], online, self_label)}
        return answer

    return await _run(_run_all)


@router.get("/contributions", response_model=None)
async def get_contributions(
    request: Request,
    metric: str,
    from_: datetime = Query(alias="from"),
    to: datetime = Query(),
    timezone_name: str = Query("UTC", alias="timezone"),
    resolution: str = Query("auto"),
    provider: str | None = None,
    host: str | None = None,
    project: str | None = None,
    model: str | None = None,
    agent_kind: str | None = None,
    conversation_id: str | None = None,
    scope: Literal["local", "pack"] = Query("pack"),
    limit: int = Query(50, ge=1, le=200),
    cursor: int = Query(0, ge=0, le=100000),
) -> dict[str, Any]:
    """What contributed to a metric over a range: the summary query's ranked contributors, paged by `limit` and `cursor`. 422 on a bad request."""
    try:
        value = QueryRequest.model_validate({
            "metric": metric, "from": from_, "to": to, "timezone": timezone_name,
            "resolution": resolution, "operation": "summary", "scope": scope,
            "filters": {key: val for key, val in {
                "provider": provider, "host": host, "project": project, "model": model,
                "agent_kind": agent_kind, "conversation_id": conversation_id,
            }.items() if val is not None},
        })
    except ValidationError as exc:
        raise api_error(422, "invalid_stats_request", exc) from exc
    return await _run(queries.contributions, await _on(request), value, limit=limit, cursor=cursor)


@router.get("/dimensions", response_model=None)
async def get_dimensions(
    request: Request, dimension: Dimension,
    from_: datetime | None = Query(None, alias="from"), to: datetime | None = None,
    provider: str | None = None, host: str | None = None,
    project: str | None = None, model: str | None = None,
    agent_kind: str | None = None, conversation_id: str | None = None,
    account_id: str | None = None, window: str | None = None,
    scope: Literal["local", "pack"] = Query("pack"),
    limit: int = Query(50, ge=1, le=200), cursor: int = Query(0, ge=0, le=100000),
) -> dict[str, Any]:
    """Distinct values of one dimension (or the Pack's computers for `host`) under optional filters and a range, paged. 422 on a bad range or filter."""
    if (from_ is None) != (to is None):
        raise HTTPException(422, detail={"code": "incomplete_range"})
    if from_ is not None and (from_.tzinfo is None or to.tzinfo is None or from_ >= to):
        raise HTTPException(422, detail={"code": "invalid_range"})
    try:
        filters = StatsFilters.model_validate({key: val for key, val in {
            "provider": provider, "host": host, "project": project, "model": model,
            "agent_kind": agent_kind, "conversation_id": conversation_id,
            "account_id": account_id, "window": window,
        }.items() if val is not None})
    except ValidationError as exc:
        raise HTTPException(422, detail={"code": "invalid_stats_filter"}) from exc
    if dimension == "host":
        self_label, online = await asyncio.to_thread(pack_scope.roster_view)
        return await _run(pack_scope.host_dimension, await _on(request), self_label, online)
    return await _run(queries.dimensions, await _on(request), dimension=dimension, filters=filters,
                      start=int(from_.timestamp()) if from_ else None,
                      end=int(to.timestamp()) if to else None, limit=limit, cursor=cursor, scope=scope)


@router.get("/events", response_model=None)
async def get_events(request: Request, from_: datetime = Query(alias="from"),
                     to: datetime = Query(), limit: int = Query(100, ge=1, le=200),
                     cursor: int = Query(0, ge=0, le=100000),
                     provider: str | None = None, host: str | None = None,
                     project: str | None = None, model: str | None = None,
                     agent_kind: str | None = None, conversation_id: str | None = None) -> dict[str, Any]:
    """Annotations (events) in a range under optional filters, paged. 422 on a bad range or filter."""
    if from_.tzinfo is None or to.tzinfo is None or from_ >= to:
        raise HTTPException(422, detail={"code": "invalid_range"})
    try:
        filters = StatsFilters.model_validate({key: val for key, val in {
            "provider": provider, "host": host, "project": project, "model": model,
            "agent_kind": agent_kind, "conversation_id": conversation_id,
        }.items() if val is not None})
    except ValidationError as exc:
        raise HTTPException(422, detail={"code": "invalid_stats_filter"}) from exc
    return await _run(config.list_annotations, await _on(request),
                      start=int(from_.timestamp()), end=int(to.timestamp()),
                      limit=limit, cursor=cursor, filters=filters)


@router.get("/charts", response_model=None)
async def get_charts(request: Request) -> list[dict[str, Any]]:
    """Every saved chart."""
    return await _run(config.list_charts, _store(request))


@router.post("/charts", response_model=None, status_code=201)
async def post_chart(request: Request, value: ChartWrite) -> dict[str, Any]:
    """Create a chart; 409 `chart_exists` when it already exists."""
    try:
        created = await _run(config.create_chart, _store(request), value)
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409, detail={"code": "chart_exists"}) from exc
    await _chart_changed(request)
    return created


@router.get("/charts/{chart_id}", response_model=None)
async def get_chart(request: Request, chart_id: UUID) -> dict[str, Any]:
    """One saved chart by id."""
    return await _run(config.get_chart, _store(request), str(chart_id))


@router.patch("/charts/{chart_id}", response_model=None)
async def patch_chart(request: Request, chart_id: UUID, value: ChartPatch) -> dict[str, Any]:
    """Update a chart (revision-checked); 422 when the body id differs from the path id."""
    if value.id and value.id != chart_id:
        raise HTTPException(422, detail={"code": "chart_id_mismatch"})
    saved = await _run(config.update_chart, _store(request), str(chart_id), value, value.revision)
    await _chart_changed(request)
    return saved


@router.delete("/charts/{chart_id}", response_model=None, status_code=204)
async def delete_chart(request: Request, chart_id: UUID, revision: int = Query(ge=1)) -> None:
    """Delete a chart (revision-checked); answers 204."""
    await _run(config.delete_chart, _store(request), str(chart_id), revision)
    await _chart_changed(request)


@router.post("/annotations", response_model=None, status_code=201)
async def post_annotation(request: Request, value: AnnotationWrite) -> dict[str, Any]:
    """Create an annotation."""
    created = await _run(config.create_annotation, _store(request), value)
    _wake_mesh_workspace()
    return created


@router.patch("/annotations/{annotation_id}", response_model=None)
async def patch_annotation(request: Request, annotation_id: UUID, value: AnnotationPatch) -> dict[str, Any]:
    """Update an annotation (revision-checked)."""
    updated = await _run(config.update_annotation, _store(request), str(annotation_id),
                         value, value.revision)
    _wake_mesh_workspace()
    return updated


@router.delete("/annotations/{annotation_id}", response_model=None, status_code=204)
async def delete_annotation(request: Request, annotation_id: UUID,
                            revision: int = Query(ge=1)) -> None:
    """Delete an annotation (revision-checked); answers 204."""
    await _run(config.delete_annotation, _store(request), str(annotation_id), revision)
    _wake_mesh_workspace()


@router.post("/backfill", response_model=None, status_code=202)
async def post_backfill(request: Request, value: BackfillRequest) -> dict[str, Any]:
    """Ask the scheduler to backfill history (idempotent by key). 409 while stats are off, 503 with no scheduler."""
    store = _store(request)
    settings = await _run(config.get_settings, store)
    if not settings["enabled"]:
        raise HTTPException(409, detail={"code": "stats_disabled"})
    scheduler = getattr(request.app.state, "stats_scheduler", None)
    if scheduler is None:
        raise HTTPException(503, detail={"code": "stats_unavailable"})
    record = await _run(config.request_backfill, store, value.idempotency_key)
    if record["state"] in ("requested", "running"):
        result = scheduler.request_backfill()
        if asyncio.iscoroutine(result):
            await result
    return record
