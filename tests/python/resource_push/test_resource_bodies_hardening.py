
from __future__ import annotations

import asyncio
import json
import time
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import computers_routes, pack_machines_routes, resource_bodies
from src.api.auth import require_auth
from src.core import resource_push
from src.core.event_hub import EventHub
from src.core.resource_push import bodies, topics

WINDOW = 0.02


@pytest.fixture()
def rig():
    loop = asyncio.new_event_loop()
    hub = EventHub()
    resource_push.install(hub.publish, loop=loop, window_seconds=WINDOW, with_bodies=True, wants_bodies=hub.has_owner_client)
    owner = hub.register()
    removers = []
    bodies._running.clear()
    bodies._skip.clear()
    yield loop, hub, owner, removers
    for remove in removers:
        remove()
    resource_push.uninstall()
    loop.close()


def frames(loop, client):
    async def read():
        got = []
        while True:
            try:
                got.append(json.loads(await asyncio.wait_for(client.stream.get(), 0.05)))
            except asyncio.TimeoutError:
                return got
    return loop.run_until_complete(read())


def settle(loop, seconds=WINDOW * 8):
    loop.run_until_complete(asyncio.sleep(seconds))


def test_an_older_frame_finishing_after_a_newer_one_goes_out_without_its_body(rig):
    loop, _, owner, removers = rig

    async def slow():
        await asyncio.sleep(0.3)
        return {"old": True}

    async def fast():
        return {"new": True}

    removers += [bodies.register("computers", [topics.COMPUTERS], slow), bodies.register("stats_feed", [topics.STATS_FEED], fast)]
    resource_push.notify(topics.COMPUTERS)
    settle(loop, WINDOW * 3)
    resource_push.notify(topics.STATS_FEED)
    settle(loop, 0.5)
    got = {tuple(f["topics"]): f for f in frames(loop, owner)}
    assert got[("stats_feed",)]["bodies"] == {"stats_feed": {"new": True}}
    assert "bodies" not in got[("computers",)]


def test_a_nan_body_is_dropped_and_the_frame_still_goes_out(rig):
    loop, _, owner, removers = rig

    async def nan():
        return {"load": float("nan")}

    removers.append(bodies.register("computers", [topics.COMPUTERS], nan))
    resource_push.notify(topics.COMPUTERS)
    settle(loop)
    (frame,) = frames(loop, owner)
    assert frame["topics"] == ["computers"] and "bodies" not in frame


def test_the_hub_never_emits_nan_and_falls_back_to_the_bodyless_notice():
    hub = EventHub()
    owner = hub.register()
    loop = asyncio.new_event_loop()
    try:
        hub.publish({"type": "resources.changed", "topics": ["x"], "bodies": {"k": float("nan")}}, reduced={"type": "resources.changed", "topics": ["x"]})
        raw = loop.run_until_complete(owner.stream.get())
    finally:
        loop.close()
    assert "NaN" not in raw and json.loads(raw) == {"type": "resources.changed", "topics": ["x"]}


def test_no_body_is_built_while_no_owner_socket_is_connected(rig):
    loop, hub, owner, removers = rig
    built = []

    async def read():
        built.append(1)
        return {"ok": True}

    removers.append(bodies.register("computers", [topics.COMPUTERS], read))
    hub.unregister(owner)
    link = hub.register(reduced=True)
    resource_push.notify(topics.COMPUTERS)
    settle(loop)
    assert built == [] and frames(loop, link) == [{"type": "resources.changed", "topics": ["computers"], "seq": 1}]
    owner = hub.register()
    resource_push.notify(topics.COMPUTERS)
    settle(loop)
    assert built == [1] and frames(loop, owner)[-1]["bodies"] == {"computers": {"ok": True}}


def test_a_slow_build_is_not_started_twice(rig, monkeypatch):
    loop, _, owner, removers = rig
    monkeypatch.setattr(bodies, "COLLECT_TIMEOUT_S", 0.05)
    started = []

    async def slow():
        started.append(1)
        await asyncio.sleep(0.4)
        return {"slow": True}

    removers.append(bodies.register("computers", [topics.COMPUTERS], slow))
    for _ in range(3):
        resource_push.notify(topics.COMPUTERS)
        settle(loop, 0.12)
    assert started == [1]
    assert all("bodies" not in f for f in frames(loop, owner))
    settle(loop, 0.5)
    resource_push.notify(topics.COMPUTERS)
    settle(loop, 0.5)
    assert started == [1, 1]


def test_the_frame_after_skip_next_is_bodyless_and_the_one_after_that_is_not(rig):
    loop, _, owner, removers = rig

    async def read():
        return {"n": 1}

    removers.append(bodies.register("stats_feed", [topics.STATS_FEED], read))
    bodies.skip_next("stats_feed")
    resource_push.notify(topics.STATS_FEED)
    settle(loop)
    resource_push.notify(topics.STATS_FEED)
    settle(loop)
    first, second = frames(loop, owner)
    assert "bodies" not in first and second["bodies"] == {"stats_feed": {"n": 1}}


def test_the_computers_and_pack_machines_providers_answer_what_their_routes_answer(monkeypatch):
    view = {"machines": [{"id": "studio", "load": 0.5}], "master_install_id": "m"}
    touched = []
    wired = SimpleNamespace(runtime=SimpleNamespace(touch=lambda: touched.append(1), view=lambda peers: view), peers=lambda: [])
    monkeypatch.setattr(pack_machines_routes, "_wired", lambda: wired)
    computers_view = {"computers": [], "self": {"role": "alpha"}}
    monkeypatch.setattr(computers_routes, "_rt", lambda: object())
    monkeypatch.setattr(computers_routes, "_links", lambda: object())
    monkeypatch.setattr(computers_routes.view, "build_view", lambda rt, links: computers_view)
    app = FastAPI()
    app.include_router(pack_machines_routes.router, prefix="/api/v1")
    app.include_router(computers_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: None
    client = TestClient(app)
    state = SimpleNamespace()
    try:
        resource_bodies.register(state)
        providers = {p.key: p for p in bodies.matching([topics.PACK_MACHINES, topics.COMPUTERS])}
        loop = asyncio.new_event_loop()
        pushed_pack = loop.run_until_complete(providers["pack_machines"].read())
        pushed_computers = loop.run_until_complete(providers["computers"].read())
        loop.close()
    finally:
        for key in ("computers", "pack_machines", "stats_feed"):
            bodies._providers.pop(key, None)
    assert pushed_pack == client.get("/api/v1/pack/machines").json()
    assert pushed_computers == client.get("/api/v1/computers").json()
    assert touched == [1]
