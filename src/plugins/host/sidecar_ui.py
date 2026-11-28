
from __future__ import annotations

import asyncio
import time
from collections import OrderedDict, deque
from typing import Any, Deque, Dict, Optional, Tuple

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from src.api.auth import require_auth
from src.plugins.host import absent_surfaces, identity, runtime, sidecar_routes, ui_doc
from src.plugins.host.sidecar_registry import SidecarDefinition
from src.plugins.runtime import frames
from src.plugins.runtime.process import REQUEST_TIMEOUT, ProcessEnded

logger = structlog.get_logger()

SURFACES = frozenset({"widget", "tab", "glance", "settings", "card_action", "status_source", "screen"})
UI_RATE_LIMIT = 240
UI_RATE_WINDOW = 60.0
MAX_PARAMS = 8
MAX_PARAM_CHARS = 200
CACHE_ENTRIES = 256
_HEADERS = {"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"}


class NoSuchSurface(RuntimeError):
    pass


router = APIRouter(dependencies=[Depends(require_auth)], tags=["cplugs"])
_calls: Dict[str, Deque[float]] = {}
_good: "OrderedDict[Tuple[str, str, Tuple[Tuple[str, str], ...]], Dict[str, Any]]" = OrderedDict()


def _admit(key: str) -> bool:
    now = time.monotonic()
    hits = _calls.setdefault(key, deque())
    while hits and hits[0] <= now - UI_RATE_WINDOW:
        hits.popleft()
    if len(hits) >= UI_RATE_LIMIT:
        return False
    hits.append(now)
    return True


def _remember(slot: Tuple[Any, ...], document: Dict[str, Any]) -> None:
    _good[slot] = document
    _good.move_to_end(slot)
    while len(_good) > CACHE_ENTRIES:
        _good.popitem(last=False)


def _params(request: Request) -> Dict[str, str]:
    out = {k: request.query_params[k] for k in request.query_params}
    if len(out) > MAX_PARAMS or any(len(k) > 40 or len(v) > MAX_PARAM_CHARS for k, v in out.items()):
        raise sidecar_routes._error(414, "request_too_long", "too many or too long parameters")
    return out


async def _render(proc: Any, surface: str, params: Dict[str, str]) -> Any:
    try:
        result = await proc.request("ui.render", {"surface": surface, "params": params}, timeout=REQUEST_TIMEOUT)
    except asyncio.TimeoutError as exc:
        raise RuntimeError("cplug_timeout") from exc
    except ProcessEnded as exc:
        if absent_surfaces.is_no_such_surface(exc):
            raise NoSuchSurface(surface) from exc
        raise RuntimeError("plugin_error" if exc.reason == "plugin_error" else "cplug_not_running") from exc
    except frames.FrameViolation as exc:
        raise RuntimeError("bad_plugin_response") from exc
    if not isinstance(result, dict) or "document" not in result:
        raise RuntimeError("bad_plugin_response")
    return result["document"]


def _answer(document: Dict[str, Any], surface: str, stale: Optional[str] = None) -> JSONResponse:
    body: Dict[str, Any] = {"surface": surface, "stale": stale is not None, "document": document}
    if stale is not None:
        body["reason"] = stale
    return JSONResponse(body, headers=_HEADERS)


def _read_decl_doc(d: SidecarDefinition, decl: Any) -> Optional[Any]:
    import json  # noqa: PLC0415

    if not isinstance(decl, dict):
        return None
    if "document" in decl:
        return decl["document"]
    if isinstance(decl.get("ui_file"), str):
        ui_path = d.code_root / decl["ui_file"]
        if ui_path.is_file() and not ui_path.is_symlink():
            return json.loads(ui_path.read_text(encoding="utf-8"))
    return None


def _tier0_static_document(d: SidecarDefinition, surface: str) -> Optional[Any]:
    ui_meta = getattr(d.manifest, "ui_meta", None)
    if not isinstance(ui_meta, dict) or surface not in ("widget", "tab", "screen"):
        return None
    if surface == "tab":
        return _read_decl_doc(d, ui_meta.get("sidebar_tab")) or _read_decl_doc(d, ui_meta.get("widget"))
    return _read_decl_doc(d, ui_meta.get("widget")) or (_read_decl_doc(d, ui_meta.get("sidebar_tab")) if surface == "screen" else None)


