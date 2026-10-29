
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

import httpx
import pytest
from websockets.asyncio.server import serve

from src.tui.api_client import ApiClient
from src.tui.events_client import EventsClient, backoff_delay
from src.tui.token_store import TokenPair, TokenStore


def row(sid: str, status: str) -> dict[str, Any]:
    return {"session": {"id": sid, "name": sid}, "activity_status": status, "unread": None}


def snapshot(seq: int, rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {"stream": "s1", "seq": seq,
            "collections": {"list": {"rows": rows, "ok": True, "status": 200, "detail": None, "meta": {}}}}


class FakeHttp:

    def __init__(self) -> None:
        self.snap = snapshot(10, [row("a", "idle")])
        self.snap_calls = 0
        self.refreshes = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/sessions/listing":
            self.snap_calls += 1
            return httpx.Response(200, json=self.snap)
        if request.url.path == "/api/v1/auth/refresh":
            self.refreshes += 1
            return httpx.Response(200, json={"access_token": f"acc-{self.refreshes + 1}",
                                             "refresh_token": f"ref-{self.refreshes + 1}", "expires_in": 900})
        return httpx.Response(404)


async def until(cond: Callable[[], bool], timeout: float = 5.0) -> None:
    end = time.monotonic() + timeout
    while not cond():
        assert time.monotonic() < end, "condition never held"
        await asyncio.sleep(0.01)


class FakeEvents:

    def __init__(self, tokens: set[str], script: Callable[[Any], Awaitable[None]]) -> None:
        self.tokens, self.script, self.server, self.port, self.seen = tokens, script, None, 0, []

    def _gate(self, connection: Any, request: Any) -> Any:
        offered = [p.strip() for p in request.headers.get("Sec-WebSocket-Protocol", "").split(",")]
        self.seen.append(offered)
        if offered[:1] != ["cloude.jwt.v1"] or offered[1:] == [] or offered[1] not in self.tokens:
            return connection.respond(403, "refused\n")
        return None

    async def _handle(self, ws: Any) -> None:
        await self.script(ws)
        await ws.wait_closed()

    async def start(self) -> None:
        self.server = await serve(self._handle, "127.0.0.1", self.port, subprotocols=["cloude.jwt.v1"],
                                  process_request=self._gate)
        self.port = self.server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        self.server.close()
        await self.server.wait_closed()


def make(tmp_path: Path, http: FakeHttp, port: int, access: str = "acc-1", **kw: Any):
    store = TokenStore(tmp_path)
    store.save(TokenPair(access, "ref-1", time.time() + 900))
    api = ApiClient(store, f"http://127.0.0.1:{port}", transport=httpx.MockTransport(http.handler))
    banners: list[bool] = []
    lost: list[bool] = []
    ev = EventsClient(api, f"http://127.0.0.1:{port}", banners.append, lambda: lost.append(True),
                      poll_seconds=0.02, sleep=lambda s: asyncio.sleep(min(s, 0.05)), **kw)
    return ev, banners, lost


def test_delta_gap_down_polling_and_recovery(tmp_path: Path) -> None:
    async def run() -> None:
        http = FakeHttp()
        go_gap = asyncio.Event()
        topics_seen: list[list[str]] = []

        async def script(ws: Any) -> None:
            await ws.send(json.dumps({"type": "events.hello", "resource_topics": ["approvals"]}))
            await ws.send(json.dumps({"type": "listing.delta", "stream": "s1", "seq": 11, "changes": {"list": {
                "upsert": [{"key": "a", "fields": {"activity_status": "working"},
                            "nested": {"session": {"name": "renamed"}}}]}}}))
            await ws.send(json.dumps({"type": "resources.changed", "topics": ["approvals"], "seq": 1}))
            await go_gap.wait()
            http.snap = snapshot(15, [row("a", "idle"), row("b", "dead")])
            await ws.send(json.dumps({"type": "listing.delta", "stream": "s1", "seq": 15, "changes": {}}))

        fake = FakeEvents({"acc-1"}, script)
        await fake.start()
        ev, banners, _ = make(tmp_path, http, fake.port)
        ev.on_topics(topics_seen.append)
        ev.start()
        try:
            await until(lambda: ev.listing.is_live() and ev.listing.rows("list")[0]["activity_status"] == "working")
            got = ev.listing.rows("list")[0]
            assert got["session"] == {"id": "a", "name": "renamed"}, "nested part must merge, not replace"
            assert got["unread"] is None, "a null stays null"
            assert ev.topic_pushed("approvals") and not ev.topic_pushed("catalog")
            assert ["approvals"] in topics_seen
            assert banners == []
            assert fake.seen[0][0] == "cloude.jwt.v1" and fake.seen[0][1] == "acc-1"

            calls = http.snap_calls
            go_gap.set()
            await until(lambda: http.snap_calls > calls and [r["session"]["id"] for r in ev.listing.rows("list")] == ["a", "b"])
            assert ev.listing.is_live()

            await fake.stop()
            await until(lambda: banners == [True] and not ev.listing.is_live())
            http.snap = snapshot(20, [row("c", "idle")])
            calls = http.snap_calls
            await until(lambda: http.snap_calls >= calls + 2)
            await until(lambda: [r["session"]["id"] for r in ev.listing.rows("list")] == ["c"])
            assert not ev.listing.is_live() and not ev.topic_pushed("approvals")

            go_gap.clear()
            await fake.start()
            await until(lambda: banners == [True, False] and ev.listing.is_live())
            await asyncio.sleep(0.1)
            settled = http.snap_calls
            await asyncio.sleep(0.2)
            assert http.snap_calls == settled, "polling must stop once the socket is back"
        finally:
            go_gap.set()
            await ev.stop()
            await fake.stop()

    asyncio.run(run())


def test_refused_handshake_refreshes_once_then_ends_login(tmp_path: Path) -> None:
    async def run() -> None:
        async def hello(ws: Any) -> None:
            await ws.send(json.dumps({"type": "events.hello", "resource_topics": []}))

        http = FakeHttp()
        fake = FakeEvents({"acc-2"}, hello)
        await fake.start()
        ev, _, lost = make(tmp_path, http, fake.port, access="acc-1")
        ev.start()
        try:
            await until(lambda: ev.connected)
            assert http.refreshes == 1 and not lost
        finally:
            await ev.stop()
            await fake.stop()

        http2 = FakeHttp()
        fake2 = FakeEvents(set(), hello)
        await fake2.start()
        ev2, _, lost2 = make(tmp_path / "b", http2, fake2.port) if (tmp_path / "b").mkdir() is None else (None, None, None)
        ev2.start()
        try:
            await until(lambda: lost2 == [True])
            assert http2.refreshes == 1 and TokenStore(tmp_path / "b").load() is None
        finally:
            await ev2.stop()
            await fake2.stop()

    asyncio.run(run())


def test_backoff_is_jittered_and_capped() -> None:
    assert backoff_delay(0, lambda: 0.0) == 0.5 and backoff_delay(0, lambda: 1.0) == 1.0
    assert backoff_delay(3, lambda: 1.0) == 8.0
    assert backoff_delay(50, lambda: 1.0) == 30.0 and backoff_delay(50, lambda: 0.0) == 15.0
