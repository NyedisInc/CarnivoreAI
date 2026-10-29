
from __future__ import annotations

import socket
import time

import pytest

from src.cplugs.sdk.public_listener import ListenerSpec, PublicListener, PublicListenerError, build_config
from tests.python.cplugs.publicboard.harness import HOST, LOOPBACK, ServerThread, edge_for, exchange, request


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "", "localhost", "example.com", "224.0.0.1"])
def test_the_door_refuses_to_bind_anything_but_one_specific_address(host: str) -> None:
    with pytest.raises(PublicListenerError):
        ListenerSpec(host=host, port=8190)


def test_the_door_refuses_an_out_of_range_port() -> None:
    with pytest.raises(PublicListenerError):
        ListenerSpec(host=LOOPBACK, port=70000)


def test_the_uvicorn_config_is_all_refusals_and_caps() -> None:
    config = build_config(edge_for(), ListenerSpec(host=LOOPBACK, port=0))
    assert config.ws == "none" and config.lifespan == "off" and config.proxy_headers is False
    assert config.server_header is False and config.access_log is False and config.h11_max_incomplete_event_size == 16 * 1024
    assert config.limit_concurrency == 64 and config.http2 is False


def test_responses_carry_no_server_header_and_no_cookie() -> None:
    with ServerThread(edge_for()) as server:
        reply = exchange(server.port, request("GET", "/nope"))
    assert reply.status == 404 and "server" not in reply.headers and "set-cookie" not in reply.headers


def test_a_port_in_use_raises_the_door_error_and_leaves_the_loop_alive() -> None:
    import asyncio

    async def attempt() -> str:
        with socket.socket() as taken:
            taken.bind((LOOPBACK, 0))
            taken.listen(1)
            with pytest.raises(PublicListenerError):
                await PublicListener(edge_for(), ListenerSpec(host=LOOPBACK, port=taken.getsockname()[1])).start()
        return "alive"

    assert asyncio.run(attempt()) == "alive"


def test_a_stopped_listener_refuses_connections() -> None:
    with ServerThread(edge_for()) as server:
        port = server.port
        assert exchange(port, request("GET", "/nope")).status == 404
    with pytest.raises(OSError):
        socket.create_connection((LOOPBACK, port), timeout=1).close()


def test_a_client_that_trickles_its_request_is_cut_at_the_deadline() -> None:
    with ServerThread(edge_for(), deadline=0.5) as server:
        with socket.create_connection((LOOPBACK, server.port), timeout=5) as conn:
            conn.sendall(f"GET /api/board HTTP/1.1\r\nHost: {HOST}\r\nX-Slow: ".encode())
            started = time.monotonic()
            conn.settimeout(5)
            try:
                data = conn.recv(100)
            except ConnectionResetError:
                data = b""
            elapsed = time.monotonic() - started
    assert data == b"" and elapsed < 3, (data, elapsed)


def test_the_deadline_does_not_cut_a_normal_request() -> None:
    with ServerThread(edge_for(), deadline=2.0) as server:
        assert exchange(server.port, request("GET", "/api/board")).status == 200
