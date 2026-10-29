
from __future__ import annotations

import ast
import asyncio
from pathlib import Path

import pytest
import uvicorn
import websockets

from src.core.early_listen.ws_deflate import ws_deflate_for

MAIN = Path(__file__).resolve().parents[3] / "src" / "main.py"


@pytest.mark.parametrize(
    "host,expected",
    [("127.0.0.1", False), ("::1", False), ("localhost", False), ("LocalHost", False),
     ("0.0.0.0", True), ("192.0.2.5", True), ("::", True), ("", True)],
)
def test_truth_table(host, expected):
    assert ws_deflate_for(host) is expected


def test_both_launch_sites_pass_the_helper():
    tree = ast.parse(MAIN.read_text())
    sites = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call) and ast.unparse(n.func) in ("uvicorn.run", "uvicorn.Config")
    ]
    assert len(sites) == 2
    for call in sites:
        kw = {k.arg: ast.unparse(k.value) for k in call.keywords}
        assert kw.get("ws_per_message_deflate") == "ws_deflate_for(exposure.bind_host)"


async def _echo_app(scope, receive, send):
    if scope["type"] == "lifespan":
        while True:
            msg = await receive()
            if msg["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            else:
                await send({"type": "lifespan.shutdown.complete"})
                return
    if scope["type"] == "websocket":
        await receive()
        await send({"type": "websocket.accept"})
        await send({"type": "websocket.close"})


async def _negotiated(deflate: bool) -> list:
    server = uvicorn.Server(uvicorn.Config(
        _echo_app, host="127.0.0.1", port=0, log_level="warning",
        ws_per_message_deflate=deflate,
    ))
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        async with websockets.connect(f"ws://127.0.0.1:{port}/") as ws:
            return [e.name for e in ws.protocol.extensions]
    finally:
        server.should_exit = True
        await task


def test_live_handshake_follows_the_helper():
    assert asyncio.run(_negotiated(ws_deflate_for("127.0.0.1"))) == []
    assert asyncio.run(_negotiated(True)) == ["permessage-deflate"]
