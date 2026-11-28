
from __future__ import annotations

import json
import re
import time
from collections import deque
from typing import Any, Callable, Deque, Dict, Tuple

import structlog
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from src.core.mcp import trusted_proxy
from src.plugins.host import identity, runtime, sidecar_routes
from src.plugins.host.secret_store import SecretStore
from src.plugins.host.sidecar_registry import SidecarDefinition
from src.plugins.runtime.webhooks import MAX_BODY_BYTES, InboundVerifier, WebhookRefused
from src.plugins.sdk.manifest import ID_PATTERN

logger = structlog.get_logger()

_HOOK_NAME = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")
_FAIL_LIMIT_PER_MINUTE = 20
_FAIL_WINDOW_SECONDS = 60.0

public_router = APIRouter(tags=["cplugs"])


class FailLimiter:

    def __init__(
        self,
        limit: int = _FAIL_LIMIT_PER_MINUTE,
        window_s: float = _FAIL_WINDOW_SECONDS,
        max_keys: int = 1024,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._clock = clock
        self._limit = limit
        self._window_s = window_s
        self._max_keys = max_keys
        self._hits: Dict[Tuple[str, str], Deque[float]] = {}

    def _prune(self, dq: Deque[float], now: float) -> None:
        while dq and now - dq[0] >= self._window_s:
            dq.popleft()

    def _prune_stale(self, now: float) -> None:
        stale = []
        for k, dq in self._hits.items():
            self._prune(dq, now)
            if not dq:
                stale.append(k)
        for k in stale:
            self._hits.pop(k, None)

    def is_blocked(self, install_key: str, client_ip: str) -> bool:
        key = (install_key, client_ip)
        dq = self._hits.get(key)
        if not dq:
            return False
        now = self._clock()
        self._prune(dq, now)
        if not dq:
            self._hits.pop(key, None)
            return False
        return len(dq) >= self._limit

    def record_failure(self, install_key: str, client_ip: str) -> None:
        now = self._clock()
        if len(self._hits) >= self._max_keys:
            self._prune_stale(now)
            hard_cap = self._max_keys * 4
            while len(self._hits) >= hard_cap:
                self._hits.pop(next(iter(self._hits)))
        key = (install_key, client_ip)
        dq = self._hits.setdefault(key, deque())
        self._prune(dq, now)
        dq.append(now)

    def clear_install(self, install_key: str) -> int:
        keys = [k for k in self._hits if k[0] == install_key]
        for k in keys:
            self._hits.pop(k, None)
        return len(keys)


_verifiers: Dict[str, InboundVerifier] = {}
_fail_limiter = FailLimiter()
_seq: Dict[str, int] = {}


def client_ip_for(request: Request) -> str:
    peer_raw = request.client.host if request.client else None
    peer_norm = trusted_proxy.normalize(peer_raw)
    if peer_raw and trusted_proxy.is_trusted(peer_raw):
        xff = request.headers.get("x-forwarded-for", "")
        if xff:
            parts = [p.strip() for p in xff.split(",") if p.strip()]
            for candidate in reversed(parts):
                norm = trusted_proxy.normalize(candidate)
                if norm is not None and not trusted_proxy.is_trusted(str(norm)):
                    return str(norm)
    return str(peer_norm) if peer_norm is not None else (peer_raw or "unknown")


def clear_install(install_key: str) -> int:
    had = 1 if _verifiers.pop(install_key, None) is not None else 0
    _fail_limiter.clear_install(install_key)
    _seq.pop(install_key, None)
    return had


def cancel_for_plugin(host: Any, plugin_id: str) -> int:
    try:
        key = host.install_key(plugin_id)
    except (KeyError, OSError, ValueError):
        key = plugin_id
    return clear_install(key)


def _error(status: int, code: str, detail: str, **headers: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "detail": detail}, headers=headers or None)


def _verifier_for(install_key: str) -> InboundVerifier:
    verifier = _verifiers.get(install_key)
    if verifier is None:
        verifier = InboundVerifier()
        _verifiers[install_key] = verifier
    return verifier