@router.get("/cplugs/{cplug_id}/ui/{surface}")
async def get_ui(cplug_id: str, surface: str, request: Request) -> JSONResponse:
    """Render one surface of an installed catalog cplug. Output: ``{surface, stale, document, reason?}``.

    Raises: 404 ``cplug_unknown`` / ``unknown_surface`` (also for a surface this plugin version already said it does not draw: answered
    before any process is started, #2969); 409 ``cplug_disabled``; 429 ``rate_limited``; 414; 502 ``invalid_ui_document``
    (the plugin's first document is refused; ``detail.rule`` and ``detail.path`` say which rule) or ``bad_plugin_response`` /
    ``cplug_timeout`` / ``cplug_not_running`` (no good document to fall back to yet).
    """
    if surface not in SURFACES:
        raise sidecar_routes._error(404, "unknown_surface", "no such surface")
    d0 = runtime.find(cplug_id)
    if (isinstance(d0, SidecarDefinition) and absent_surfaces.is_absent(d0.id, d0.manifest.version, surface)
            and not sidecar_routes.will_be_refused(request, cplug_id)):
        raise sidecar_routes._error(404, "unknown_surface", "no such surface")
    params = _params(request)
    if isinstance(d0, SidecarDefinition) and not runtime.hidden(d0) and getattr(d0.manifest, "tier0", False):
        host = runtime.host_for(request.app)
        if not host.enabled(cplug_id):
            raise sidecar_routes._error(409, "cplug_disabled", f"turn {cplug_id} on first")
        live = host.sidecar_runtime()
        if live is None:
            raise sidecar_routes._error(503, "sidecar_runtime_unavailable", "the plugin runtime is not running")
        if sidecar_routes.tier0_held_down(host, d0, live):
            raise sidecar_routes.held_off(host, d0, live)
        try:
            key = host.install_key(cplug_id)
        except identity.LedgerUnreadable as exc:
            raise sidecar_routes._error(503, "install_ledger_unreadable", "the install ledger could not be read") from exc
        if not _admit(key):
            raise sidecar_routes._error(429, "rate_limited", "too many reads of this plugin's UI", **{"Retry-After": "5"})
        raw_doc = _tier0_static_document(d0, surface)
        if raw_doc is None:
            raise sidecar_routes._error(404, "unknown_surface", "no such surface")
        try:
            fresh = ui_doc.validate(raw_doc, routes=d0.manifest.routes,
                                    tools=[t.get("name") for t in d0.manifest.tools if isinstance(t, dict)])
        except ui_doc.UiDocError as exc:
            raise HTTPException(status_code=502, detail={"code": "invalid_ui_document", "detail": f"{d0.id} gave no usable {surface} document", "rule": exc.code, "path": exc.path}) from exc
        return _answer(fresh, surface)
    try:
        _host, d, proc, key = await sidecar_routes._target(request, cplug_id, None)
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        slot = _stale_slot(request, cplug_id, surface, params) if detail.get("code") == "cplug_not_running" else None
        if slot is None or slot not in _good:
            raise
        return _answer(_good[slot], surface, "cplug_not_running")
    if not _admit(key):
        raise sidecar_routes._error(429, "rate_limited", "too many reads of this plugin's UI", **{"Retry-After": "5"})
    slot = (key, surface, tuple(sorted(params.items())))
    try:
        rendered = await _render(proc, surface, params)
        absent_surfaces.note_rendered(d.id, d.manifest.version, surface)
        fresh = ui_doc.validate(rendered, routes=d.manifest.routes,
                                tools=[t.get("name") for t in d.manifest.tools if isinstance(t, dict)])
    except NoSuchSurface as exc:
        absent_surfaces.remember(d.id, d.manifest.version, surface)
        raise sidecar_routes._error(404, "unknown_surface", "no such surface") from exc
    except RuntimeError as exc:
        reason, rule = str(exc), None
    except ui_doc.UiDocError as exc:
        reason, rule = "invalid_ui_document", exc
        logger.warning("cplug_ui_refused", cplug=d.id, surface=surface, rule=exc.code, path=exc.path)
    else:
        _remember(slot, fresh)
        return _answer(fresh, surface)
    if slot in _good:
        return _answer(_good[slot], surface, reason)
    detail = {"code": reason, "detail": f"{d.id} gave no usable {surface} document"}
    if rule is not None:
        detail["rule"], detail["path"] = rule.code, rule.path
    raise HTTPException(status_code=502, detail=detail)


def _stale_slot(request: Request, cplug_id: str, surface: str, params: Dict[str, str]) -> Optional[Tuple[Any, ...]]:
    try:
        return (runtime.host_for(request.app).install_key(cplug_id), surface, tuple(sorted(params.items())))
    except identity.LedgerUnreadable:
        return None
