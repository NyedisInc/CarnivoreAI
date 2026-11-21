
from __future__ import annotations

import http.client
import socket
import ssl
import threading
import time
from dataclasses import dataclass
from typing import Callable, List, Optional, Protocol, Tuple


@dataclass(frozen=True)
class RawResponse:

    status: int
    headers: List[Tuple[str, str]]
    body: bytes
    truncated: bool = False


class Transport(Protocol):

    def send(self, *, ip: str, port: int, tls: bool, host: str, method: str, target: str,
             headers: List[Tuple[str, str]], body: Optional[bytes], deadline: float, max_bytes: int) -> RawResponse: ...


class _Watchdog:

    def __init__(self, seconds: float) -> None:
        self.fired = False
        self._sock: Optional[socket.socket] = None
        self._lock = threading.Lock()
        self._timer = threading.Timer(seconds, self._fire)
        self._timer.daemon = True
        self._timer.start()

    def _shutdown(self) -> None:
        if self._sock is not None:
            try:
                self._sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def _fire(self) -> None:
        with self._lock:
            self.fired = True
            self._shutdown()

    def watch(self, sock: socket.socket) -> None:
        with self._lock:
            self._sock = sock
            if self.fired:
                self._shutdown()

    def cancel(self) -> None:
        self._timer.cancel()


class _PinnedHTTP(http.client.HTTPConnection):

    def __init__(self, ip: str, host: str, port: int, timeout: float, watch: Callable[[socket.socket], None]) -> None:
        super().__init__(host, port, timeout=timeout)
        self._ip, self._watch = ip, watch

    def connect(self) -> None:
        self.sock = socket.create_connection((self._ip, self.port), self.timeout)
        self._watch(self.sock)


class _PinnedHTTPS(http.client.HTTPSConnection):

    def __init__(self, ip: str, host: str, port: int, timeout: float, context: ssl.SSLContext,
                 watch: Callable[[socket.socket], None]) -> None:
        super().__init__(host, port, timeout=timeout, context=context)
        self._ip, self._watch = ip, watch

    def connect(self) -> None:
        sock = socket.create_connection((self._ip, self.port), self.timeout)
        self._watch(sock)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


class StdlibTransport:

    def send(self, *, ip: str, port: int, tls: bool, host: str, method: str, target: str,
             headers: List[Tuple[str, str]], body: Optional[bytes], deadline: float, max_bytes: int) -> RawResponse:
        remaining = max(0.1, deadline - time.monotonic())
        dog = _Watchdog(remaining)
        conn = (_PinnedHTTPS(ip, host, port, remaining, ssl.create_default_context(), dog.watch) if tls
                else _PinnedHTTP(ip, host, port, remaining, dog.watch))
        try:
            conn.putrequest(method, target, skip_accept_encoding=True)
            for name, value in headers:
                conn.putheader(name, value)
            conn.putheader("Content-Length", str(len(body or b"")))
            conn.endheaders(body or None)
            resp = conn.getresponse()
            chunks: List[bytes] = []
            size, truncated = 0, False
            while method != "HEAD":
                chunk = resp.read(min(65536, max_bytes + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
                if size > max_bytes:
                    truncated = True
                    break
            if dog.fired:
                raise TimeoutError("deadline")
            data = b"".join(chunks)[:max_bytes]
            return RawResponse(resp.status, list(resp.getheaders()), data, truncated)
        except (OSError, http.client.HTTPException) as exc:
            if dog.fired:
                raise TimeoutError("deadline") from exc
            raise
        finally:
            dog.cancel()
            conn.close()
