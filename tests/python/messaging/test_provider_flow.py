
from __future__ import annotations

import asyncio
import json

from src.api import messaging_routes
from src.core.messaging import events, message_store, notices, store, stream

from .conftest import UUID_A, bind, received


def _view(world):
    state = world.rt.providers[world.pid]
    traffic = message_store.last_traffic(world.pid)
    return messaging_routes.provider_view(store.get_provider(world.pid), state, traffic)["stream"]


def _consume(world, *frames):
    async def feed():
        for frame in frames:
            yield json.dumps(frame)

    asyncio.run(stream.consume(world.rt, world.rt.providers[world.pid], feed()))


def test_a_new_provider_is_stale_with_no_traffic(world):
    view = _view(world)
    assert view["flow"] == "stale" and view["bridge"] is None
    assert view["last_inbound_at"] is None and view["last_outbound_at"] is None


def test_a_hello_records_the_bridge_head_and_makes_a_live_stream_flowing(world):
    _consume(world, {"type": "hello", "cpp": 1, "after": 0, "oldest": 1, "latest": 106, "gap": False})
    view = _view(world)
    assert view["state"] == "live" and view["flow"] == "flowing"
    assert view["bridge"]["latest"] == 106 and view["bridge"]["seen_at"] > 0


def test_a_stream_that_is_not_live_is_stale_even_with_a_head_seen(world):
    _consume(world, {"type": "hello", "cpp": 1, "after": 0, "oldest": 1, "latest": 5, "gap": False})
    state = world.rt.providers[world.pid]
    state.row = store.update_provider(world.pid, stream_state="reconnecting")
    assert _view(world)["flow"] == "stale"


def test_last_inbound_and_outbound_times_follow_the_messages(world):
    bind(world, UUID_A, default=True)
    asyncio.run(events.handle_event(world.rt, world.rt.providers[world.pid], received(1, "status")))
    assert _view(world)["last_outbound_at"] is None
    assert asyncio.run(world.rt.send_notice(world.rt.providers[world.pid], world.conv_id, notices.TEST, None))
    view = _view(world)
    assert view["last_inbound_at"] is not None
    assert view["last_outbound_at"] >= view["last_inbound_at"]
