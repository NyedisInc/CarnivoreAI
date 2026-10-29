
from __future__ import annotations

import socket
import time
from typing import List
from unittest import mock

from src.cplugs.sdk import public_listener
from src.cplugs.sdk.public_listener import MAX_CONCURRENCY
from tests.python.cplugs.publicboard.harness import LOOPBACK, ServerThread, edge_for, exchange, request


SETTLE = 0.5


class Gate:

    def __init__(self) -> None:
        self.trusted = False

    def __call__(self, host: str) -> bool:
        return self.trusted


def strangers_then_proxy(gate: Gate, port: int, count: int):
    held: List[socket.socket] = [socket.create_connection((LOOPBACK, port), timeout=3) for _ in range(count)]
    time.sleep(SETTLE)
    gate.trusted = True
    return exchange(port, request("GET", "/api/board")), held


def test_63_idle_strangers_do_not_stop_the_trusted_proxy_being_served() -> None:
    gate = Gate()
    with ServerThread(edge_for(), peer_allowed=gate) as server:
        reply, held = strangers_then_proxy(gate, server.port, MAX_CONCURRENCY - 1)
        try:
            assert reply.status == 200, reply.status
            assert all(_closed_by_server(conn) for conn in held), "a stranger was kept open"
        finally:
            for conn in held:
                conn.close()


def test_a_dropped_stranger_gets_no_bytes_at_all() -> None:
    gate = Gate()
    with ServerThread(edge_for(), peer_allowed=gate) as server:
        reply = exchange(server.port, request("GET", "/api/board"))
    assert reply.status is None and reply.raw == b""


def test_without_the_door_filter_the_same_strangers_do_fill_the_slots() -> None:
    gate = Gate()
    with mock.patch.object(public_listener, "peer_refused", lambda spec, transport: False):
        with ServerThread(edge_for(), peer_allowed=gate) as server:
            reply, held = strangers_then_proxy(gate, server.port, MAX_CONCURRENCY - 1)
            for conn in held:
                conn.close()
    assert reply.status == 503, reply.status


def test_a_peer_with_no_ip_address_is_dropped() -> None:
    class UnixTransport:
        def get_extra_info(self, name: str) -> object:
            return None

    spec = public_listener.ListenerSpec(host=LOOPBACK, port=0, peer_allowed=lambda host: True)
    assert public_listener.peer_refused(spec, UnixTransport()) is True
    assert public_listener.peer_refused(public_listener.ListenerSpec(host=LOOPBACK, port=0), UnixTransport()) is False


def _closed_by_server(conn: socket.socket) -> bool:
    conn.settimeout(2)
    try:
        return conn.recv(10) == b""
    except ConnectionResetError:
        return True
