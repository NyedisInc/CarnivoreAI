
from __future__ import annotations

import hashlib
import json
from typing import Any, Callable, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlsplit

import structlog

from src.core.notifications.contracts import DeliveryResult, FailureClass, NotifyEvent
from src.core.notifications import http
from src.core.notifications.http import GuardBlocked, GuardLocalPolicy, GuardNetworkError, GuardResponse, GuardTimeout, HostPolicy, guarded_request
from src.core.notifications.kind_specs import KindSpec

log = structlog.get_logger(__name__)

RETRY_AFTER_CAP = 20.0

Override = Callable[[int, bytes], Optional[FailureClass]]


def policy_for(kind: KindSpec, config: Mapping[str, Any], url: str) -> HostPolicy:
    rules = kind.hosts
    origin = http.origin_of(url)

    def on(name: str) -> bool:
        return bool(kind.allow_private and config.get(name) is True)

    def approved(name: str) -> bool:
        return on(name) and origin is not None and config.get(f"{name}_origin") == origin

    private = approved("allow_private")
    plain = private and approved("allow_plain_http")
    return HostPolicy(
        exact=tuple(rules.exact_hosts), suffixes=tuple(rules.suffixes), pattern=rules.regex,
        any_host=rules.any_host, allow_private=private, allow_plain_http=plain, switchable=kind.allow_private,
        origin_changed=(on("allow_private") and not private) or (on("allow_plain_http") and not approved("allow_plain_http")),
    )


def path_allowed(kind: KindSpec, url: str) -> bool:
    prefix = kind.hosts.path_prefix
    return prefix is None or urlsplit(url).path.startswith(prefix)


def delivery_id(event: NotifyEvent, dest_id: str) -> str:
    if event.instance_key:
        instance = event.instance_key
    elif event.toast_id:
        instance = f"toast:{event.toast_id}:{event.toast_version}"
    else:
        instance = f"{event.type_id}:{event.session_id or event.session_ref}:{event.ts!r}"
    return hashlib.sha256(f"{dest_id}\x00{instance}".encode("utf-8")).hexdigest()[:32]


def dest_id_of(config: Mapping[str, Any]) -> str:
    value = config.get("dest_id")
    return value if isinstance(value, str) and value else "unknown"


def _retry_after(headers: Mapping[str, str], body: bytes) -> Optional[float]:
    raw: Any = headers.get("retry-after")
    if raw is None and body:
        try:
            doc = json.loads(body)
        except ValueError:
            doc = None
        if isinstance(doc, dict):
            raw = doc.get("retry_after")
            if raw is None and isinstance(doc.get("parameters"), dict):
                raw = doc["parameters"].get("retry_after")
    try:
        seconds = float(raw)
    except (TypeError, ValueError):
        return None
    return min(max(seconds, 0.0), RETRY_AFTER_CAP)


def classify(resp: GuardResponse, override: Optional[Override] = None) -> DeliveryResult:
    status = resp.status
    if 200 <= status < 300:
        return DeliveryResult(ok=True, status_code=status)
    failure = override(status, resp.body) if override else None
    if failure is None:
        if status == 429:
            failure = FailureClass.RATE_LIMITED
        elif status >= 500:
            failure = FailureClass.SERVER
        elif status in (401, 403):
            failure = FailureClass.AUTH
        elif status in (404, 410):
            failure = FailureClass.GONE
        else:
            failure = FailureClass.INVALID
    retry = _retry_after(resp.headers, resp.body) if failure is FailureClass.RATE_LIMITED else None
    return DeliveryResult(ok=False, failure=failure, status_code=status, retry_after=retry, detail=f"http {status}")


def classify_error(exc: Exception) -> DeliveryResult:
    if isinstance(exc, GuardLocalPolicy):
        failure = {"origin": FailureClass.ORIGIN_CHANGED, "plain_http": FailureClass.PLAIN_HTTP_OFF}.get(
            exc.switch, FailureClass.PRIVATE_OFF)
    elif isinstance(exc, GuardBlocked):
        failure = FailureClass.BLOCKED
    elif isinstance(exc, GuardTimeout):
        failure = FailureClass.TIMEOUT
    else:
        failure = FailureClass.NETWORK
    return DeliveryResult(ok=False, failure=failure, detail=getattr(exc, "reason", "") or "error")


def invalid(detail: str) -> DeliveryResult:
    return DeliveryResult(ok=False, failure=FailureClass.INVALID, detail=detail)


async def post(
    kind: KindSpec, config: Mapping[str, Any], url: str, *, json_body: Any = None,
    content: Optional[bytes] = None, headers: Optional[Mapping[str, str]] = None,
    override: Optional[Override] = None, timeout: float = 10.0,
    data: Optional[Mapping[str, Any]] = None, auth: Optional[Tuple[str, str]] = None,
) -> DeliveryResult:
    dest = dest_id_of(config)
    if not path_allowed(kind, url):
        log.warning("notify_send_blocked", dest_id=dest, kind=kind.id, reason="path")
        return DeliveryResult(ok=False, failure=FailureClass.BLOCKED, detail="path")
    try:
        resp = await guarded_request(
            "POST", url, policy=policy_for(kind, config, url), dest_id=dest, headers=headers, json=json_body,
            content=content, data=data, auth=auth, timeout=timeout,
        )
    except (GuardBlocked, GuardTimeout, GuardNetworkError) as exc:
        return classify_error(exc)
    result = classify(resp, override)
    if not result.ok:
        log.info("notify_send_failed", dest_id=dest, kind=kind.id, failure=result.failure.value,
                 status=result.status_code)
    return result


def aggregate(results: Sequence[DeliveryResult]) -> DeliveryResult:
    sent = sum(1 for r in results if r.ok)
    if sent == len(results):
        return DeliveryResult(ok=True, status_code=results[-1].status_code)
    if sent:
        return DeliveryResult(ok=True, status_code=200, detail=f"sent {sent} of {len(results)}")
    return next((r for r in results if r.failure is not FailureClass.INVALID), results[0])
