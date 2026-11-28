
from __future__ import annotations

import asyncio
import json
import secrets
import time
from collections import deque
from typing import Any, Deque, Dict, Mapping, Optional, Tuple

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from src.api.auth import require_auth
from src.plugins.host import frame_serving, identity, risk, runtime
from src.plugins.host import state as owner_state
from src.plugins.host.peer_refusal import refuse_peer_token_writes
from src.plugins.host.sidecar_registry import SidecarDefinition
from src.plugins.runtime import frames, guards, sandbox
from src.plugins.runtime.process import REQUEST_TIMEOUT, TOOL_CALL_TIMEOUT, ProcessEnded
from src.plugins.runtime.supervisor import NEEDS_APPROVAL, TIER0_STATE
from src.plugins.sdk.manifest import ID_PATTERN

logger = structlog.get_logger()

METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")
MAX_REQUEST_BYTES = 64 * 1024
MAX_RESPONSE_BYTES = 256 * 1024
MAX_QUERY_CHARS = 2048
MAX_TAIL_CHARS = 512
RATE_LIMIT = 60
RATE_WINDOW = 60.0
_STATUSES = frozenset({200, 201, 202}) | (frozenset(range(400, 600)) - {401, 407})
_LIVE_STATES = frozenset({"running", "idle", "declarative", "backing_off", "unknown"})
_HEADERS = {"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"}

router = APIRouter(dependencies=[Depends(refuse_peer_token_writes), Depends(require_auth)], tags=["cplugs"])
_calls: Dict[str, Deque[float]] = {}


class ActBody(BaseModel):
    """The owner's click: which plugin route, and optionally the session the gesture named."""

    model_config = ConfigDict(extra="forbid")
    cplug_id: str = Field(min_length=1, max_length=64)
    route: str = Field(min_length=1, max_length=64)
    session_ref: Optional[str] = Field(default=None, max_length=200)
    body: Any = None


class ToolBody(BaseModel):
    """Browser ``tool.call`` payload: which plugin tool and JSON arguments."""

    model_config = ConfigDict(extra="forbid")
    cplug_id: str = Field(min_length=1, max_length=64)
    tool: str = Field(min_length=1, max_length=64)
    args: Any = None
    session_ref: Optional[str] = Field(default=None, max_length=200)


def _error(status: int, code: str, detail: str, **headers: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "detail": detail}, headers=headers or None)


def held_off(host: runtime.Host, d: SidecarDefinition, live: Any) -> HTTPException:
    if hasattr(live.supervisor, "is_paused") and live.supervisor.is_paused(d.id):
        return _error(409, "cplug_paused", f"{d.id} is paused; resume or restart it in plugins")
    if live.supervisor.state(d.id) == "paused":
        return _error(409, "cplug_paused", f"{d.id} is paused; resume or restart it in plugins")
    if not any(live.safe_mode().values()) and live.supervisor.state(d.id) in (NEEDS_APPROVAL, "disabled", "unknown", TIER0_STATE):
        st = owner_state.get(host.state_dir, d.manifest)
        if risk.consent_owed(d.manifest.tier, d.manifest.code_digest, st.digest):
            return _error(409, NEEDS_APPROVAL, f"{d.id} changed since it was approved; approve it in plugins")
    return _error(409, "cplug_disabled", f"{d.id} is held off (switch, safe mode, revoked or failed)")


def _admit(key: str, now: Optional[float] = None) -> bool:
    now = time.monotonic() if now is None else now
    hits = _calls.setdefault(key, deque())
    while hits and hits[0] <= now - RATE_WINDOW:
        hits.popleft()
    if len(hits) >= RATE_LIMIT:
        return False
    hits.append(now)
    return True


def held_down(live: Any, cplug_id: str) -> bool:
    return any(live.safe_mode().values()) or live.supervisor.state(cplug_id) not in _LIVE_STATES


def tier0_held_down(host: runtime.Host, d: SidecarDefinition, live: Any) -> bool:
    if any(live.safe_mode().values()):
        return True
    if live.supervisor.state(d.id) != TIER0_STATE:
        return True
    st = owner_state.get(host.state_dir, d.manifest)
    return risk.consent_owed(d.manifest.tier, d.manifest.code_digest, st.digest)


def _refused_to_http(exc: guards.Refused) -> HTTPException:
    code = exc.code
    if code in ("not_granted", "permission_denied", "integrity"):
        status = 403
    elif code in ("invalid_params", "not_found"):
        status = 400
    elif code in ("dialog_open", "disabled"):
        status = 409
    elif code == "too_large":
        status = 413
    elif code == "rate_limited":
        status = 429
    elif code == "timeout":
        status = 504
    elif code == "unavailable":
        status = 503
    else:
        status = 502
    return _error(status, code, str(exc))


def will_be_refused(request: Request, cplug_id: str) -> bool:
    host = runtime.host_for(request.app)
    live = host.sidecar_runtime()
    if not host.enabled(cplug_id) or live is None:
        return True
    d = runtime.find(cplug_id)
    if isinstance(d, SidecarDefinition) and getattr(d.manifest, "tier0", False):
        return tier0_held_down(host, d, live)
    return held_down(live, cplug_id)


