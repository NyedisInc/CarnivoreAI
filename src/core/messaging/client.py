
from __future__ import annotations

import asyncio
import dataclasses
import errno
import ipaddress
import json
import socket
from typing import Any, Optional, Protocol, Tuple

import structlog

from urllib.parse import urlsplit

from src.core.messaging import contract
from src.core.messaging.ddl import STATUS_FAILED, STATUS_UNCONFIRMED
from src.core.notifications import http

log = structlog.get_logger(__name__)

TIMEOUT_SECONDS = 10.0

UNREACHABLE = "provider_unreachable"
UNAUTHORIZED = "provider_unauthorized"
REFUSED = "provider_refused"
UNKNOWN_CONVERSATION = "unknown_conversation"
TEXT_TOO_LONG = "text_too_long"
NOT_READY = "not_ready"
RATE_LIMITED = "rate_limited"
BAD_ANSWER = "cpp_unsupported"
UNCERTAIN = "send_uncertain"
MAY_HAVE_SENT = "may have been sent; do not resend"
UNCERTAIN_BODY_CODES = frozenset({"send_in_doubt", "in_progress"})
BLOCKED = "provider_blocked"
REJECTED = "provider_rejected"

REPLAY_HEADER = "idempotent-replayed"

MAX_DETAIL_CHARS = 120

ELLIPSIS = "..."

LOCAL_NETWORK_DETAIL = ("the app may not have Local Network permission "
                        "(System Settings > Privacy & Security > Local Network)")

MAY_HAVE_ACCEPTED = "the provider may have accepted the send"


class ProviderError(Exception):

    def __init__(self, code: str, *, status: Optional[int] = None, retry_after: Optional[int] = None,
                 detail: Optional[str] = None) -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.status = status
        self.retry_after = retry_after
        self.detail = detail

    @property
    def log_status(self) -> str:
        return STATUS_UNCONFIRMED if self.code == UNCERTAIN else STATUS_FAILED

    @property
    def owner_text(self) -> str:
        if self.code == UNCERTAIN:
            return f"{MAY_HAVE_SENT}: {self.detail}" if self.detail else MAY_HAVE_SENT
        return self.detail or self.code


class ProviderClient(Protocol):

    async def capabilities(self) -> contract.Capabilities: ...

    async def conversations(self) -> Tuple[contract.ConversationEntry, ...]: ...

    async def send(self, conversation: str, text: str, *, reply_to: Optional[str],
                   client_ref: str) -> contract.SendResult: ...

    async def events_page(self, after: int, limit: int = 200) -> contract.EventsPage: ...


def policy_for(*, allow_private: bool, allow_plain_http: bool) -> http.HostPolicy:
    return http.HostPolicy(any_host=True, allow_private=allow_private, allow_plain_http=allow_plain_http,
                           switchable=True)


