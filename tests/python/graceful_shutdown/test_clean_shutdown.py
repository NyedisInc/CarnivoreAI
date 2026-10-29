
from __future__ import annotations

import asyncio
import http.client
import logging
import socket
import threading
import time
from typing import Iterator, List, Type

import pytest
import structlog
import uvicorn
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from starlette.middleware.base import BaseHTTPMiddleware

from src.api.request_log import RequestLogMiddleware
from src.core import graceful_shutdown
from src.core.graceful_shutdown import GracefulServer
from src.core.mcp import channel

SERVER_CLS: Type[uvicorn.Server] = GracefulServer
GRACEFUL_S = 1
FIRST_PORT = 5101


def _free_port() -> int:
    for port in range(FIRST_PORT, FIRST_PORT + 200):
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError("no free test port")


def _app() -> FastAPI:
    app = FastAPI()

    @app.get("/mcp")
    async def stream() -> StreamingResponse:
        return StreamingResponse(channel.stream_events("tmux_t", "ses_t", keepalive_s=0.2),
                                 media_type="text/event-stream")

    app.add_middleware(BaseHTTPMiddleware, dispatch=lambda request, call_next: call_next(request))
    app.add_middleware(RequestLogMiddleware)
    return app


class _Records(logging.Handler):

    def __init__(self) -> None:
        super().__init__()
        self.messages: List[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(self.format(record))


@pytest.fixture(autouse=True)
def _flag_reset() -> Iterator[None]:
    graceful_shutdown.reset()
    yield
    graceful_shutdown.reset()


def test_stop_ends_open_channel_stream_with_no_traceback() -> None:
    port = _free_port()
    server = SERVER_CLS(uvicorn.Config(_app(), host="127.0.0.1", port=port, log_level="warning", log_config=None,
                                       timeout_graceful_shutdown=GRACEFUL_S))
    records = _Records()
    logger = logging.getLogger("uvicorn.error")
    logger.addHandler(records)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.02)
        assert server.started
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        conn.request("GET", "/mcp")
        response = conn.getresponse()
        assert response.status == 200
        assert b"retry" in response.readline()
        time.sleep(0.3)
        server.should_exit = True
        began = time.monotonic()
        response.read()
        assert time.monotonic() - began < GRACEFUL_S, "the stream outlived the graceful timeout"
        thread.join(timeout=10)
        assert not thread.is_alive()
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        logger.removeHandler(records)
    text = "\n".join(records.messages)
    assert "Exception in ASGI application" not in text
    assert "CancelledError" not in text
    assert "Cancel" not in text
    assert channel.REGISTRY.count() == 0


def _run_cancelled(shutting_down: bool) -> List[dict]:
    async def cancelled_app(scope, receive, send) -> None:
        raise asyncio.CancelledError("Task cancelled, timeout graceful shutdown exceeded")

    if shutting_down:
        graceful_shutdown.begin()
    scope = {"type": "http", "method": "GET", "path": "/mcp", "client": ("127.0.0.1", 1)}
    with structlog.testing.capture_logs() as events:
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(RequestLogMiddleware(cancelled_app)(scope, None, None))
    return events


def test_cancel_at_shutdown_logs_one_line_and_reraises() -> None:
    events = [e for e in _run_cancelled(True) if e["event"] == "request_cancelled_at_shutdown"]
    assert len(events) == 1
    assert events[0]["path"] == "/mcp"
    assert events[0]["log_level"] == "info"


def test_cancel_during_normal_running_is_not_named() -> None:
    assert [e for e in _run_cancelled(False) if e["event"] == "request_cancelled_at_shutdown"] == []


def test_a_real_error_still_logs_as_before() -> None:
    async def failing_app(scope, receive, send) -> None:
        raise ValueError("boom")

    scope = {"type": "http", "method": "GET", "path": "/x", "client": None}
    with structlog.testing.capture_logs() as events:
        with pytest.raises(ValueError):
            asyncio.run(RequestLogMiddleware(failing_app)(scope, None, None))
    assert [e["status"] for e in events if e["event"] == "http_request"] == [500]


def test_end_all_makes_room_in_a_full_queue() -> None:
    registry = channel.ChannelRegistry()
    stream = registry.open("full", "ses")
    for _ in range(channel.MAX_QUEUED):
        stream.queue.put_nowait({"n": 1})
    assert registry.end_all() == 1
    assert stream.queue.qsize() == channel.MAX_QUEUED
    registry.close(stream)
