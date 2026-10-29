
from __future__ import annotations

import asyncio
import contextlib
import time
from typing import Any, AsyncIterator, Optional
from urllib.parse import urlsplit

import httpx
import structlog

from src.tui.token_store import LockBusy, TokenPair, TokenStore

logger = structlog.get_logger(__name__)

LOOPBACK_HOST = "127.0.0.1"
VERIFY_PATH = "/api/v1/auth/verify"
REFRESH_PATH = "/api/v1/auth/refresh"
STATUS_PATH = "/api/v1/auth/status"
DEFAULT_ACCESS_TTL = 900


class AuthRequired(Exception):
    pass


class LoginError(Exception):

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class ServerUnavailable(Exception):
    """The server did not answer (down, restarting, 5xx, 429); the saved pair is kept.

    ``retry_after`` is the server's Retry-After in seconds when it sent one.
    """

    def __init__(self, reason: str = "", retry_after: Optional[float] = None) -> None:
        super().__init__(reason)
        self.retry_after = retry_after


def _retry_after(resp: httpx.Response) -> Optional[float]:
    try:
        return float(resp.headers["retry-after"])
    except (KeyError, ValueError):
        return None


def server_base_url(port: int) -> str:
    return f"http://{LOOPBACK_HOST}:{port}"


def _require_loopback(base_url: str) -> str:
    if urlsplit(base_url).hostname != LOOPBACK_HOST:
        raise ValueError("the tui only talks to the local server on 127.0.0.1")
    return base_url.rstrip("/")


def _require_relative_path(path: str) -> None:
    try:
        absolute = httpx.URL(path).is_absolute_url
    except httpx.InvalidURL:
        raise ValueError("the tui only requests paths on the local server") from None
    if not path.startswith("/") or path.startswith("//") or "\\" in path or absolute:
        raise ValueError("the tui only requests paths on the local server")


def _release_if_acquired(ctx: Any, fut: "asyncio.Future[Any]") -> None:
    if not fut.cancelled() and fut.exception() is None:
        ctx.__exit__(None, None, None)


def _pair_from(body: dict[str, Any]) -> TokenPair:
    access = body.get("access_token") or body.get("token")
    refresh = body.get("refresh_token")
    if not access or not refresh:
        raise ValueError("auth response carried no token pair")
    ttl = body.get("expires_in") or DEFAULT_ACCESS_TTL
    return TokenPair(str(access), str(refresh), time.time() + float(ttl))


class ApiClient:

    def __init__(
        self,
        store: TokenStore,
        base_url: str,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        self._store = store
        self.base_url = _require_loopback(base_url)
        self._http = httpx.AsyncClient(
            base_url=self.base_url,
            transport=transport,
            timeout=10.0,
            trust_env=False,
            follow_redirects=False,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    @contextlib.asynccontextmanager
    async def _locked(self) -> AsyncIterator[None]:
        ctx = self._store.locked()
        acquire = asyncio.ensure_future(asyncio.to_thread(ctx.__enter__))
        try:
            await asyncio.shield(acquire)
        except asyncio.CancelledError:
            acquire.add_done_callback(lambda fut: _release_if_acquired(ctx, fut))
            raise
        except LockBusy:
            raise ServerUnavailable("token_file_busy") from None
        try:
            yield
        finally:
            ctx.__exit__(None, None, None)

    async def _post(self, path: str, json_body: dict[str, str]) -> httpx.Response:
        try:
            return await self._http.post(path, json=json_body)
        except httpx.HTTPError as exc:
            raise ServerUnavailable(type(exc).__name__) from None

    async def login(self, code: str) -> None:
        try:
            resp = await self._post(VERIFY_PATH, {"code": code})
        except ServerUnavailable:
            raise LoginError("unavailable") from None
        if resp.status_code == 429:
            raise LoginError("rate_limited")
        if resp.status_code != 200:
            raise LoginError("unavailable" if resp.status_code >= 500 else "invalid")
        try:
            pair = _pair_from(resp.json())
        except ValueError:
            raise LoginError("unavailable") from None
        try:
            async with self._locked():
                self._store.save(pair)
        except ServerUnavailable:
            raise LoginError("busy") from None

    async def _refresh(self, stale_refresh: Optional[str]) -> TokenPair:
        async with self._locked():
            current = self._store.load()
            if current is None:
                raise AuthRequired()
            if stale_refresh is not None and current.refresh_token != stale_refresh:
                return current
            resp = await self._post(REFRESH_PATH, {"refresh_token": current.refresh_token})
            if resp.status_code >= 500:
                raise ServerUnavailable(str(resp.status_code))
            if resp.status_code in (401, 403):
                logger.info("tui_refresh_refused", status=resp.status_code)
                self._store.clear_if(current.refresh_token)
                raise AuthRequired()
            if resp.status_code != 200:
                logger.info("tui_refresh_not_spent", status=resp.status_code)
                raise ServerUnavailable(str(resp.status_code), _retry_after(resp))
            try:
                pair = _pair_from(resp.json())
            except ValueError:
                self._store.clear_if(current.refresh_token)
                raise AuthRequired() from None
            self._store.save(pair)
            logger.info("tui_refresh_rotated")
            return pair

    async def _access(self) -> TokenPair:
        pair = self._store.load()
        if pair is None:
            raise AuthRequired()
        if pair.access_fresh():
            return pair
        return await self._refresh(pair.refresh_token)

    async def access_token(self) -> str:
        return (await self._access()).access_token

    async def refresh_access_token(self) -> str:
        pair = self._store.load()
        return (await self._refresh(pair.refresh_token if pair else None)).access_token

    async def reject_access_token(self) -> None:
        pair = self._store.load()
        if pair is not None:
            async with self._locked():
                self._store.clear_if(pair.refresh_token)
        raise AuthRequired()

    async def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        _require_relative_path(path)
        extra = kwargs.pop("headers", {})
        pair = await self._access()
        for attempt in (0, 1):
            headers = {**extra, "Authorization": f"Bearer {pair.access_token}"}
            try:
                resp = await self._http.request(method, path, headers=headers, **kwargs)
            except httpx.HTTPError as exc:
                raise ServerUnavailable(type(exc).__name__) from None
            if resp.status_code != 401:
                return resp
            if attempt == 1:
                async with self._locked():
                    self._store.clear_if(pair.refresh_token)
                raise AuthRequired()
            pair = await self._refresh(pair.refresh_token)
        raise AuthRequired()

    async def check_session(self) -> bool:
        try:
            return (await self.request("GET", STATUS_PATH)).status_code == 200
        except AuthRequired:
            return False