async def _target(request: Request, cplug_id: str, route: Optional[str]) -> Tuple[runtime.Host, SidecarDefinition, Any, str]:
    host = runtime.host_for(request.app)
    d = runtime.find(cplug_id) if ID_PATTERN.match(cplug_id) else None
    if not isinstance(d, SidecarDefinition) or runtime.hidden(d) or (route is not None and route not in d.manifest.routes):
        raise _error(404, "cplug_unknown", "no such plugin route")
    from src.plugins.host import dev_routes  # noqa: PLC0415

    async with dev_routes.reload_lock(host.state_dir, cplug_id):
        d = runtime.find(cplug_id)
        if not isinstance(d, SidecarDefinition) or runtime.hidden(d) or (route is not None and route not in d.manifest.routes):
            raise _error(404, "cplug_unknown", "no such plugin route")
        if not host.enabled(cplug_id):
            raise _error(409, "cplug_disabled", f"turn {cplug_id} on first")
        live = host.sidecar_runtime()
        if live is None:
            raise _error(503, "sidecar_runtime_unavailable", "the plugin runtime is not running")
        if held_down(live, cplug_id):
            raise held_off(host, d, live)
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
            raise held_off(host, d, live)
        if proc is None or bool(getattr(proc, "ended", None)):
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
    _host, _d, proc, key = await _target(request, cplug_id, route)
    if len(tail) > MAX_TAIL_CHARS or len(request.url.query) > MAX_QUERY_CHARS:
        raise _error(414, "request_too_long", "the path or query is too long")
    body = await _read_body(request, request.method)
    params = {"route": route, "method": request.method, "path_params": {"rest": tail},
              "query": {k: request.query_params.getlist(k) for k in request.query_params}, "body": body, "actor": "owner"}
    with frame_serving.serving(key):
        return await _forward(proc, cplug_id, params)


@router.post("/cplug-owner/act")
async def owner_act(body: ActBody, request: Request) -> Response:
    """The owner's click: mint a token for exactly this install and session, hand it to the plugin's route or Tier 0 macro. Output: JSON.

    Fenced against API keys (``/api/v1/cplug-owner``). The token never leaves the host: it rides in the ``route.handle`` params.
    """
    if len(json.dumps(body.body, ensure_ascii=True, default=str).encode()) > MAX_REQUEST_BYTES:
        raise _error(413, "body_too_large", f"at most {MAX_REQUEST_BYTES} bytes")
    d0 = runtime.find(body.cplug_id) if ID_PATTERN.match(body.cplug_id) else None
    if isinstance(d0, SidecarDefinition) and not runtime.hidden(d0) and getattr(d0.manifest, "tier0", False):
        from src.plugins.host import tier0_channels  # noqa: PLC0415

        if tier0_channels.find_macro(d0.manifest, body.route) is not None:
            host = runtime.host_for(request.app)
            if not host.enabled(d0.id):
                raise _error(409, "cplug_disabled", f"turn {d0.id} on first")
            live = host.sidecar_runtime()
            if live is None:
                raise _error(503, "sidecar_runtime_unavailable", "the plugin runtime is not running")
            if tier0_held_down(host, d0, live):
                raise held_off(host, d0, live)
            try:
                key = host.install_key(d0.id)
            except identity.LedgerUnreadable as exc:
                raise _error(503, "install_ledger_unreadable", "the install ledger could not be read") from exc
            if not _admit(key):
                raise _error(429, "rate_limited", "too many calls to this plugin", **{"Retry-After": str(int(RATE_WINDOW))})
            token = live.tokens.mint(key, body.session_ref) if body.session_ref else None
            logger.info("cplug_owner_act_macro", cplug=d0.id, macro=body.route)
            try:
                results = await live.run_macro(d0.id, body.route, session_ref=body.session_ref or "", owner_token=token)
            except guards.Refused as exc:
                raise _refused_to_http(exc) from exc
            except KeyError as exc:
                raise _error(404, "cplug_unknown", "no such plugin macro") from exc
            return JSONResponse({"ok": True, "steps": results}, headers=_HEADERS)
    host, d, proc, key = await _target(request, body.cplug_id, body.route)
    live = host.sidecar_runtime()
    token = live.tokens.mint(key, body.session_ref) if (body.session_ref and live is not None) else None
    logger.info("cplug_owner_act", cplug=d.id, route=body.route)
    params = {"route": body.route, "method": "POST", "path_params": {"rest": ""}, "query": {}, "body": body.body, "actor": "owner",
              "owner_token": token, "session_ref": body.session_ref}
    return await _forward(proc, d.id, params)


