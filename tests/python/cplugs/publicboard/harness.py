
from __future__ import annotations

import asyncio
import socket
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Mapping, Optional, Tuple

from src.cplugs.publicboard.edge import EdgeConfig, PublicEdge
from src.cplugs.sdk.public_listener import ListenerSpec, PublicListener, PublicListenerError

HOST = "review.example.test"
LOOPBACK = "127.0.0.1"
LEAK = b"REACHED-HANDLER"


async def canary(scope: Any, receive: Any, send: Any) -> None:
    body = LEAK + b" " + scope["method"].encode()
    await send({"type": "http.response.start", "status": 200, "headers": [(b"content-length", str(len(body)).encode()), (b"connection", b"close")]})
    await send({"type": "http.response.body", "body": body})


CANARY_ROUTES = {("GET", "/api/board"): canary, ("POST", "/api/answers"): canary}


class ServerThread:

    def __init__(self, app: Any, deadline: float = 10.0, peer_allowed: Optional[Callable[[str], bool]] = None) -> None:
        self.app, self.deadline, self.peer_allowed = app, deadline, peer_allowed
        self.port = 0
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._ready = threading.Event()
        self._stop: Optional[asyncio.Event] = None
        self._error: Optional[BaseException] = None
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        asyncio.run(self._main())

    async def _main(self) -> None:
        self._loop, self._stop = asyncio.get_running_loop(), asyncio.Event()
        listener = PublicListener(self.app, ListenerSpec(host=LOOPBACK, port=0, request_deadline=self.deadline, peer_allowed=self.peer_allowed))
        try:
            await listener.start()
            self.port = listener.port
        except (PublicListenerError, OSError) as exc:
            self._error = exc
            self._ready.set()
            return
        self._ready.set()
        await self._stop.wait()
        await listener.stop()

    def __enter__(self) -> "ServerThread":
        self._thread.start()
        self._ready.wait(10)
        if self._error is not None:
            raise self._error
        return self

    def __exit__(self, *exc: Any) -> None:
        if self._loop is not None and self._stop is not None:
            self._loop.call_soon_threadsafe(self._stop.set)
        self._thread.join(10)


def edge_for(routes: Optional[Mapping[Tuple[str, str], Any]] = None, peers: Tuple[str, ...] = (LOOPBACK,)) -> PublicEdge:
    table = CANARY_ROUTES if routes is None else routes
    return PublicEdge(EdgeConfig.of(peers, [HOST]), table)


@dataclass
class Reply:

    status: Optional[int]
    headers: Dict[str, str] = field(default_factory=dict)
    body: bytes = b""
    responses: int = 0
    raw: bytes = b""

    def signature(self) -> Tuple[Any, ...]:
        return (self.status, tuple(sorted((k, v) for k, v in self.headers.items() if k != "date")), self.body)


def parse(raw: bytes) -> Reply:
    count = raw.count(b"HTTP/1.1 ")
    if not raw.startswith(b"HTTP/"):
        return Reply(None, raw=raw)
    head, _, body = raw.partition(b"\r\n\r\n")
    lines = head.split(b"\r\n")
    status = int(lines[0].split(b" ")[1])
    headers = {}
    for line in lines[1:]:
        name, _, value = line.partition(b":")
        headers[name.decode().strip().lower()] = value.decode().strip()
    return Reply(status, headers, body, count, raw)


def exchange(port: int, raw: bytes, timeout: float = 3.0) -> Reply:
    chunks = []
    with socket.create_connection((LOOPBACK, port), timeout=timeout) as conn:
        try:
            conn.sendall(raw)
        except OSError:
            pass
        conn.settimeout(timeout)
        while True:
            try:
                data = conn.recv(65536)
            except (socket.timeout, ConnectionResetError):
                break
            if not data:
                break
            chunks.append(data)
    return parse(b"".join(chunks))


def request(method: str, target: str, *, host: Optional[str] = HOST, headers: Tuple[Tuple[str, str], ...] = (), body: bytes = b"",
            version: str = "HTTP/1.1") -> bytes:
    lines = [f"{method} {target} {version}"]
    if host is not None:
        lines.append(f"Host: {host}")
    lines += [f"{name}: {value}" for name, value in headers]
    return ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1") + body
