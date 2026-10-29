
from __future__ import annotations

import asyncio
import json
import os
import tempfile
from types import SimpleNamespace
from typing import List

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_szm_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_szm_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

from src.api import size_master  # noqa: E402
from src.api.resize_negotiation import apply_negotiated_resize, get_negotiator  # noqa: E402
from src.core.terminal_size import TerminalSizeNegotiator  # noqa: E402

BIG = "tab-big-000001"
SMALL = "tab-small-00002"


def _pair(master=None):
    neg = TerminalSizeNegotiator()
    neg.bind_client_id("s", "big", BIG)
    neg.bind_client_id("s", "small", SMALL)
    neg.set_client_size("s", "big", 200, 60)
    neg.set_client_size("s", "small", 100, 30)
    if master:
        neg.set_master("s", master)
    return neg




def test_no_master_is_smallest_wins_unchanged():
    neg = _pair()
    assert neg.master("s") is None
    assert neg.effective_size("s") == (100, 30)


def test_claiming_moves_the_pane_to_the_master():
    neg = _pair()
    assert neg.set_master("s", BIG) == (200, 60)
    assert neg.effective_size("s") == (200, 60)


def test_a_watcher_resizing_does_not_move_the_pane():
    neg = _pair(master=BIG)
    assert neg.set_client_size("s", "small", 80, 20) is None
    assert neg.effective_size("s") == (200, 60)


def test_the_master_resizing_moves_the_pane():
    neg = _pair(master=BIG)
    assert neg.set_client_size("s", "big", 180, 50) == (180, 50)


def test_releasing_restores_smallest_wins():
    neg = _pair(master=BIG)
    assert neg.set_master("s", None) == (100, 30)
    assert neg.master("s") is None


def test_a_hidden_master_keeps_the_last_size():
    neg = _pair(master=BIG)
    assert neg.set_client_size("s", "big", 200, 60, voting=False) is None
    assert neg.effective_size("s") == (200, 60)
    assert neg.set_client_size("s", "small", 90, 25) is None
    assert neg.effective_size("s") == (200, 60)


def test_a_departed_master_is_kept_and_keeps_the_size():
    neg = _pair(master=BIG)
    assert neg.master_attached("s")
    assert neg.remove_client("s", "big") is None
    assert neg.master("s") == BIG, "only set_master clears a master"
    assert not neg.master_attached("s")
    assert neg.effective_size("s") == (200, 60)


def test_the_master_coming_back_is_attached_again():
    neg = _pair(master=BIG)
    neg.remove_client("s", "big")
    neg.bind_client_id("s", "big2", BIG)
    assert neg.master_attached("s")
    assert neg.set_client_size("s", "big2", 190, 55) == (190, 55)


def test_a_client_with_no_id_votes_only_while_there_is_no_master():
    neg = TerminalSizeNegotiator()
    neg.bind_client_id("s", "old", None)
    neg.set_client_size("s", "old", 90, 20)
    neg.bind_client_id("s", "big", BIG)
    neg.set_client_size("s", "big", 200, 60)
    assert neg.effective_size("s") == (90, 20)
    neg.set_master("s", BIG)
    assert neg.effective_size("s") == (200, 60)


def test_a_socket_that_never_sized_is_forgotten_on_removal():
    neg = TerminalSizeNegotiator()
    neg.bind_client_id("s", "ws", BIG)
    neg.set_master("s", BIG)
    assert neg.master_attached("s")
    assert neg.remove_client("s", "ws") is None
    assert not neg.master_attached("s")




class Recorder:

    def __init__(self) -> None:
        self.resizes: List[tuple] = []
        self.frames: List[dict] = []

    def resize_terminal(self, cols: int, rows: int, session_id: str) -> None:
        self.resizes.append((cols, rows))

    async def broadcast_to_session(self, session_id: str, message: str) -> int:
        self.frames.append(json.loads(message))
        return 1