async def _read_raw_body(request: Request) -> bytes:
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        return b"x" * (MAX_BODY_BYTES + 1)
    buf = bytearray()
    async for chunk in request.stream():
        buf += chunk
        if len(buf) > MAX_BODY_BYTES:
            return bytes(buf[: MAX_BODY_BYTES + 1])
    return bytes(buf)


def _map_webhook_refusal(code: str) -> HTTPException:
    if code == "too_large":
        return _error(413, code, "webhook body too large")
    if code in ("rate_limited", "cache_full"):
        return _error(429, code, "webhook rate limit or nonce cache full", **{"Retry-After": "60"})
    return _error(401, code, "webhook verification failed")


@public_router.post("/cplugs/{cplug_id}/webhook/{hook_name}")
async def receive_webhook(cplug_id: str, hook_name: str, request: Request) -> JSONResponse:
    """Verify and deliver an inbound webhook to an enabled plugin."""
    host = runtime.host_for(request.app)
    d = runtime.find(cplug_id) if ID_PATTERN.match(cplug_id) and _HOOK_NAME.match(hook_name) else None
    if not isinstance(d, SidecarDefinition) or runtime.hidden(d):
        raise _error(404, "cplug_unknown", "no such plugin webhook")
    hooks = getattr(d.manifest, "webhooks", None) or {}
    hook_cfg = hooks.get(hook_name)
    if not isinstance(hook_cfg, dict):
        raise _error(404, "webhook_unknown", "no such plugin webhook")
    if not host.enabled(cplug_id):
        raise _error(409, "cplug_disabled", f"turn {cplug_id} on first")
    live = host.sidecar_runtime()
    if live is None:
        raise _error(503, "sidecar_runtime_unavailable", "the plugin runtime is not running")
    if getattr(d.manifest, "tier0", False):
        if sidecar_routes.tier0_held_down(host, d, live):
            raise sidecar_routes.held_off(host, d, live)
    elif sidecar_routes.held_down(live, cplug_id):
        raise sidecar_routes.held_off(host, d, live)
    try:
        key = host.install_key(cplug_id)
    except identity.LedgerUnreadable as exc:
        raise _error(503, "install_ledger_unreadable", "the install ledger could not be read") from exc
    if f"hooks.inbound:{hook_name}" not in host._live_grants(d.manifest):
        raise _error(403, "webhook_not_granted", f"hooks.inbound:{hook_name} is not granted")

    ip = client_ip_for(request)
    if _fail_limiter.is_blocked(key, ip):
        raise _error(429, "rate_limited", "too many failed webhook attempts", **{"Retry-After": "60"})

    raw_body = await _read_raw_body(request)
    headers = {k.lower(): v for k, v in request.headers.items()}
    custom_sig_hdr = hook_cfg.get("header")
    if custom_sig_hdr and "x-signature" not in headers and custom_sig_hdr.lower() in headers:
        headers["x-signature"] = headers[custom_sig_hdr.lower()]

    secret_name = hook_cfg.get("hmac_secret", "")
    secret_str = SecretStore(host.state_dir).webhook_secret(key, d.manifest, secret_name, hook_name)
    secret_bytes = secret_str.encode("utf-8") if secret_str else b""
    verifier = _verifier_for(key)
    try:
        verified = verifier.verify(hook_name, secret_bytes, headers, raw_body)
    except WebhookRefused as exc:
        _fail_limiter.record_failure(key, ip)
        logger.warning("cplug_webhook_refused", cplug=cplug_id, hook=hook_name, reason=exc.code)
        raise _map_webhook_refusal(exc.code) from exc

    payload_obj: Any
    try:
        payload_obj = json.loads(verified.decode("utf-8")) if verified else {}
    except (UnicodeDecodeError, ValueError):
        payload_obj = {"raw": verified.decode("utf-8", errors="replace")}

    seq = _seq.get(key, 0) + 1
    _seq[key] = seq
    delivered = await live.supervisor.deliver_event(
        cplug_id,
        f"webhook.{hook_name}",
        seq,
        {"hook": hook_name, "payload": payload_obj},
    )
    return JSONResponse(status_code=202, content={"ok": True, "delivered": bool(delivered)})
