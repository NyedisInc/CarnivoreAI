
from __future__ import annotations

import asyncio
import ssl
from dataclasses import dataclass
from typing import Any, Callable, Dict, Mapping, Optional, Tuple

import httpx
import structlog

logger = structlog.get_logger()

TIMEOUT_SECONDS = 10.0


class ArgentError(Exception):

    def __init__(self, message: str, status: int = 0, code: str = "", body: Optional[Mapping[str, Any]] = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.body: Mapping[str, Any] = body or {}


class Unreachable(ArgentError):
    pass


class RateLimited(ArgentError):

    def __init__(self, message: str, status: int = 429, code: str = "", body: Optional[Mapping[str, Any]] = None, retry_after: Optional[float] = None) -> None:
        super().__init__(message, status, code, body)
        self.retry_after = retry_after


def parse_retry_after(value: Optional[str]) -> Optional[float]:
    try:
        return float(int(value.strip())) if value else None
    except ValueError:
        return None


class Unauthorized(ArgentError):
    pass


class NotFound(ArgentError):
    pass


@dataclass(frozen=True)
class ArgentResponse:

    status: int
    body: Dict[str, Any]
    not_modified: bool = False


def error_code(body: Mapping[str, Any]) -> str:
    err = body.get("error")
    if isinstance(err, str):
        return err
    if isinstance(err, Mapping) and isinstance(err.get("code"), str):
        return str(err["code"])
    return ""


class ArgentClient:

    def __init__(self, base_url: str, token_provider: Callable[[], Optional[str]] = lambda: None, *, ca_path: str = "",
                 transport: Optional[httpx.AsyncBaseTransport] = None, on_unauthorized: Optional[Callable[[], None]] = None,
                 timeout: float = TIMEOUT_SECONDS) -> None:
        self._base = base_url.rstrip("/")
        self._token = token_provider
        self._ca_path = ca_path
        self._transport = transport
        self._on_unauthorized = on_unauthorized
        self._timeout = timeout
        self._etags: Dict[str, Tuple[str, Dict[str, Any]]] = {}

    def _verify(self) -> Any:
        if not self._ca_path:
            return True
        try:
            return ssl.create_default_context(cafile=self._ca_path)
        except (OSError, ssl.SSLError) as exc:
            raise Unreachable("the argent ca file could not be read") from exc

    async def request(self, method: str, path: str, *, json: Any = None, params: Optional[Mapping[str, Any]] = None, auth: bool = True,
                      headers: Optional[Mapping[str, str]] = None) -> ArgentResponse:
        url = f"{self._base}{path}"
        sent: Dict[str, str] = {"Accept": "application/json"}
        if auth:
            token = self._token()
            if token:
                sent["Authorization"] = f"Bearer {token}"
        cache_key = f"{url}?{sorted((params or {}).items())}"
        cached = self._etags.get(cache_key) if method == "GET" else None
        if cached:
            sent["If-None-Match"] = cached[0]
        for name, value in (headers or {}).items():
            if name.lower() not in {key.lower() for key in sent}:
                sent[name] = value
        verify = await asyncio.to_thread(self._verify)
        try:
            async with httpx.AsyncClient(transport=self._transport, verify=verify, timeout=self._timeout, follow_redirects=False) as http:
                reply = await http.request(method, url, headers=sent, json=json, params=params)
        except httpx.HTTPError as exc:
            logger.info("argent_call_unreachable", path=path, error_type=type(exc).__name__)
            raise Unreachable(f"argent did not answer ({type(exc).__name__})") from None
        return self._read(method, path, cache_key, cached, reply)

    def _read(self, method: str, path: str, cache_key: str, cached: Optional[Tuple[str, Dict[str, Any]]], reply: httpx.Response) -> ArgentResponse:
        status = reply.status_code
        if status == 304 and cached:
            return ArgentResponse(status, cached[1], True)
        try:
            parsed = reply.json() if reply.content else {}
        except ValueError:
            parsed = {}
        body: Dict[str, Any] = parsed if isinstance(parsed, dict) else {"items": parsed}
        if status == 401:
            logger.info("argent_call_unauthorized", path=path)
            if self._on_unauthorized is not None:
                self._on_unauthorized()
            raise Unauthorized("argent did not accept the login", status, error_code(body) or "unauthorized", body)
        if status >= 500:
            raise Unreachable(f"argent answered {status}", status, error_code(body), body)
        if status == 404:
            raise NotFound("argent has no such route", status, error_code(body) or "not_found", body)
        if status == 429:
            raise RateLimited("argent rate-limited the call", status, error_code(body), body, parse_retry_after(reply.headers.get("retry-after")))
        if status >= 400:
            raise ArgentError(f"argent refused ({status})", status, error_code(body), body)
        etag = reply.headers.get("etag")
        if method == "GET" and etag:
            self._etags[cache_key] = (etag, body)
        return ArgentResponse(status, body)

    async def get(self, path: str, **kwargs: Any) -> ArgentResponse:
        return await self.request("GET", path, **kwargs)

    async def post(self, path: str, **kwargs: Any) -> ArgentResponse:
        return await self.request("POST", path, **kwargs)
