
from __future__ import annotations

from types import SimpleNamespace

import pytest

from tests.python.federation.test_peer_forward import PEER_IID, world as _world  # noqa: F401

# ruff: noqa: E402
from src.api import warroom_screen_routes
import asyncio
import json

from src.core.federation import peer_links, peer_listing
from src.core.warroom import peer_screens
from src.core.federation.pairing import SCREENS_MINOR
from src.core.federation.peer_client import PeerUnreachable
from src.core.warroom.screens import PaneScreen

URL = "/api/v1/warroom/screens"
OK = {"status": "ok", "cols": 80, "rows": 24, "hash": "h1", "screen": "hello"}


class FakeClient:
    def __init__(self, answers):
        self.calls, self.answers = [], answers

    async def request(self, method, path, *, json=None, timeout=None, max_body=None, **_kw):
        self.calls.append((method, path, json, timeout, max_body))
        answer = self.answers.get((method, path))
        if isinstance(answer, Exception):
            raise answer
        return SimpleNamespace(status_code=answer[0], json=lambda: answer[1])


class FakeLinks:
    def __init__(self, client, minor):
        self._client, self._minor = client, minor

    def client(self, _iid):
        return self._client

    def minor(self, _iid):
        return self._minor


@pytest.fixture()
def world(_world, monkeypatch):
    backend = SimpleNamespace(tmux_session="carnivore_local")
    hidden = SimpleNamespace(tmux_session="carnivore_sh-1")
    backends = {"ses_local": backend, "ses_hidden": hidden}
    registry = SimpleNamespace(
        backends=backends, sessions=dict.fromkeys(backends), get_backend=backends.get,
        is_hidden=lambda sid: sid == "ses_hidden",
        registered_ids_for_tmux_name=lambda name: [s for s, b in backends.items() if b.tmux_session == name])
    manager = SimpleNamespace(_registry=registry, _tmux_socket_name=lambda: "test")
    monkeypatch.setattr(_world.http.app.state, "session_manager",
                        manager, raising=False)

    async def fake_capture(_socket, names):
        return {sid: PaneScreen("ok", 80, 24, "L1", "local") for sid in names}

    monkeypatch.setattr(warroom_screen_routes, "capture_many", fake_capture)
    monkeypatch.setattr(peer_listing, "_OWNER_IDS", {_world.key: {"carnivore_api": "ses_owner9", "other": "ses_o2"}})
    _world.peer_client = FakeClient({("POST", "/warroom/screens"): (200, {"screens": {
        "ses_owner9": OK, "ses_o2": {"status": "gone"}}})})
    _world.set_link = lambda client, minor: monkeypatch.setattr(peer_links, "LINKS", FakeLinks(client, minor))
    _world.set_link(_world.peer_client, SCREENS_MINOR)
    _world.ids = [f"remote:{_world.key}:carnivore_api", f"remote:{_world.key}:other"]
    return _world


def _items(world):
    return {"items": [{"id": "ses_local"}, {"id": world.ids[0], "hash": "old"}, {"id": world.ids[1]}]}


def test_one_batched_call_per_peer_maps_answers_back(world) -> None:
    reply = world.http.post(URL, json=_items(world))
    assert reply.status_code == 200, reply.text
    screens = reply.json()["screens"]
    assert screens["ses_local"]["status"] == "ok" and screens["ses_local"]["screen"] == "local"
    assert screens[world.ids[0]]["status"] == "ok" and screens[world.ids[0]]["screen"] == "hello"
    assert screens[world.ids[1]]["status"] == "gone"
    assert len(world.peer_client.calls) == 1
    _m, path, sent, _t, _mb = world.peer_client.calls[0]
    assert path == "/warroom/screens"
    assert sent == {"items": [{"id": "ses_owner9", "hash": "old"}, {"id": "ses_o2", "hash": None}]}


def test_a_peer_below_the_minor_answers_older_with_no_call(world) -> None:
    world.set_link(world.peer_client, SCREENS_MINOR - 1)
    screens = world.http.post(URL, json=_items(world)).json()["screens"]
    assert [screens[i]["status"] for i in world.ids] == ["older", "older"]
    assert world.peer_client.calls == []


def test_a_peer_caller_never_fans_out(world) -> None:
    reply = world.http.post(URL, json={"items": [{"id": world.ids[0]}]},
                            headers={"Authorization": f"Bearer {world.peer_bearer}"})
    assert reply.status_code == 200, reply.text
    assert reply.json()["screens"][world.ids[0]]["status"] == "unsupported"
    assert world.peer_client.calls == []


def test_an_unreachable_peer_answers_unreachable(world) -> None:
    world.peer_client.answers[("POST", "/warroom/screens")] = PeerUnreachable("down")
    screens = world.http.post(URL, json=_items(world)).json()["screens"]
    assert [screens[i]["status"] for i in world.ids] == ["unreachable", "unreachable"]
    assert screens["ses_local"]["status"] == "ok"


def test_a_deeply_nested_reply_costs_only_that_peers_tiles(world) -> None:
    async def request(*_a, **_kw):
        return SimpleNamespace(status_code=200, json=lambda: json.loads("[" * 200_000))

    world.peer_client.request = request
    reply = world.http.post(URL, json=_items(world))
    assert reply.status_code == 200, reply.text
    screens = reply.json()["screens"]
    assert [screens[i]["status"] for i in world.ids] == ["unreachable", "unreachable"]
    assert screens["ses_local"]["status"] == "ok"


def test_a_key_error_from_the_token_mint_is_contained(world) -> None:
    async def request(*_a, **_kw):
        raise KeyError("access_token")

    world.peer_client.request = request
    reply = world.http.post(URL, json=_items(world))
    assert reply.status_code == 200, reply.text
    assert reply.json()["screens"][world.ids[0]]["status"] == "unreachable"
    assert reply.json()["screens"]["ses_local"]["status"] == "ok"


def test_an_offline_peer_at_minor_zero_is_unreachable_not_older(world) -> None:
    world.set_link(None, 0)
    screens = world.http.post(URL, json=_items(world)).json()["screens"]
    assert [screens[i]["status"] for i in world.ids] == ["unreachable", "unreachable"]
    assert world.peer_client.calls == []


def test_a_hanging_peer_is_cut_at_the_total_cap_and_local_tiles_answer(world, monkeypatch) -> None:
    monkeypatch.setattr(warroom_screen_routes, "PEER_TOTAL_SECONDS", 0.2)

    async def request(*_a, **_kw):
        await asyncio.Event().wait()

    world.peer_client.request = request
    screens = world.http.post(URL, json=_items(world)).json()["screens"]
    assert [screens[i]["status"] for i in world.ids] == ["unreachable", "unreachable"]
    assert screens["ses_local"]["status"] == "ok"


def test_a_one_way_computer_answers_unsupported(world) -> None:
    world.peer_client.answers[("POST", "/warroom/screens")] = (403, {"detail": {"code": "computer_one_way"}})
    screens = world.http.post(URL, json=_items(world)).json()["screens"]
    assert [screens[i]["status"] for i in world.ids] == ["unsupported", "unsupported"]


def test_a_peer_caller_cannot_read_a_hidden_companion_shell(world) -> None:
    bearer = {"Authorization": f"Bearer {world.peer_bearer}"}
    reply = world.http.post(URL, json={"items": [{"id": "carnivore_sh-1"}, {"id": "carnivore_local"}]}, headers=bearer)
    screens = reply.json()["screens"]
    assert screens["carnivore_sh-1"]["status"] == "unsupported"
    assert screens["carnivore_local"]["status"] == "ok"
