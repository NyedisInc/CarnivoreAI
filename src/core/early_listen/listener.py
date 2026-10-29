
from __future__ import annotations

import errno
import socket
import sys
import time
from typing import List

import structlog
import uvicorn

from src.core.graceful_shutdown import GracefulServer

logger = structlog.get_logger()

STARTUP_FAILURE_EXIT = 3

BIND_RETRY_S = 3.0

BIND_POLL_S = 0.1


class EarlyListenError(Exception):
    pass


class BindFailed(EarlyListenError):
    """The server address could not be bound.
    """

    def __init__(self, host: str, port: int, err_no: int, detail: str) -> None:
        super().__init__(f"could not bind {host}:{port}: {detail}")
        self.host = host
        self.port = port
        self.err_no = err_no


def _addresses(host: str, port: int) -> List[tuple]:
    infos = socket.getaddrinfo(host or None, port, family=socket.AF_UNSPEC,
                               type=socket.SOCK_STREAM, flags=socket.AI_PASSIVE)
    seen = []
    for family, type_, proto, _canon, sockaddr in infos:
        entry = (family, type_, proto, sockaddr)
        if entry not in seen:
            seen.append(entry)
    return seen


def _bind_one(family: int, type_: int, proto: int, sockaddr: tuple) -> socket.socket:
    sock = socket.socket(family, type_, proto)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if family == socket.AF_INET6 and hasattr(socket, "IPPROTO_IPV6"):
            sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
        sock.set_inheritable(False)
        sock.bind(sockaddr)
    except OSError:
        sock.close()
        raise
    return sock


def bind_listeners(host: str, port: int, backlog: int, *, retry_s: float = BIND_RETRY_S,
                   poll_s: float = BIND_POLL_S) -> List[socket.socket]:
    try:
        addresses = _addresses(host, port)
    except socket.gaierror as exc:
        raise BindFailed(host, port, exc.errno or 0, str(exc)) from exc
    deadline = time.monotonic() + retry_s
    while True:
        bound: List[socket.socket] = []
        try:
            for family, type_, proto, sockaddr in addresses:
                bound.append(_bind_one(family, type_, proto, sockaddr))
            for sock in bound:
                sock.listen(backlog)
            return bound
        except OSError as exc:
            for sock in bound:
                sock.close()
            if exc.errno == errno.EADDRINUSE and time.monotonic() < deadline:
                time.sleep(poll_s)
                continue
            raise BindFailed(host, port, exc.errno or 0, str(exc)) from exc


def serve_early(config: uvicorn.Config) -> None:
    try:
        sockets = bind_listeners(config.host, config.port, config.backlog,
                                 retry_s=BIND_RETRY_S, poll_s=BIND_POLL_S)
    except BindFailed as exc:
        logger.error("early_listen_bind_failed", host=exc.host, port=exc.port,
                     errno=exc.err_no, detail=str(exc),
                     note="the app's lifespan did not run; nothing was started")
        sys.exit(STARTUP_FAILURE_EXIT)
    logger.info("early_listen_bound", host=config.host, port=config.port,
                addresses=[str(s.getsockname()[0]) for s in sockets], backlog=config.backlog)
    server = GracefulServer(config)
    try:
        server.run(sockets=sockets)
    finally:
        for sock in sockets:
            sock.close()
    if not server.started:
        sys.exit(STARTUP_FAILURE_EXIT)
