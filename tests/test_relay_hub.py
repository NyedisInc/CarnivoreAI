
from __future__ import annotations

import pytest

from relay.bounded import (
    ENDED_CLOSE_CODE,
    NORMAL_CLOSE_CODE,
    OFFER_ACCEPTED,
    OVERFLOW_CLOSE_CODE,
    REASON_ENDED,
    REASON_OVERFLOW,
    REASON_SHUTDOWN,
    REFUSED_CLOSE_CODE,
    SHUTDOWN_CLOSE_CODE,
    BoundedStream,
    close_for_reason,
)
from relay.hub import RelayHub
from relay.protocol import LinkDeclaration
from tests.relay_support import RecordingFactory, sha256_of

DIGEST_A = sha256_of("token-a")
DIGEST_B = sha256_of("token-b")


def declaration(link_id: str, digest: str = DIGEST_A) -> LinkDeclaration:
    return LinkDeclaration(
        link_id=link_id, token_sha256=digest, session_id="ses_1"
    )


def build_hub(factory: RecordingFactory, **overrides) -> RelayHub:
    kwargs = {
        "redactor_factory": factory,
        "max_watcher_chunks": 256,
        "max_watcher_bytes": 4 * 1024 * 1024,
        "idle_flush_ms": 50,
    }
    kwargs.update(overrides)
    return RelayHub(**kwargs)


def test_declare_builds_exactly_one_redactor_per_link():
    factory = RecordingFactory()
    hub = build_hub(factory)
    hub.declare("pub", [declaration("l1"), declaration("l2", DIGEST_B)])
    assert len(factory.made) == 2
    assert hub.redactor_for("l1") is not hub.redactor_for("l2")


def test_a_declaration_refresh_keeps_the_same_redactor():
    factory = RecordingFactory()
    hub = build_hub(factory)
    hub.declare("pub", [declaration("l1")])
    first = hub.redactor_for("l1")
    dropped = hub.declare("pub", [declaration("l1")])
    assert dropped == []
    assert hub.redactor_for("l1") is first
    assert len(factory.made) == 1


def test_a_rotated_digest_ends_the_old_watchers():
    factory = RecordingFactory()
    hub = build_hub(factory)
    hub.declare("pub", [declaration("l1", DIGEST_A)])
    watcher = hub.add_watcher("l1")
    hub.declare("pub", [declaration("l1", DIGEST_B)])
    assert watcher.stream.reason == REASON_ENDED
    assert hub.digest_for("l1") == DIGEST_B


def test_dropping_a_link_ends_its_watchers_and_forgets_it():
    factory = RecordingFactory()
    hub = build_hub(factory)
    hub.declare("pub", [declaration("l1"), declaration("l2", DIGEST_B)])
    watcher = hub.add_watcher("l1")
    dropped = hub.declare("pub", [declaration("l2", DIGEST_B)])
    assert dropped == ["l1"]
    assert hub.link_ids() == ["l2"]
    assert watcher.stream.reason == REASON_ENDED
    assert hub.digest_for("l1") is None


def test_one_publisher_cannot_drop_another_publishers_links():
    factory = RecordingFactory()
    hub = build_hub(factory)
    hub.declare("pub_a", [declaration("l1")])
    hub.declare("pub_b", [declaration("l2", DIGEST_B)])
    assert hub.link_ids() == ["l1", "l2"]
    hub.declare("pub_b", [])
    assert hub.link_ids() == ["l1"]


@pytest.mark.asyncio
async def test_publish_refuses_a_link_this_publisher_does_not_own():
    factory = RecordingFactory()
    hub = build_hub(factory)
    hub.declare("pub_a", [declaration("l1")])
    assert await hub.publish("pub_b", "l1", "output") is False
    assert await hub.publish("pub_a", "l1", "output") is True
    assert await hub.publish("pub_a", "nope", "output") is False


@pytest.mark.asyncio
async def test_publish_fans_out_the_redacted_text_to_every_watcher():
    factory = RecordingFactory()
    hub = build_hub(factory)
    hub.declare("pub", [declaration("l1")])
    first = hub.add_watcher("l1")
    second = hub.add_watcher("l1")
    await hub.publish("pub", "l1", "hello")
    assert await first.stream.get() == "hello"
    assert await second.stream.get() == "hello"
    assert factory.made[0].fed == ["hello"]


@pytest.mark.asyncio
async def test_a_watcher_past_its_bound_overflows_rather_than_truncating():
    factory = RecordingFactory()
    hub = build_hub(factory, max_watcher_bytes=8)
    hub.declare("pub", [declaration("l1")])
    watcher = hub.add_watcher("l1")
    await hub.publish("pub", "l1", "x" * 64)
    assert watcher.stream.overflowed is True
    assert watcher.stream.reason == REASON_OVERFLOW
    assert close_for_reason(watcher.stream.reason)[0] == OVERFLOW_CLOSE_CODE
    assert await watcher.stream.get() is None
    assert hub.watcher_count("l1") == 0


