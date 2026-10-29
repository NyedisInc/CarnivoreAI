
from __future__ import annotations

import asyncio
import json
import time
from collections import deque
from typing import Any, Deque, Dict, Optional, Tuple

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from src.api.auth import require_auth
from src.cplugs.host import identity, runtime
from src.cplugs.host.sidecar_registry import SidecarDefinition
from src.cplugs.runtime import frames, sandbox
from src.cplugs.runtime.process import REQUEST_TIMEOUT, ProcessEnded
from src.cplugs.sdk.manifest import ID_PATTERN

logger = structlog.get_logger()

METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")
MAX_REQUEST_BYTES = 64 * 1024
MAX_RESPONSE_BYTES = 256 * 1024
MAX_QUERY_CHARS = 2048
MAX_TAIL_CHARS = 512
RATE_LIMIT = 60
RATE_WINDOW = 60.0
_STATUSES = frozenset({200, 201, 202}) | (frozenset(range(400, 600)) - {401, 407})
_LIVE_STATES = frozenset({"running", "idle", "backing_off", "unknown"})
_HEADERS = {"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"}

router = APIRouter(dependencies=[Depends(require_auth)], tags=["cplugs"])
_calls: Dict[str, Deque[float]] = {}


class ActBody(BaseModel):

    model_config = ConfigDict(extra="forbid")
    cplug_id: str = Field(min_length=1, max_length=64)
    route: str = Field(min_length=1, max_length=64)
    session_ref: str = Field(min_length=1, max_length=200)
    body: Any = None


def _error(status: int, code: str, detail: str, **headers: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "detail": detail}, headers=headers or None)


def _admit(key: str, now: Optional[float] = None) -> bool:
    now = time.monotonic() if now is None else now
    hits = _calls.setdefault(key, deque())
    while hits and hits[0] <= now - RATE_WINDOW:
        hits.popleft()
    if len(hits) >= RATE_LIMIT:
        return False
    hits.append(now)
    return True


async def _target(request: Request, cplug_id: str, route: Optional[str]) -> Tuple[runtime.Host, SidecarDefinition, Any, str]:
    host = runtime.host_for(request.app)
    d = runtime.find(cplug_id) if ID_PATTERN.match(cplug_id) else None
    if not isinstance(d, SidecarDefinition) or runtime.hidden(d) or (route is not None and route not in d.manifest.routes):
        raise _error(404, "cplug_unknown", "no such plugin route")
    if not host.enabled(cplug_id):
        raise _error(409, "cplug_disabled", f"turn {cplug_id} on first")
    live = host.sidecar_runtime()
    if live is None:
        raise _error(503, "sidecar_runtime_unavailable", "the plugin runtime is not running")
    held = _error(409, "cplug_disabled", f"{cplug_id} is held off (switch, safe mode, revoked or failed)")
    if any(live.safe_mode().values()) or live.supervisor.state(cplug_id) not in _LIVE_STATES:
        raise held
    try:
        key = host.install_key(cplug_id)
    except identity.LedgerUnreadable as exc:
        raise _error(503, "install_ledger_unreadable", "the install ledger could not be read") from exc
    if route is not None and not _admit(key):
        raise _error(429, "rate_limited", "too many calls to this plugin", **{"Retry-After": str(int(RATE_WINDOW))})
    try:
        proc = await live.supervisor.ensure(cplug_id)
    except sandbox.SandboxUnavailable as exc:
        raise _error(503, "sandbox_unavailable", "the plugin sandbox is not usable on this computer") from exc
    if live.supervisor.state(cplug_id) not in _LIVE_STATES:
        raise held
    if proc is None:
        raise _error(409, "cplug_not_running", f"{cplug_id} is on but its process is not running")
    return host, d, proc, key