@router.post("/cplug-owner/tool")
async def owner_tool(body: ToolBody, request: Request) -> JSONResponse:
    """Browser ``tool.call`` bridge endpoint: run a plugin's declared tool on the owner's behalf.

    ``read`` tools run immediately; ``inbox`` tools park in the owner approvals inbox.
    Fenced against API keys (``/api/v1/cplug-owner``).
    """
    if body.args is not None and not isinstance(body.args, dict):
        raise _error(422, "invalid_args", "args must be a JSON object")
    if len(json.dumps(body.args or {}, ensure_ascii=True, default=str).encode()) > MAX_REQUEST_BYTES:
        raise _error(413, "body_too_large", f"at most {MAX_REQUEST_BYTES} bytes")

    d_check = runtime.find(body.cplug_id) if ID_PATTERN.match(body.cplug_id) else None
    if not isinstance(d_check, SidecarDefinition) or runtime.hidden(d_check):
        raise _error(404, "cplug_unknown", "no such plugin")
    spec = next((t for t in d_check.manifest.tools if isinstance(t, Mapping) and t.get("name") == body.tool), None)
    if spec is None:
        raise _error(404, "tool_unknown", "no such plugin tool")

    host, d, proc, key = await _target(request, body.cplug_id, None)
    spec = next((t for t in d.manifest.tools if isinstance(t, Mapping) and t.get("name") == body.tool), None)
    if spec is None:
        raise _error(404, "tool_unknown", "no such plugin tool")
    if not _admit(key):
        raise _error(429, "rate_limited", "too many calls to this plugin", **{"Retry-After": str(int(RATE_WINDOW))})

    live = host.sidecar_runtime()
    who: Dict[str, Any] = {"kind": "owner", "session_ref": body.session_ref}
    if body.session_ref and live is not None:
        who["owner_token"] = live.tokens.mint(key, body.session_ref)

    async def invoke() -> Dict[str, Any]:
        from src.core.mcp.common import ToolError  # noqa: PLC0415
        from src.plugins.host import mcp as host_mcp  # noqa: PLC0415

        try:
            reply = await proc.request(
                "tools/call",
                {"name": body.tool, "arguments": dict(body.args or {}), "caller": who},
                timeout=TOOL_CALL_TIMEOUT,
            )
        except asyncio.TimeoutError as exc:
            raise _error(504, "cplug_timeout", f"{d.id} did not answer in {int(TOOL_CALL_TIMEOUT)} seconds") from exc
        except ProcessEnded as exc:
            if exc.reason == "plugin_error":
                raise _error(502, "plugin_error", f"{d.id} could not handle the call") from exc
            raise _error(409, "cplug_not_running", f"{d.id} stopped ({exc.reason})") from exc
        except frames.FrameViolation as exc:
            raise _error(502, "bad_plugin_response", f"{d.id} sent a frame the host refuses") from exc
        try:
            text = host_mcp._answer(d.id, reply)
        except ToolError as exc:
            raise _error(422, "tool_error", str(exc)) from exc
        return {"ok": True, "text": text, "result": reply}

    gate = spec.get("gate", "read")
    logger.info("cplug_owner_tool", cplug=d.id, tool=body.tool, gate=gate)
    if gate == "read":
        return JSONResponse(await invoke(), headers=_HEADERS)

    from src.core.mcp import pending  # noqa: PLC0415

    store = pending.get_store()
    result_box: Dict[str, Any] = {}
    error_box: Dict[str, HTTPException] = {}

    async def execute_approved() -> Dict[str, Any]:
        try:
            out = await invoke()
        except HTTPException as exc:
            error_box["http"] = exc
            raise pending.ActionRefused(str(exc.detail)) from exc
        result_box["value"] = out
        return out

    caller = f"cplug-owner:{d.id}"
    try:
        item = store.create(
            caller_session_id=caller,
            caller_tmux=caller,
            target_session_id="",
            target_tmux="",
            action=f"{d.id}__{body.tool}",
            args_summary=f"plugin {d.id} view tool {body.tool}",
            execute=execute_approved,
            args=dict(body.args or {}),
            dedupe_key=f"owner_tool:{key}:{body.tool}:{secrets.token_hex(4)}",
            beast_eligible=False,
        )
    except pending.PayloadTooLargeError as exc:
        raise _error(413, "body_too_large", str(exc)) from exc
    except pending.PendingLimitError as exc:
        raise _error(429, "rate_limited", str(exc)) from exc

    try:
        status = await pending.wait_for(item, TOOL_CALL_TIMEOUT)
        if status == pending.PENDING:
            if store.withdraw(item.id, "owner tool call timed out"):
                raise _error(408, "owner_timeout", "the owner did not approve in time")
            status = item.status
        if not pending.finished(item):
            status = await pending.wait_for(item, TOOL_CALL_TIMEOUT)
    finally:
        if item.status == pending.PENDING:
            store.withdraw(item.id, "owner tool call cancelled")

    if "http" in error_box:
        raise error_box["http"]
    if status == pending.APPROVED and "value" in result_box:
        return JSONResponse(result_box["value"], headers=_HEADERS)
    if status == pending.APPROVED and not pending.finished(item):
        raise _error(504, "owner_settle_timeout", "the approved tool call did not finish in time")
    if status == pending.APPROVED:
        raise _error(502, "plugin_error", f"{d.id} could not finish the approved tool call")
    if status == pending.REFUSED:
        raise _error(409, "refused_at_approve", "tool call refused at approval")
    raise _error(403, "owner_denied", "the owner denied this tool call")