def error_snippet(body: bytes, token: str = "") -> Optional[str]:
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    for key in ("detail", "message", "error"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            text = "".join(ch if ch.isprintable() else " " for ch in value).strip()
            if token:
                text = text.replace(token, "***")
            if len(text) > MAX_DETAIL_CHARS:
                text = text[:MAX_DETAIL_CHARS - len(ELLIPSIS)].rstrip() + ELLIPSIS
            return text
    return None


def _is_lan(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    return (ip.is_private or ip.is_link_local) and not ip.is_loopback


async def local_network_hint(exc: BaseException, base_url: str) -> Optional[str]:
    seen, cur = set(), exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        if isinstance(cur, OSError) and cur.errno == errno.EHOSTUNREACH:
            break
        cur = cur.__cause__ or cur.__context__
    else:
        return None
    host = urlsplit(base_url).hostname or ""
    if _is_lan(host):
        return LOCAL_NETWORK_DETAIL
    try:
        infos = await asyncio.to_thread(socket.getaddrinfo, host, None)
    except (OSError, UnicodeError):
        return None
    return LOCAL_NETWORK_DETAIL if any(_is_lan(str(i[4][0])) for i in infos) else None


def is_replay_answer(headers: Any) -> bool:
    value = headers.get(REPLAY_HEADER) if hasattr(headers, "get") else None
    return isinstance(value, str) and value.strip().lower() == "true"


def body_error_code(body: bytes) -> Optional[str]:
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    value = data.get("error") if isinstance(data, dict) else None
    return value if isinstance(value, str) else None


def _error_for(status: int, headers: Any, body: bytes = b"", token: str = "") -> ProviderError:
    if status in (409, 422) and body_error_code(body) in UNCERTAIN_BODY_CODES:
        return ProviderError(UNCERTAIN, status=status, detail=error_snippet(body, token))
    retry = headers.get("retry-after") if hasattr(headers, "get") else None
    retry_after = int(retry) if isinstance(retry, str) and retry.isdigit() else None
    code = {401: UNAUTHORIZED, 403: REFUSED, 404: UNKNOWN_CONVERSATION, 413: TEXT_TOO_LONG, 429: RATE_LIMITED,
            503: NOT_READY}.get(status)
    if code is None:
        code = REJECTED if 400 <= status < 500 else UNREACHABLE
    detail = error_snippet(body, token) if 400 <= status < 500 or status == 503 else None
    return ProviderError(code, status=status, retry_after=retry_after, detail=detail)


class HttpProviderClient:

    def __init__(self, provider_id: str, base_url: str, token: str, *, allow_private: bool = False,
                 allow_plain_http: bool = False, resolver: Optional[http.Resolver] = None) -> None:
        self.provider_id = provider_id
        self.base_url = base_url.rstrip("/")
        self._token = token
        self.policy = policy_for(allow_private=allow_private, allow_plain_http=allow_plain_http)
        self._resolver = resolver

    @property
    def token(self) -> str:
        return self._token

    async def _call(self, method: str, path: str, *, body: Any = None,
                    headers: Optional[dict] = None) -> Any:
        return (await self._request(method, path, body=body, headers=headers))[0]

    async def _request(self, method: str, path: str, *, body: Any = None,
                       headers: Optional[dict] = None) -> Tuple[Any, Any]:
        try:
            resp = await http.guarded_request(
                method, self.base_url + path, policy=self.policy, dest_id=self.provider_id,
                headers={"authorization": f"Bearer {self._token}", "accept": "application/json", **(headers or {})},
                json=body, timeout=TIMEOUT_SECONDS, resolver=self._resolver)
        except http.GuardTimeout:
            raise ProviderError(UNCERTAIN if method == "POST" else UNREACHABLE) from None
        except http.GuardBlocked as exc:
            log.warning("messaging_provider_blocked", provider_id=self.provider_id, reason=exc.reason)
            raise ProviderError(BLOCKED) from None
        except http.GuardError as exc:
            raise ProviderError(UNREACHABLE, detail=await local_network_hint(exc, self.base_url)) from None
        if not 200 <= resp.status < 300:
            err = _error_for(resp.status, resp.headers, resp.body, self._token)
            log.info("messaging_provider_status", provider_id=self.provider_id, call=path, status=resp.status,
                     code=err.code, detail=err.detail)
            raise err
        try:
            return (json.loads(resp.body.decode("utf-8")) if not resp.truncated else None), resp.headers
        except (UnicodeDecodeError, ValueError):
            raise ProviderError(BAD_ANSWER) from None

    async def capabilities(self) -> contract.Capabilities:
        try:
            return contract.parse_capabilities(await self._call("GET", "/cpp/v1/capabilities"))
        except contract.ContractError:
            raise ProviderError(BAD_ANSWER) from None

    async def conversations(self) -> Tuple[contract.ConversationEntry, ...]:
        try:
            return contract.parse_conversations(await self._call("GET", "/cpp/v1/conversations"))
        except contract.ContractError:
            raise ProviderError(BAD_ANSWER) from None

    async def send(self, conversation: str, text: str, *, reply_to: Optional[str],
                   client_ref: str) -> contract.SendResult:
        body = {"conversation": conversation, "text": text, "reply_to": reply_to, "client_ref": client_ref}
        headers = {"idempotency-key": client_ref}
        for attempt in (1, 2):
            try:
                answer, reply_headers = await self._request("POST", "/cpp/v1/messages", body=body, headers=headers)
                result = contract.parse_send_result(answer)
            except ProviderError as exc:
                if exc.code != UNCERTAIN or attempt == 2:
                    raise
                continue
            except contract.ContractError:
                if attempt == 2:
                    raise ProviderError(BAD_ANSWER, detail=MAY_HAVE_ACCEPTED) from None
                continue
            if not result.status_ok:
                log.warning("messaging_send_status_missing", provider_id=self.provider_id, call="/cpp/v1/messages")
            if attempt == 2 and is_replay_answer(reply_headers):
                log.info("messaging_idempotency_replay_seen", provider_id=self.provider_id)
                result = dataclasses.replace(result, replayed=True)
            return result
        raise ProviderError(UNCERTAIN)

    async def events_page(self, after: int, limit: int = 200) -> contract.EventsPage:
        try:
            return contract.parse_events_page(await self._call(
                "GET", f"/cpp/v1/events?after={int(after)}&routable=1&limit={max(1, min(500, int(limit)))}"))
        except contract.ContractError:
            raise ProviderError(BAD_ANSWER) from None
