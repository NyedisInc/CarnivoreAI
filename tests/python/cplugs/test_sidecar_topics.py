
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import List, Optional, Tuple

import pytest

from src.core.resource_push.notifier import ResourceNotifier
from src.core.resource_push.topics import CPLUG_TOPIC, all_topics
from src.cplugs.runtime import guards
from src.cplugs.runtime.dispatch import HostDispatcher, HostServices, PluginContext
from src.cplugs.runtime.owner_tokens import OwnerTokens


def _ctx(tmp_path: Path, topics=("runs", "feed")) -> PluginContext:
    return PluginContext(plugin_id="flowx", install_key="uuid1", data_dir=tmp_path / "d", granted=frozenset(), topics=frozenset(topics),
                         tier="sideload")


def _publish(dispatcher: HostDispatcher, ctx: PluginContext, **params):
    try:
        return asyncio.run(dispatcher.handle(ctx, "topic.publish", params))
    except guards.Refused as exc:
        return exc


def test_two_publishes_inside_one_interval_both_reach_the_coalescer(tmp_path: Path) -> None:
    seen: List[Tuple[str, Optional[str]]] = []
    dispatcher = HostDispatcher(HostServices(activity=lambda e: None, publish_topic=lambda t, k: seen.append((t, k))), OwnerTokens())
    ctx = _ctx(tmp_path)
    _publish(dispatcher, ctx, name="runs")
    _publish(dispatcher, ctx, name="runs")
    assert seen == [("cplug.flowx.runs", None), ("cplug.flowx.runs", None)]


def test_undeclared_topic_is_refused(tmp_path: Path) -> None:
    dispatcher = HostDispatcher(HostServices(activity=lambda e: None, publish_topic=lambda t, k: None), OwnerTokens())
    refused = _publish(dispatcher, _ctx(tmp_path), name="other")
    assert isinstance(refused, guards.Refused) and refused.data == {"reason": "topic_not_declared"}


def test_the_burst_ends_with_a_trailing_send_through_the_real_notifier(tmp_path: Path) -> None:
    from src.cplugs.host import sidecar_topics  # noqa: PLC0415

    all_topics()

    async def run() -> List[List[str]]:
        frames: List[List[str]] = []
        notifier = ResourceNotifier(lambda frame: frames.append(list(frame["topics"])) or 1, asyncio.get_running_loop(), window_seconds=0.01)
        publish = sidecar_topics.make_publisher(lambda plugin_id: "uuid1", notifier.notify_coalesced, 0.15)
        dispatcher = HostDispatcher(HostServices(activity=lambda e: None, publish_topic=publish), OwnerTokens())
        ctx = _ctx(tmp_path)
        await dispatcher.handle(ctx, "topic.publish", {"name": "runs", "key": "r1"})
        await dispatcher.handle(ctx, "topic.publish", {"name": "runs", "key": "r1"})
        await asyncio.sleep(0.05)
        first = len(frames)
        await asyncio.sleep(0.3)
        assert first == 1
        return frames

    frames = asyncio.run(run())
    assert frames == [[f"{CPLUG_TOPIC}:uuid1:runs:r1"], [f"{CPLUG_TOPIC}:uuid1:runs:r1"]]


@pytest.mark.parametrize("key,suffix", [(None, ""), ("run-1_a", ":run-1_a"), ("Bad Key", ""), ("x" * 41, ""), ("", "")])
def test_wire_name_carries_only_a_valid_key(key, suffix) -> None:
    from src.cplugs.host import sidecar_topics  # noqa: PLC0415

    assert sidecar_topics.wire_topic("uuid1", "runs", key) == f"{CPLUG_TOPIC}:uuid1:runs{suffix}"


def test_keys_share_one_slot_per_install_and_name_and_the_map_stays_bounded() -> None:
    from src.cplugs.host import sidecar_topics  # noqa: PLC0415
    from src.core.resource_push import notifier as notifier_module  # noqa: PLC0415

    async def run() -> Tuple[List[List[str]], int]:
        frames: List[List[str]] = []
        notifier = ResourceNotifier(lambda frame: frames.append(list(frame["topics"])) or 1, asyncio.get_running_loop(), window_seconds=0.0)
        publish = sidecar_topics.make_publisher(lambda plugin_id: "uuid1", notifier.notify_coalesced, 0.05)
        publish("cplug.flowx.runs", "r1")
        publish("cplug.flowx.runs", "r2")
        publish("cplug.flowx.runs", "r3")
        await asyncio.sleep(0.15)
        for index in range(notifier_module.PRUNE_ABOVE * 3):
            publish("cplug.flowx.runs", f"run-{index}")
            await asyncio.sleep(0.06)
        return frames, len(notifier._last_sent)

    frames, slots = asyncio.run(run())
    assert frames[:2] == [[f"{CPLUG_TOPIC}:uuid1:runs:r1"], [f"{CPLUG_TOPIC}:uuid1:runs"]]
    assert slots <= 2
