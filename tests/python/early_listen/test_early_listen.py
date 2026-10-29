
from __future__ import annotations

import ast
import asyncio
import socket
import threading
from pathlib import Path
from typing import Any, Callable, List, Optional

import pytest
import uvicorn

from src.core.early_listen import listener as early
from src.core.early_listen import BindFailed, bind_listeners, serve_early

MAIN_PY = Path(__file__).resolve().parents[3] / "src" / "main.py"
REQUEST = b"GET / HTTP/1.1\r\nHost: test\r\nConnection: close\r\n\r\n"


class _SlowBootApp:

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] == "lifespan":
            while True:
                message = await receive()
                if message["type"] == "lifespan.startup":
                    self.entered.set()
                    await asyncio.to_thread(self.release.wait, 10)
                    await send({"type": "lifespan.startup.complete"})
                elif message["type"] == "lifespan.shutdown":
                    await send({"type": "lifespan.shutdown.complete"})
                    return
        if scope["type"] == "http":
            await receive()
            await send({"type": "http.response.start", "status": 200,
                        "headers": [(b"content-type", b"text/plain")]})
            await send({"type": "http.response.body", "body": b"ready"})


def _config(app: Any, port: int) -> uvicorn.Config:
    return uvicorn.Config(app, host="127.0.0.1", port=port, lifespan="on",
                          log_config=None, log_level="warning")


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _run_in_thread(target: Callable[[], None]) -> threading.Thread:
    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    return thread


def test_a_connect_during_a_slow_boot_is_held_then_served() -> None:
    app = _SlowBootApp()
    sockets = bind_listeners("127.0.0.1", 0, backlog=16)
    port = sockets[0].getsockname()[1]
    server = uvicorn.Server(_config(app, port))
    thread = _run_in_thread(lambda: server.run(sockets=sockets))
    try:
        assert app.entered.wait(5), "lifespan startup never began"
        client = socket.create_connection(("127.0.0.1", port), timeout=5)
        client.sendall(REQUEST)
        client.settimeout(0.5)
        with pytest.raises(socket.timeout):
            client.recv(1024)
        app.release.set()
        client.settimeout(5)
        reply = b""
        while chunk := client.recv(4096):
            reply += chunk
        client.close()
        assert reply.startswith(b"HTTP/1.1 200"), reply[:80]
        assert reply.split(b"\r\n\r\n", 1)[1].find(b"ready") >= 0
    finally:
        app.release.set()
        server.should_exit = True
        thread.join(10)
    assert not thread.is_alive()


def test_control_uvicorn_default_path_refuses_the_same_connect() -> None:
    app = _SlowBootApp()
    port = _free_port()
    server = uvicorn.Server(_config(app, port))
    thread = _run_in_thread(server.run)
    try:
        assert app.entered.wait(5), "lifespan startup never began"
        with pytest.raises(ConnectionRefusedError):
            socket.create_connection(("127.0.0.1", port), timeout=2)
    finally:
        app.release.set()
        server.should_exit = True
        thread.join(10)
    assert not thread.is_alive()


def test_a_held_port_exits_with_startup_failure_before_the_lifespan_runs(monkeypatch) -> None:
    monkeypatch.setattr(early, "BIND_RETRY_S", 0.2)
    holder = socket.socket()
    holder.bind(("127.0.0.1", 0))
    holder.listen(1)
    port = holder.getsockname()[1]
    app = _SlowBootApp()
    exit_codes: List[Optional[int]] = []

    def run() -> None:
        try:
            serve_early(_config(app, port))
        except SystemExit as exc:
            exit_codes.append(exc.code)

    try:
        thread = _run_in_thread(run)
        thread.join(10)
    finally:
        app.release.set()
        holder.close()
    assert exit_codes == [early.STARTUP_FAILURE_EXIT]
    assert not app.entered.is_set(), "the lifespan ran although the port was never bound"


def test_a_port_released_within_the_retry_window_is_bound() -> None:
    holder = socket.socket()
    holder.bind(("127.0.0.1", 0))
    holder.listen(1)
    port = holder.getsockname()[1]
    threading.Timer(0.3, holder.close).start()
    sockets = bind_listeners("127.0.0.1", port, backlog=4, retry_s=3.0, poll_s=0.05)
    try:
        assert [s.getsockname()[1] for s in sockets] == [port]
    finally:
        for sock in sockets:
            sock.close()


def test_a_port_held_past_the_window_raises_bind_failed() -> None:
    with socket.socket() as holder:
        holder.bind(("127.0.0.1", 0))
        holder.listen(1)
        port = holder.getsockname()[1]
        with pytest.raises(BindFailed) as caught:
            bind_listeners("127.0.0.1", port, backlog=4, retry_s=0.2, poll_s=0.05)
    assert caught.value.port == port


def test_the_sockets_listen_are_not_inherited_and_do_not_share_the_port() -> None:
    sockets = bind_listeners("127.0.0.1", 0, backlog=4)
    try:
        for sock in sockets:
            with socket.create_connection(sock.getsockname()[:2], timeout=2):
                pass
            assert sock.get_inheritable() is False
            assert sock.getsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR) != 0
            if hasattr(socket, "SO_REUSEPORT"):
                assert sock.getsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT) == 0
    finally:
        for sock in sockets:
            sock.close()


def test_main_serves_through_the_early_listener_outside_reload() -> None:
    tree = ast.parse(MAIN_PY.read_text(encoding="utf-8"))
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Name) and node.func.id == "serve_early"]
    assert len(calls) == 1, "src/main.py must start the server through serve_early"
