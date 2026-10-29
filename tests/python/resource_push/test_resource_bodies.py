
from __future__ import annotations

import asyncio
import json

import pytest

from src.core import resource_push
from src.core.event_hub import EventHub
from src.core.resource_push import bodies, topics

WINDOW = 0.02


@pytest.fixture()
def rig():
    loop = asyncio.new_event_loop()
    hub = EventHub()
    resource_push.install(hub.publish, loop=loop, window_seconds=WINDOW, with_bodies=True)
    owner, link = hub.register(), hub.register(reduced=True)
    removers = []
    yield loop, owner, link, removers
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


def test_owner_gets_the_body_and_a_reduced_socket_gets_the_frame_without_it(rig):
    loop, owner, link, removers = rig
    served = []

    async def read():
        served.append(1)
        return {"machines": ["studio"]}

    removers.append(bodies.register("pack_machines", [topics.PACK_MACHINES], read))
    removers.append(bodies.register("computers", [topics.COMPUTERS, topics.PACK_MACHINES], lambda: _none()))
    resource_push.notify(topics.PACK_MACHINES)
    resource_push.notify(topics.LAYOUTS)
    loop.run_until_complete(asyncio.sleep(WINDOW * 6))
    mine, theirs = frames(loop, owner), frames(loop, link)
    owner_frame = next(f for f in mine if "pack_machines" in f["topics"])
    link_frame = next(f for f in theirs if "pack_machines" in f["topics"])
    assert owner_frame["bodies"] == {"pack_machines": {"machines": ["studio"]}}
    assert "bodies" not in link_frame and link_frame["topics"] == owner_frame["topics"]
    assert any(f["topics"] == ["layouts"] and "bodies" not in f for f in mine)
    assert served == [1]


def test_an_oversize_or_failing_provider_drops_only_its_own_body(rig):
    loop, owner, _, removers = rig

    async def big():
        return {"x": "y" * (bodies.MAX_BODY_BYTES + 1)}

    async def boom():
        raise RuntimeError("db gone")

    async def fine():
        return {"ok": True}

    removers += [bodies.register("computers", [topics.COMPUTERS], big), bodies.register("pack_machines", [topics.COMPUTERS], boom),
                 bodies.register("stats_feed", [topics.COMPUTERS], fine)]
    resource_push.notify(topics.COMPUTERS)
    loop.run_until_complete(asyncio.sleep(WINDOW * 6))
    frame = frames(loop, owner)[-1]
    assert frame["topics"] == ["computers"] and frame["bodies"] == {"stats_feed": {"ok": True}}


async def _none():
    return None
