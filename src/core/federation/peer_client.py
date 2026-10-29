
from __future__ import annotations

import asyncio
import os
import socket
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Optional

from src.core.federation import peer_http, peer_prove, peer_token
from src.core.federation.pairing import PROTOCOL_MAJOR
from src.core.relay_identity.device_key import b64url as _b64url

API = "/api/v1/federation"
REQUEST_TIMEOUT = 5.0
REFRESH_MARGIN = 180.0


def _url(path: str) -> str:
    return path if path.startswith("/api/") else f"/api/v1{path}"


class PeerUnreachable(Exception):

    def __init__(self, message: str, hard: bool = False) -> None:
        super().__init__(message)
        self.hard = hard


class PeerRefused(Exception):

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Route:

    kind: str
    target: Any
    tag: str = ""


async def _prove_on(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, route: Route,
                    peer_public_key: str, peer_install_id: str, grant_id: str) -> bool:
    nonce = os.urandom(16)
    body = {"nonce": _b64url(nonce), **({"grant_id": grant_id} if grant_id else {}), **({"route": route.tag} if route.tag else {})}
    reply = await peer_http.exchange(reader, writer, "POST", f"{API}/prove", body=body, keep_alive=True)
    if reply.status_code != 200:
        raise PeerUnreachable(f"prove answered http_{reply.status_code}", hard=reply.status_code == 404)
    try:
        data = reply.json()
        return (data.get("install_id") == peer_install_id
                and peer_prove.verify(peer_public_key, nonce, peer_install_id, data.get("signature"), route.tag))
    except (ValueError, AttributeError):
        return False


async def _connected(route: Route, timeout: float, action: Callable[[Any, Any], Awaitable[Any]]) -> Any:
    async def run() -> Any:
        reader, writer = await peer_http.open_connection(route.kind, route.target)
        try:
            return await action(reader, writer)
        finally:
            writer.close()

    try:
        return await asyncio.wait_for(run(), timeout)
    except asyncio.TimeoutError:
        raise PeerUnreachable("timeout") from None
    except (peer_http.ReplyTooLarge, ValueError, asyncio.IncompleteReadError) as exc:
        raise PeerUnreachable(f"bad answer ({type(exc).__name__})", hard=True) from None
    except OSError as exc:
        raise PeerUnreachable(f"refused ({type(exc).__name__})", hard=True) from None


async def prove_route(route: Route, peer_public_key: str, peer_install_id: str, *, grant_id: str = "",
                      timeout: float = REQUEST_TIMEOUT) -> bool:
    return await _connected(route, timeout, lambda r, w: _prove_on(r, w, route, peer_public_key, peer_install_id, grant_id))


class PeerClient:

    def __init__(self, route: Route, *, grant_id: str, peer_install_id: str, sign: Callable[[bytes], str],
                 peer_public_key: Optional[str] = None, timeout: float = REQUEST_TIMEOUT, clock: Callable[[], float] = time.time) -> None:
        self.route, self._grant, self._peer, self._sign = route, grant_id, peer_install_id, sign
        self._timeout, self._clock, self._pinned, self._proven = timeout, clock, peer_public_key, False
        self._token: Optional[str] = None
        self._expires = 0.0

    @property
    def grant_id(self) -> str:
        return self._grant

    async def _send(self, method: str, path: str, token: Optional[str], body: Any,
                    timeout: Optional[float] = None, max_body: int = peer_http.MAX_BODY,
                    content: Optional[bytes] = None, headers: Optional[Dict[str, str]] = None) -> peer_http.Reply:
        limit = timeout or self._timeout
        if self.route.kind != "tcp":
            return await _connected(self.route, limit, lambda r, w: peer_http.exchange(r, w, method, path, token=token, body=body, max_body=max_body,
                                                                                 content=content, headers=headers))

        async def bound(reader: Any, writer: Any) -> peer_http.Reply:
            if self._pinned is None or not self.route.tag:
                raise PeerRefused("identity_changed")
            if not await _prove_on(reader, writer, self.route, self._pinned, self._peer, self._grant):
                raise PeerRefused("identity_changed")
            return await peer_http.exchange(reader, writer, method, path, token=token, body=body, max_body=max_body,
                                            content=content, headers=headers)

        return await _connected(self.route, limit * 2, bound)

    async def _mint(self) -> str:
        if self._pinned is not None and not self._proven and self.route.kind != "tcp":
            if not await prove_route(self.route, self._pinned, self._peer, grant_id=self._grant, timeout=self._timeout):
                raise PeerRefused("identity_changed")
            self._proven = True
        ts, nonce = int(self._clock()), os.urandom(16)
        signature = self._sign(peer_token.challenge_message(self._grant, self._peer, ts, nonce))
        response = await self._send("POST", f"{API}/token", None, {
            "grant_id": self._grant, "ts": ts, "nonce": _b64url(nonce), "signature": signature})
        if response.status_code in (401, 403):
            raise PeerRefused("grant_invalid")
        if response.status_code != 200:
            raise PeerRefused(f"http_{response.status_code}")
        data = response.json()
        if data.get("install_id") != self._peer:
            raise PeerRefused("identity_changed")
        self._token = str(data["token"])
        self._expires = self._clock() + float(data.get("expires_in", peer_token.TOKEN_TTL_SECONDS))
        return self._token

    async def bearer(self, force: bool = False) -> str:
        if force or self._token is None or self._clock() >= self._expires - REFRESH_MARGIN:
            return await self._mint()
        return self._token

    async def proven_socket(self) -> socket.socket:
        async def bound(reader: Any, writer: Any) -> socket.socket:
            if self._pinned is None or not self.route.tag:
                raise PeerRefused("identity_changed")
            if not await _prove_on(reader, writer, self.route, self._pinned, self._peer, self._grant):
                raise PeerRefused("identity_changed")
            return socket.socket(fileno=os.dup(writer.get_extra_info("socket").fileno()))

        return await _connected(self.route, self._timeout * 2, bound)

    async def request(self, method: str, path: str, *, json: Any = None, timeout: Optional[float] = None,
                      max_body: int = peer_http.MAX_BODY, content: Optional[bytes] = None,
                      headers: Optional[Dict[str, str]] = None) -> peer_http.Reply:
        """One authenticated request under ``/api/v1/federation`` or any absolute ``/api/...`` path.

        ``timeout`` overrides the per-request deadline (a restart on the far end outlasts the default).
        ``max_body`` is the reply cap; only the session listing asks for more than the default. ``content`` and
        ``headers`` send raw bytes with extra headers (a Pack blob chunk) in place of ``json``.
        Raises: PeerUnreachable, PeerRefused (the token could not be earned).
        Example: (await client.request("GET", "/federation/hello")).json()
        """
        token = self._token if self._clock() < self._expires - REFRESH_MARGIN else await self._mint()
        response = await self._send(method, _url(path), token, json, timeout, max_body, content, headers)
        if response.status_code == 401:
            response = await self._send(method, _url(path), await self._mint(), json, timeout, max_body, content, headers)
        return response

    async def public(self, method: str, path: str, *, json: Any = None) -> peer_http.Reply:
        return await self._send(method, _url(path), None, json)


def hello_ok(data: dict, peer_install_id: str) -> Optional[str]:
    if data.get("install_id") != peer_install_id:
        return "identity_changed"
    if data.get("protocol") != PROTOCOL_MAJOR:
        return "incompatible"
    return None