async def _read_body(request: Request, method: str) -> Any:
    if method == "GET":
        return None
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_REQUEST_BYTES:
        raise _error(413, "body_too_large", f"at most {MAX_REQUEST_BYTES} bytes")
    raw = bytearray()
    async for chunk in request.stream():
        raw += chunk
        if len(raw) > MAX_REQUEST_BYTES:
            raise _error(413, "body_too_large", f"at most {MAX_REQUEST_BYTES} bytes")
    if not raw:
        return None
    if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
        raise _error(415, "json_only", "send application/json")
    try:
        return json.loads(bytes(raw))
    except (ValueError, RecursionError) as exc:
        raise _error(400, "invalid_json", "the body is not valid JSON") from exc


def _reply(result: Any) -> Response:
    if not isinstance(result, dict) or isinstance(result.get("status"), bool) or result.get("status") not in _STATUSES:
        raise _error(502, "bad_plugin_response", "the plugin answered with no usable status")
    try:
        payload = json.dumps(result.get("body"), allow_nan=False, ensure_ascii=True).encode("ascii")
    except (TypeError, ValueError, RecursionError) as exc:
        raise _error(502, "bad_plugin_response", "the plugin body is not JSON") from exc
    if len(payload) > MAX_RESPONSE_BYTES:
        raise _error(502, "response_too_large", f"the plugin answered more than {MAX_RESPONSE_BYTES} bytes")
    return Response(content=payload, status_code=result["status"], media_type="application/json", headers=_HEADERS)


async def _forward(proc: Any, cplug_id: str, params: Dict[str, Any]) -> Response:
    try:
        result = await proc.request("route.handle", params, timeout=REQUEST_TIMEOUT)
    except asyncio.TimeoutError as exc:
        raise _error(504, "cplug_timeout", f"{cplug_id} did not answer in {int(REQUEST_TIMEOUT)} seconds") from exc
    except ProcessEnded as exc:
        if exc.reason == "plugin_error":
            raise _error(502, "plugin_error", f"{cplug_id} could not handle the call") from exc
        raise _error(409, "cplug_not_running", f"{cplug_id} stopped ({exc.reason})") from exc
    except frames.FrameViolation as exc:
        raise _error(502, "bad_plugin_response", f"{cplug_id} sent a frame the host refuses") from exc
    return _reply(result)


@router.api_route("/cplugs/{cplug_id}/r/{rest:path}", methods=list(METHODS))
async def forward_route(cplug_id: str, rest: str, request: Request) -> Response:
    """Forward one call to the plugin's declared route and answer its JSON. Output: the plugin's status and re-serialized body."""
    route, _, tail = rest.partition("/")
    _host, _d, proc, _key = await _target(request, cplug_id, route)
    if len(tail) > MAX_TAIL_CHARS or len(request.url.query) > MAX_QUERY_CHARS:
        raise _error(414, "request_too_long", "the path or query is too long")
    body = await _read_body(request, request.method)
    params = {"route": route, "method": request.method, "path_params": {"rest": tail},
              "query": {k: request.query_params.getlist(k) for k in request.query_params}, "body": body, "actor": "owner"}
    return await _forward(proc, cplug_id, params)


@router.post("/cplug-owner/act")
async def owner_act(body: ActBody, request: Request) -> Response:
    """
    Fenced against API keys (``/api/v1/cplug-owner``). The token never leaves the host: it rides in the ``route.handle`` params.
    """
    if len(json.dumps(body.body, ensure_ascii=True, default=str).encode()) > MAX_REQUEST_BYTES:
        raise _error(413, "body_too_large", f"at most {MAX_REQUEST_BYTES} bytes")
    host, d, proc, key = await _target(request, body.cplug_id, body.route)
    live = host.sidecar_runtime()
    token = live.tokens.mint(key, body.session_ref)
    logger.info("cplug_owner_act", cplug=d.id, route=body.route)
    params = {"route": body.route, "method": "POST", "path_params": {"rest": ""}, "query": {}, "body": body.body, "actor": "owner",
              "owner_token": token, "session_ref": body.session_ref}
    return await _forward(proc, d.id, params)
