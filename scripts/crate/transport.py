
from __future__ import annotations

import http.client
import socket
import ssl
from dataclasses import dataclass, field
from typing import BinaryIO, Callable, Dict, Iterator, Mapping, Optional, Protocol, Union
from urllib.parse import urlsplit

from scripts.crate.errors import NetworkError

CHUNK = 1024 * 1024
SOCKET_TIMEOUT_S = 120.0

Body = Union[bytes, BinaryIO, None]


@dataclass
class Response:

    status: int
    headers: Mapping[str, str]
    chunks: Iterator[bytes]
    close: Callable[[], None] = field(default=lambda: None)

    def read(self) -> bytes:
        try:
            return b"".join(self.chunks)
        finally:
            self.close()


class Transport(Protocol):

    def send(self, method: str, path: str, headers: Mapping[str, str], body: Body = None,
             length: Optional[int] = None) -> Response:
        ...


class HttpTransport:

    def __init__(self, base_url: str, timeout: float = SOCKET_TIMEOUT_S) -> None:
        parts = urlsplit(base_url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ValueError(f"not an http(s) URL: {base_url!r}")
        self.scheme, self.host, self.port = parts.scheme, parts.hostname, parts.port
        self.prefix = parts.path.rstrip("/")
        self.timeout = timeout

    def _connection(self) -> http.client.HTTPConnection:
        if self.scheme == "https":
            return http.client.HTTPSConnection(self.host, self.port, timeout=self.timeout, context=ssl.create_default_context())
        return http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)

    def send(self, method: str, path: str, headers: Mapping[str, str], body: Body = None,
             length: Optional[int] = None) -> Response:
        sent: Dict[str, str] = dict(headers)
        if body is not None and not isinstance(body, bytes):
            if length is None:
                raise ValueError("a streamed body needs its length")
            sent["Content-Length"] = str(length)
        conn = self._connection()
        try:
            conn.request(method, self.prefix + path, body=body, headers=sent)
            raw = conn.getresponse()
        except (OSError, http.client.HTTPException, socket.timeout) as exc:
            conn.close()
            raise NetworkError(f"{self.host}:{self.port or ''} unreachable: {type(exc).__name__}") from exc

        def chunks() -> Iterator[bytes]:
            while True:
                block = raw.read(CHUNK)
                if not block:
                    return
                yield block

        return Response(raw.status, {k.lower(): v for k, v in raw.getheaders()}, chunks(), conn.close)