@pytest.mark.asyncio
async def test_a_slow_watcher_is_invisible_to_the_other_watchers():
    factory = RecordingFactory()
    hub = build_hub(factory, max_watcher_chunks=2)
    hub.declare("pub", [declaration("l1")])
    slow = hub.add_watcher("l1")
    healthy = hub.add_watcher("l1")
    assert slow.stream.offer("backlog", 7) == OFFER_ACCEPTED
    assert slow.stream.offer("backlog", 7) == OFFER_ACCEPTED
    await hub.publish("pub", "l1", "y" * 64)
    assert slow.stream.overflowed is True
    assert healthy.stream.overflowed is False
    assert await healthy.stream.get() == "y" * 64


def test_shutdown_ends_watchers_with_going_away_not_share_ended():
    factory = RecordingFactory()
    hub = build_hub(factory)
    hub.declare("pub", [declaration("l1")])
    watcher = hub.add_watcher("l1")
    hub.shutdown()
    assert watcher.stream.reason == REASON_SHUTDOWN
    assert close_for_reason(watcher.stream.reason)[0] == SHUTDOWN_CLOSE_CODE
    assert hub.link_ids() == []


def test_add_watcher_on_an_undeclared_link_answers_none():
    hub = build_hub(RecordingFactory())
    assert hub.add_watcher("nope") is None


def test_remove_watcher_is_safe_after_the_link_died():
    factory = RecordingFactory()
    hub = build_hub(factory)
    hub.declare("pub", [declaration("l1")])
    watcher = hub.add_watcher("l1")
    hub.declare("pub", [])
    hub.remove_watcher(watcher)
    hub.remove_watcher(watcher)


def test_the_four_close_codes_are_four_different_numbers():
    codes = {
        OVERFLOW_CLOSE_CODE,
        ENDED_CLOSE_CODE,
        REFUSED_CLOSE_CODE,
        SHUTDOWN_CLOSE_CODE,
        NORMAL_CLOSE_CODE,
    }
    assert len(codes) == 5
    assert close_for_reason(REASON_ENDED)[0] == ENDED_CLOSE_CODE
    assert close_for_reason(REASON_OVERFLOW)[0] == OVERFLOW_CLOSE_CODE
    assert close_for_reason(None)[0] == NORMAL_CLOSE_CODE
    reasons = [REASON_ENDED, REASON_OVERFLOW, REASON_SHUTDOWN, None]
    assert REFUSED_CLOSE_CODE not in {close_for_reason(r)[0] for r in reasons}


def test_a_bounded_stream_rejects_a_nonsense_bound():
    with pytest.raises(ValueError):
        BoundedStream(max_items=0, max_bytes=10)
    with pytest.raises(ValueError):
        BoundedStream(max_items=10, max_bytes=0)


@pytest.mark.asyncio
async def test_an_overflowed_stream_admits_nothing_more():
    stream = BoundedStream(max_items=1, max_bytes=1024)
    assert stream.offer("a", 1) == OFFER_ACCEPTED
    assert stream.offer("b", 1) != OFFER_ACCEPTED
    assert stream.offer("c", 1) != OFFER_ACCEPTED
    assert await stream.get() == "a"
    assert await stream.get() is None




def test_a_late_joiner_gets_the_stored_size_first_and_the_publisher_a_join():
    import json

    from relay.link_state import Control

    hub = build_hub(RecordingFactory())
    joined = []
    hub.attach_publisher("pub1", joined.append)
    hub.declare("pub1", [declaration("l1")])
    early = hub.add_watcher("l1")
    assert joined == [], "a publisher that never sent a size is never told"

    assert hub.set_size("pub1", "l1", 170, 50) is True
    late = hub.add_watcher("l1")
    assert joined == ["l1"]
    for watcher in (early, late):
        first = watcher.stream._queue.get_nowait()[0]
        assert isinstance(first, Control)
        assert json.loads(first.text) == {"type": "terminal_size", "cols": 170, "rows": 50}


def test_a_size_from_another_publisher_is_refused():
    hub = build_hub(RecordingFactory())
    hub.declare("pub1", [declaration("l1")])
    assert hub.set_size("pub2", "l1", 80, 24) is False
    assert hub.set_size("pub1", "nope", 80, 24) is False


def test_a_dropped_publisher_connection_leaves_no_notifier_behind():
    hub = build_hub(RecordingFactory())
    hub.attach_publisher("pub1", lambda link_id: None)
    hub.declare("pub1", [declaration("l1")])
    hub.drop_publisher("pub1")
    assert "pub1" not in hub._notifiers


def test_a_reclaim_forgets_the_grid_until_the_new_connection_states_one():
    hub = build_hub(RecordingFactory())
    joined = []
    hub.attach_publisher("new", joined.append)
    hub.declare("old", [declaration("l1")], publisher_id="p" * 32)
    hub.set_size("old", "l1", 170, 50)
    hub.declare("new", [declaration("l1")], publisher_id="p" * 32)
    watcher = hub.add_watcher("l1")
    assert joined == [] and watcher.stream._queue.empty()