def _manager() -> SimpleNamespace:
    rec = Recorder()
    return SimpleNamespace(resize_terminal=rec.resize_terminal, rec=rec)


async def _attach_pair(sm) -> None:
    neg = get_negotiator(sm)
    neg.bind_client_id("s", "big", BIG)
    neg.bind_client_id("s", "small", SMALL)
    await apply_negotiated_resize(sm, "s", "big", 200, 60, sm.rec)
    await apply_negotiated_resize(sm, "s", "small", 100, 30, sm.rec)


@pytest.mark.asyncio
async def test_a_claim_resizes_the_pane_and_tells_every_window():
    sm = _manager()
    await _attach_pair(sm)
    sm.rec.resizes.clear()
    sm.rec.frames.clear()
    result = await size_master.set_master(sm, "s", BIG, sm.rec, reason="test")
    assert result == {"session_id": "s", "master": BIG, "master_attached": True}
    assert sm.rec.resizes == [(200, 60)]
    types = [f["type"] for f in sm.rec.frames]
    assert types == ["terminal_size", "size_master"], types
    assert sm.rec.frames[0]["cols"] == 200
    assert sm.rec.frames[1]["master"] == BIG


@pytest.mark.asyncio
async def test_a_watcher_resize_under_a_master_never_resizes_the_pane():
    sm = _manager()
    await _attach_pair(sm)
    await size_master.set_master(sm, "s", BIG, sm.rec, reason="test")
    sm.rec.resizes.clear()
    await apply_negotiated_resize(sm, "s", "small", 70, 20, sm.rec)
    assert sm.rec.resizes == []
    assert sm.rec.frames[-1]["type"] == "terminal_size"
    assert (sm.rec.frames[-1]["cols"], sm.rec.frames[-1]["rows"]) == (200, 60)


@pytest.mark.asyncio
async def test_a_lone_watcher_under_a_master_is_told_the_grid():
    sm = _manager()
    neg = get_negotiator(sm)
    neg.bind_client_id("s", "small", SMALL)
    await apply_negotiated_resize(sm, "s", "small", 100, 30, sm.rec)
    assert sm.rec.frames == [], "control: a lone client is not told its own size"
    await size_master.set_master(sm, "s", BIG, sm.rec, reason="test")
    sm.rec.frames.clear()
    await apply_negotiated_resize(sm, "s", "small", 80, 20, sm.rec)
    assert sm.rec.frames and sm.rec.frames[-1]["type"] == "terminal_size"
    assert (sm.rec.frames[-1]["cols"], sm.rec.frames[-1]["rows"]) == (100, 30)


@pytest.mark.asyncio
async def test_a_departed_master_clears_after_the_grace_window(monkeypatch):
    monkeypatch.setattr(size_master, "GRACE_SECONDS", 0.05)
    sm = _manager()
    await _attach_pair(sm)
    await size_master.set_master(sm, "s", BIG, sm.rec, reason="test")
    sm.rec.frames.clear()
    sm.rec.resizes.clear()
    await size_master.release_client(sm, "s", "big", sm.rec)
    assert get_negotiator(sm).master("s") == BIG, "cleared before the grace window"
    assert sm.rec.resizes == [], "a departed master's size must be kept"
    await asyncio.sleep(0.2)
    assert get_negotiator(sm).master("s") is None
    assert sm.rec.resizes == [(100, 30)], "the pane returns to the survivor"
    assert sm.rec.frames[-1] == {
        "type": "size_master", "session_id": "s", "master": None, "master_attached": False}


@pytest.mark.asyncio
async def test_the_master_reconnecting_inside_the_grace_window_keeps_it(monkeypatch):
    monkeypatch.setattr(size_master, "GRACE_SECONDS", 0.05)
    sm = _manager()
    await _attach_pair(sm)
    await size_master.set_master(sm, "s", BIG, sm.rec, reason="test")
    await size_master.release_client(sm, "s", "big", sm.rec)
    get_negotiator(sm).bind_client_id("s", "big-again", BIG)
    await apply_negotiated_resize(sm, "s", "big-again", 200, 60, sm.rec)
    await asyncio.sleep(0.2)
    assert get_negotiator(sm).master("s") == BIG


