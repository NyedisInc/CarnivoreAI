from __future__ import annotations

import asyncio
import os
import tempfile

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_ttl_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_ttl_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

from types import SimpleNamespace  # noqa: E402

from src.api import session_crud_routes  # noqa: E402
from src.core import session_change_notice  # noqa: E402
from src.core.federation import peer_serve  # noqa: E402
from src.core.ttl_flight import TtlFlight  # noqa: E402
from src.models import Session, SessionInfo, SessionStatus  # noqa: E402


def test_two_calls_in_the_ttl_cost_one_computation_and_a_notice_drops_it():
    async def go():
        cache, runs = TtlFlight("t", 60.0), []

        async def work():
            runs.append(1)
            await asyncio.sleep(0)
            return [len(runs)]

        first, second = await asyncio.gather(cache.get(work), cache.get(work))
        third = await cache.get(work)
        assert (first, second, third, len(runs)) == ([1], [1], [1], 1)
        session_change_notice.publish(SimpleNamespace(), {"type": "x"})
        assert await cache.get(work) == [2] and len(runs) == 2

    asyncio.run(go())


def test_two_scopes_never_share_a_result(monkeypatch):
    info = SessionInfo(session=Session(id="ses_1", working_dir="/w", status=SessionStatus.RUNNING, pty_pid=4242), tmux_session="t1")
    passes = []

    async def assemble(_state):
        passes.append(1)
        return [info]

    monkeypatch.setattr(session_crud_routes, "_assemble_owner_listing", assemble)
    session_crud_routes.OWNER_LISTING_CACHE.invalidate()

    async def go():
        owner_a = await session_crud_routes.build_owner_listing(SimpleNamespace())
        owner_b = await session_crud_routes.build_owner_listing(SimpleNamespace())
        assert len(passes) == 1 and owner_a is not owner_b
        peer_view = [peer_serve._slim(i, "iid", "uuid") for i in owner_a]
        assert peer_view[0].session.pty_pid is None
        again = await session_crud_routes.build_owner_listing(SimpleNamespace())
        assert again[0].session.pty_pid == 4242

    asyncio.run(go())


def test_merged_call_answers_both_halves_and_the_peer_side_falls_back_on_an_older_peer(monkeypatch):
    from src.core.federation import peer_listing

    class Reply:
        def __init__(self, status, body=None):
            self.status_code, self._body = status, body

        def json(self):
            return self._body

    class Client:
        def __init__(self, reply):
            self.reply, self.paths = reply, []

        async def request(self, method, path, **_kw):
            self.paths.append(path)
            return self.reply

    async def go():
        peer_listing._NO_MERGED.clear()
        good = Client(Reply(200, {"list": [{"a": 1}], "asleep": [{"b": 2}]}))
        lst, asleep = await peer_listing._merged_reply(good, "k1")
        assert (lst.json(), asleep.json(), good.paths) == ([{"a": 1}], [{"b": 2}], ["/sessions/list-and-asleep"])
        old = Client(Reply(404))
        assert await peer_listing._merged_reply(old, "k2") is None
        assert await peer_listing._merged_reply(old, "k2") is None and old.paths == ["/sessions/list-and-asleep"]

    asyncio.run(go())


def test_the_merged_route_returns_list_and_asleep(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.api import session_crud_routes, session_sleep_routes
    from src.api.peer_auth import require_peer_sessions

    async def rows(_state):
        return [SessionInfo(session=Session(id="ses_1", working_dir="/w", status=SessionStatus.RUNNING), tmux_session="t1")]

    async def peers(infos, **_kw):
        return infos

    async def asleep(_state, *_a):
        return []

    monkeypatch.setattr(session_crud_routes, "_assemble_owner_listing", rows)
    monkeypatch.setattr(session_crud_routes.peer_listing, "for_caller", peers)
    monkeypatch.setattr(session_sleep_routes, "_assemble_asleep_rows", asleep)
    app = FastAPI()
    app.include_router(session_crud_routes.router, prefix="/api/v1")
    app.include_router(session_sleep_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_peer_sessions] = lambda: None
    app.state.session_manager = SimpleNamespace()
    body = TestClient(app).get("/api/v1/sessions/list-and-asleep").json()
    assert [r["session"]["id"] for r in body["list"]] == ["ses_1"] and body["asleep"] == []
