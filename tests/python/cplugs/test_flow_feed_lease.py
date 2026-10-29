
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import List, Tuple

import pytest

from src.core.flow_data import live, tail
from src.cplugs.host import flow_port, frame_serving
from src.cplugs.host.activity_reader import ActivityReader
from src.cplugs.runtime import guards
from src.cplugs.runtime.dispatch import HostDispatcher, HostServices, PluginContext
from src.cplugs.runtime.owner_tokens import OwnerTokens
from src.cplugs.sdk import transcript_events
from tests.python.cplugs.flow import fixture as fx


class World:

    def __init__(self, dispatcher: HostDispatcher, named: List[Tuple[str, str]], clock: List[float]) -> None:
        self.dispatcher, self.named, self.clock = dispatcher, named, clock

    def feed(self, tmp_path: Path, *granted: str, topic: str = "feed", key: str = "k1", frame: bool = True):
        ctx = PluginContext(plugin_id="flowx", install_key=key, data_dir=tmp_path / "d", granted=frozenset(granted), topics=frozenset({"feed"}),
                            tier="sideload")
        try:
            if frame:
                with frame_serving.serving(key):
                    return asyncio.run(self.dispatcher.handle(ctx, "flow.feed", {"seed": "huddle_item", "id": "395", "topic": topic}))
            return asyncio.run(self.dispatcher.handle(ctx, "flow.feed", {"seed": "huddle_item", "id": "395", "topic": topic}))
        except guards.Refused as exc:
            return exc


@pytest.fixture()
def world(tmp_path, monkeypatch):
    made = fx.make_install(tmp_path)
    monkeypatch.setattr(ActivityReader, "_transcript_path", lambda self, conv: next((str(p) for p in made["paths"].values() if p.stem == conv), None))
    monkeypatch.setattr(tail, "CACHE", tail.TailCache())
    clock = [1000.0]
    monkeypatch.setattr(live, "_OWNERS", {"k1:feed": live.FeedWatch(clock=lambda: clock[0])})
    transcript_events.reset()
    named: List[Tuple[str, str]] = []
    port = flow_port.FlowPort(lambda: made["state_dir"], on_topic=lambda key, topic: named.append((key, topic)))
    yield World(HostDispatcher(HostServices(activity=lambda row: None, flow_feed=port.feed), OwnerTokens()), named, clock)
    live.drop_owners("")
    transcript_events.reset()


def test_a_call_leases_the_run_and_an_append_names_the_declared_topic(world, tmp_path):
    answer = world.feed(tmp_path, "flow.read")
    assert answer["items"] and {"cursor", "total", "lanes"} <= set(answer)
    transcript_events.publish_append("ses_somebodyelse", "carnivore_99")
    assert world.named == []
    transcript_events.publish_append(fx.APP[fx.F], None)
    assert world.named == [("k1", "feed")]


def test_no_call_for_46_seconds_ends_the_watch_and_names_nothing(world, tmp_path):
    world.feed(tmp_path, "flow.read")
    assert transcript_events.listening()
    world.clock[0] += live.LEASE_S + 1
    transcript_events.publish_append(fx.APP[fx.F], None)
    assert world.named == [] and not transcript_events.listening()


def test_a_second_call_renews_the_lease(world, tmp_path):
    world.feed(tmp_path, "flow.read")
    world.clock[0] += live.LEASE_S - 5
    world.feed(tmp_path, "flow.read")
    world.clock[0] += live.LEASE_S - 5
    transcript_events.publish_append(fx.APP[fx.F], None)
    assert world.named == [("k1", "feed")]


def test_refusals(world, tmp_path):
    assert world.feed(tmp_path, "sessions.read").code == "not_granted"
    refused = world.feed(tmp_path, "flow.read", topic="other")
    assert isinstance(refused, guards.Refused) and refused.data == {"reason": "topic_not_declared"}
    assert not transcript_events.listening()


def test_the_plugins_own_timer_with_no_frame_open_cannot_take_or_renew_the_lease(world, tmp_path):
    refused = world.feed(tmp_path, "flow.read", frame=False)
    assert isinstance(refused, guards.Refused) and refused.code == "unavailable" and refused.data == {"reason": "no_frame_open"}
    assert not transcript_events.listening()
    world.feed(tmp_path, "flow.read")
    world.clock[0] += live.LEASE_S - 5
    assert world.feed(tmp_path, "flow.read", frame=False).code == "unavailable"
    world.clock[0] += 10
    transcript_events.publish_append(fx.APP[fx.F], None)
    assert world.named == [] and not transcript_events.listening()
