
from __future__ import annotations

import asyncio
import re
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict, Mapping, Optional
from urllib.parse import quote, urlsplit

import httpx
from websockets.asyncio.client import connect as _ws_connect
from websockets.exceptions import InvalidStatus, WebSocketException

from src.core.byoai.contracts import (
    AUTH_BEARER, AUTH_CUSTOM_HEADER, AUTH_FAL_KEY, AUTH_X_API_KEY, AUTH_XI_API_KEY,
    MAX_TIMEOUT_S, ByoaiError, ByoaiUnreachable, Connection, MissingKey, ProviderHTTPError, ProviderTimeout,
)
from src.core.byoai.presets import auth_style, get_preset

MAX_BODY_EXCERPT = 2048

ANTHROPIC_VERSION = "2023-06-01"

DEFAULT_TIMEOUT = httpx.Timeout(120.0, connect=10.0)

_HEADER_NAME = re.compile(r"[A-Za-z0-9-]{1,64}")


def validate_base_url(url: str) -> str:
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ByoaiError("base url must be http or https with a host")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ByoaiError("base url may not carry credentials, a query or a fragment")
    return url.strip().rstrip("/")


def host_of(url: str) -> str:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    return f"{host}:{parts.port}" if parts.port else host


def key_origin(url: str) -> str:
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower().rstrip(".")
    if ":" in host:
        host = f"[{host}]"
    default = {"http": 80, "https": 443}.get(parts.scheme.lower())
    port = parts.port
    return f"{parts.scheme.lower()}://{host}" + (f":{port}" if port and port != default else "")


def join_url(base_url: str, path: str) -> str:
    base = validate_base_url(base_url)
    if path and not path.startswith("/"):
        raise ByoaiError("path must start with /")
    if path.startswith("//") or "\\" in path or re.search(r"[\x00-\x20]", path):
        raise ByoaiError("path is not a plain path")
    if ".." in path.split("?", 1)[0].split("/"):
        raise ByoaiError("path may not contain ..")
    return base + path


def auth_headers(connection: Connection, key: Optional[str]) -> Dict[str, str]:
    style = auth_style(get_preset(connection.preset), connection.options)
    headers: Dict[str, str] = {}
    if style == AUTH_X_API_KEY:
        headers["anthropic-version"] = ANTHROPIC_VERSION
    if not key:
        return headers
    if "\r" in key or "\n" in key:
        raise ByoaiError("key has a line break")
    if style == AUTH_BEARER:
        headers["Authorization"] = f"Bearer {key}"
    elif style == AUTH_X_API_KEY:
        headers["x-api-key"] = key
    elif style == AUTH_XI_API_KEY:
        headers["xi-api-key"] = key
    elif style == AUTH_FAL_KEY:
        headers["Authorization"] = f"Key {key}"
    elif style == AUTH_CUSTOM_HEADER:
        name = str(connection.options.get("auth_header") or "")
        if not _HEADER_NAME.fullmatch(name):
            raise ByoaiError("custom auth needs a header name in options.auth_header")
        headers[name] = key
    return headers


def scrub(text: str, key: Optional[str]) -> str:
    if key:
        pct = quote(key, safe="")
        low = re.sub(r"%[0-9A-F]{2}", lambda m: m.group().lower(), pct)
        for form in (key, key.replace("/", "\\/"), pct, low):
            text = text.replace(form, "***")
    return text[:MAX_BODY_EXCERPT]


def _check(connection: Connection, key: Optional[str]) -> None:
    preset = get_preset(connection.preset)
    if preset.key_required and not key:
        raise MissingKey(f"connection {connection.id} needs a key")
    if key and connection.key_host != key_origin(connection.base_url):
        raise MissingKey(f"connection {connection.id} has no key bound to {key_origin(connection.base_url)}")


def _http_error(response: httpx.Response, key: Optional[str]) -> ProviderHTTPError:
    return ProviderHTTPError(response.status_code, scrub(response.text, key))