@pytest.mark.asyncio
async def test_a_watcher_leaving_starts_no_timer(monkeypatch):
    monkeypatch.setattr(size_master, "GRACE_SECONDS", 0.05)
    sm = _manager()
    await _attach_pair(sm)
    await size_master.set_master(sm, "s", BIG, sm.rec, reason="test")
    await size_master.release_client(sm, "s", "small", sm.rec)
    await asyncio.sleep(0.2)
    assert get_negotiator(sm).master("s") == BIG


class _Socket:

    def __init__(self, client_id) -> None:
        self.query_params = {} if client_id is None else {"client_id": client_id}
        self.sent: List[dict] = []

    async def send_text(self, text: str) -> None:
        self.sent.append(json.loads(text))


@pytest.mark.asyncio
async def test_attach_binds_the_id_and_tells_the_socket_who_holds_the_size():
    sm = _manager()
    get_negotiator(sm).set_master("s", BIG)
    ws = _Socket(BIG)
    await size_master.attach(ws, sm, "s")
    assert ws.sent == [{"type": "size_master", "session_id": "s", "master": BIG,
                        "master_attached": True}]


@pytest.mark.asyncio
async def test_a_malformed_client_id_is_ignored_not_bound():
    sm = _manager()
    get_negotiator(sm).set_master("s", BIG)
    await size_master.attach(_Socket("<script>"), sm, "s")
    assert not get_negotiator(sm).master_attached("s")
    assert size_master.client_id_from_query({"client_id": "short"}) is None
    assert size_master.client_id_from_query({"client_id": BIG}) == BIG




def _client(monkeypatch, *, authenticated: bool = True):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.api import size_master_routes
    from src.api.auth import require_auth
    from src.api.routes import router

    sm = _manager()
    monkeypatch.setattr(size_master_routes, "connection_manager", sm.rec)
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    if authenticated:
        app.dependency_overrides[require_auth] = lambda: None
    app.state.session_manager = sm
    app.state.services = SimpleNamespace(registry=SimpleNamespace(sessions={"s": object()}))
    return TestClient(app), sm


def test_the_routes_claim_read_and_release(monkeypatch):
    client, sm = _client(monkeypatch)
    url = "/api/v1/sessions/s/size-master"
    assert client.get(url).json() == {"session_id": "s", "master": None, "master_attached": False}
    claimed = client.put(url, json={"client_id": BIG})
    assert claimed.status_code == 200 and claimed.json()["master"] == BIG
    assert client.get(url).json()["master"] == BIG
    assert sm.rec.frames[-1]["type"] == "size_master"
    stale = client.delete(url, params={"client_id": SMALL})
    assert stale.status_code == 409, "a stale crown released somebody else's claim"
    assert client.delete(url, params={"client_id": BIG}).json()["master"] is None
    again = client.delete(url, params={"client_id": BIG})
    assert again.status_code == 200 and again.json()["master"] is None


def test_the_routes_refuse_an_unknown_session_and_a_bad_id(monkeypatch):
    client, _ = _client(monkeypatch)
    assert client.get("/api/v1/sessions/nope/size-master").status_code == 404
    assert client.put("/api/v1/sessions/s/size-master", json={"client_id": "x"}).status_code == 422


def test_the_routes_require_auth(monkeypatch):
    client, _ = _client(monkeypatch, authenticated=False)
    for method in ("get", "delete"):
        assert getattr(client, method)("/api/v1/sessions/s/size-master").status_code in (401, 403)
    assert client.put("/api/v1/sessions/s/size-master",
                      json={"client_id": BIG}).status_code in (401, 403)