def bound_timeout(seconds: Optional[float]) -> httpx.Timeout:
    if not seconds or seconds <= 0:
        return DEFAULT_TIMEOUT
    return httpx.Timeout(min(float(seconds), MAX_TIMEOUT_S), connect=DEFAULT_TIMEOUT.connect)


def _map(exc: httpx.HTTPError) -> ByoaiError:
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
        return ByoaiUnreachable(type(exc).__name__)
    if isinstance(exc, httpx.TimeoutException):
        return ProviderTimeout(type(exc).__name__)
    return ByoaiError(f"request failed: {type(exc).__name__}")


def _build(connection: Connection, key: Optional[str], path: str,
           headers: Optional[Mapping[str, str]]) -> tuple:
    _check(connection, key)
    return join_url(connection.base_url, path), {**(headers or {}), **auth_headers(connection, key)}


async def raw(connection: Connection, key: Optional[str], method: str, path: str, *,
              json: Any = None, content: Optional[bytes] = None,
              params: Optional[Mapping[str, Any]] = None,
              headers: Optional[Mapping[str, str]] = None,
              timeout: Optional[float] = None) -> httpx.Response:
    url, merged = _build(connection, key, path, headers)
    bound = bound_timeout(timeout)
    try:
        async with httpx.AsyncClient(follow_redirects=False, trust_env=False, timeout=bound) as client:
            return await asyncio.wait_for(client.request(method, url, json=json, content=content,
                                                         params=params, headers=merged), bound.read)
    except asyncio.TimeoutError:
        raise ProviderTimeout("WallClockTimeout") from None
    except httpx.HTTPError as exc:
        raise _map(exc) from None


async def request(connection: Connection, key: Optional[str], method: str, path: str,
                  **kwargs: Any) -> httpx.Response:
    response = await raw(connection, key, method, path, **kwargs)
    if response.status_code >= 300:
        raise _http_error(response, key)
    return response


@asynccontextmanager
async def stream(connection: Connection, key: Optional[str], method: str, path: str, *,
                 json: Any = None, content: Optional[bytes] = None,
                 params: Optional[Mapping[str, Any]] = None,
                 headers: Optional[Mapping[str, str]] = None,
                 timeout: Optional[float] = None) -> AsyncIterator[httpx.Response]:
    url, merged = _build(connection, key, path, headers)
    try:
        async with httpx.AsyncClient(follow_redirects=False, trust_env=False,
                                     timeout=bound_timeout(timeout)) as client:
            async with client.stream(method, url, json=json, content=content,
                                     params=params, headers=merged) as response:
                if response.status_code >= 300:
                    await response.aread()
                    raise _http_error(response, key)
                yield response
    except httpx.HTTPError as exc:
        raise _map(exc) from None


class _NoRedirectConnect(_ws_connect):

    def process_redirect(self, exc: Exception) -> Exception:
        return exc


@asynccontextmanager
async def raw_ws(connection: Connection, key: Optional[str], path: str, *,
                 headers: Optional[Mapping[str, str]] = None,
                 subprotocols: Optional[list] = None,
                 open_timeout: float = 10.0) -> AsyncIterator[Any]:
    url, merged = _build(connection, key, path, headers)
    ws_url = "ws" + url[len("http"):]
    try:
        ws = await _NoRedirectConnect(ws_url, additional_headers=merged,
                                      subprotocols=subprotocols, open_timeout=open_timeout,
                                      proxy=None)
    except InvalidStatus as exc:
        body = exc.response.body.decode("utf-8", "replace") if exc.response.body else ""
        raise ProviderHTTPError(exc.response.status_code, scrub(body, key)) from None
    except TimeoutError:
        raise ProviderTimeout("websocket open timed out") from None
    except OSError as exc:
        raise ByoaiUnreachable(f"websocket failed: {type(exc).__name__}") from None
    except WebSocketException as exc:
        raise ByoaiError(f"websocket failed: {type(exc).__name__}") from None
    try:
        yield ws
    finally:
        await ws.close()
