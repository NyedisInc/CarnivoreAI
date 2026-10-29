
from __future__ import annotations

import asyncio
import base64
import inspect
import sys
from pathlib import Path

import pytest

import os
import tempfile

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_vf_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_vf_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core import viewer_fanout  # noqa: E402
from src.core.bounded_stream import (  # noqa: E402
    OFFER_ACCEPTED,
    OFFER_CLOSED,
    OFFER_OVERFLOWED,
    OVERFLOW_CLOSE_CODE,
)

CHUNK = b"x" * 8192
ENCODED = base64.b64encode(CHUNK).decode("utf-8")




def test_the_bound_is_the_one_the_plan_named():
    assert viewer_fanout.MAX_VIEWER_QUEUE_CHUNKS == 256
    assert viewer_fanout.MAX_VIEWER_QUEUE_BYTES == 4 * 1024 * 1024


def test_the_chunk_count_is_what_actually_fires_for_terminal_output():
    per_chunk = len(ENCODED)
    assert per_chunk == 10924
    at_chunk_bound = per_chunk * viewer_fanout.MAX_VIEWER_QUEUE_CHUNKS
    assert at_chunk_bound < viewer_fanout.MAX_VIEWER_QUEUE_BYTES


def test_a_stalled_viewer_stops_growing_at_the_bound():
    stream = viewer_fanout.new_viewer_stream("stalled")
    accepted = 0
    overflowed_at = None
    for i in range(5000):
        outcome = viewer_fanout.offer_pty(stream, ENCODED)
        if outcome == OFFER_ACCEPTED:
            accepted += 1
        elif outcome == OFFER_OVERFLOWED and overflowed_at is None:
            overflowed_at = i

    assert accepted == viewer_fanout.MAX_VIEWER_QUEUE_CHUNKS
    assert overflowed_at == viewer_fanout.MAX_VIEWER_QUEUE_CHUNKS
    assert stream.queued_bytes <= viewer_fanout.MAX_VIEWER_QUEUE_BYTES
    assert stream.overflowed is True


def test_a_viewer_inside_its_bound_keeps_every_chunk():
    stream = viewer_fanout.new_viewer_stream("healthy")
    for _ in range(viewer_fanout.MAX_VIEWER_QUEUE_CHUNKS):
        assert viewer_fanout.offer_pty(stream, ENCODED) == OFFER_ACCEPTED
    assert stream.overflowed is False
    assert stream.closed is False


def test_no_chunk_is_ever_partially_delivered():

    async def scenario():
        stream = viewer_fanout.new_viewer_stream("v")
        payloads = [base64.b64encode(f"chunk-{i}".encode()).decode()
                    for i in range(5)]
        for p in payloads:
            viewer_fanout.offer_pty(stream, p)
        stream.close()
        seen = []
        while (frame := await stream.get()) is not None:
            seen.append(frame.payload)
        assert seen == payloads

    asyncio.run(scenario())


def test_the_overflow_close_code_is_an_application_code():
    assert viewer_fanout.VIEWER_OVERFLOW_CLOSE_CODE == OVERFLOW_CLOSE_CODE
    assert 4000 <= viewer_fanout.VIEWER_OVERFLOW_CLOSE_CODE <= 4999




def test_the_fan_out_is_synchronous_so_the_tail_loop_never_awaits_a_viewer():
    from src.core.session_manager import SessionManager

    handler = SessionManager._make_output_handler(
        _FakeManagerWithSubscribers({}), "ses_1"
    )
    assert not asyncio.iscoroutinefunction(handler)
    assert not asyncio.iscoroutinefunction(viewer_fanout.offer_pty)
    assert not asyncio.iscoroutinefunction(viewer_fanout.offer_text)


class _FakeManagerWithSubscribers:

    def __init__(self, subscribers):
        from src.core.sessions.registry import SessionRegistry

        self._registry = SessionRegistry(log_cap=lambda: 1000)
        self._registry.subscribers = subscribers


def test_a_stalled_viewer_never_delays_a_healthy_one():

    async def scenario():
        healthy = viewer_fanout.new_viewer_stream("healthy")
        stalled = viewer_fanout.new_viewer_stream("stalled")
        manager = _FakeManagerWithSubscribers({"ses_1": [healthy, stalled]})

        from src.core.session_manager import SessionManager
        handler = SessionManager._make_output_handler(manager, "ses_1")

        for i in range(50):
            handler(f"line-{i}\r\n".encode())
            frame = await asyncio.wait_for(healthy.get(), timeout=1.0)
            assert base64.b64decode(frame.payload) == f"line-{i}\r\n".encode()

        assert healthy.queued_items == 0
        assert stalled.queued_items == 50
        assert healthy.overflowed is False
        assert healthy.closed is False

    asyncio.run(scenario())


def test_an_overflowing_viewer_is_dropped_and_the_other_is_untouched():

    async def scenario():
        healthy = viewer_fanout.new_viewer_stream("healthy")
        stalled = viewer_fanout.new_viewer_stream("stalled")
        subs = [healthy, stalled]
        manager = _FakeManagerWithSubscribers({"ses_1": subs})

        from src.core.session_manager import SessionManager
        handler = SessionManager._make_output_handler(manager, "ses_1")

        for _ in range(viewer_fanout.MAX_VIEWER_QUEUE_CHUNKS + 5):
            handler(CHUNK)
            if not healthy.closed:
                await healthy.get()

        assert stalled.overflowed is True
        assert healthy.overflowed is False
        assert healthy.closed is False
        assert subs == [healthy]

    asyncio.run(scenario())


def test_session_isolation_survives_the_rewrite():

    async def scenario():
        a = viewer_fanout.new_viewer_stream("a")
        b = viewer_fanout.new_viewer_stream("b")
        manager = _FakeManagerWithSubscribers({"ses_a": [a], "ses_b": [b]})

        from src.core.session_manager import SessionManager
        handler_a = SessionManager._make_output_handler(manager, "ses_a")
        handler_a(b"only-for-A")

        assert a.queued_items == 1
        assert b.queued_items == 0
        assert base64.b64decode((await a.get()).payload) == b"only-for-A"

    asyncio.run(scenario())




def test_exactly_one_coroutine_in_the_endpoint_sends_after_the_handshake():
    from src.api import websocket as ws_mod
    from src.api import ws_receive as receive_mod
    from src.api import ws_viewer_drain as drain_mod

    senders = []
    for mod in (ws_mod, drain_mod, receive_mod):
        for name, fn in vars(mod).items():
            if not inspect.iscoroutinefunction(fn):
                continue
            if getattr(fn, "__module__", None) != mod.__name__:
                continue
            src = inspect.getsource(fn)
            if "websocket.send_" in src:
                senders.append(name)
    assert sorted(senders) == ["_drain_viewer", "websocket_terminal"], senders

    endpoint_src = inspect.getsource(ws_mod.websocket_terminal)
    assert endpoint_src.count("await paint_on_attach(") == 2, (
        "paint_on_attach's call sites moved; both must stay inside the "
        "handshake, above the create_task block"
    )
    handshake_end = endpoint_src.index("writer_task = asyncio.create_task(")
    assert endpoint_src.rindex("await paint_on_attach(") < handshake_end


def test_the_read_loop_answers_through_the_stream_and_never_the_socket():
    from src.api import ws_receive

    src = inspect.getsource(ws_receive.receive_messages)
    assert "websocket.send" not in src
    assert "viewer_fanout.offer_text" in src


def test_the_broadcast_paths_offer_rather_than_send():
    from src.api.websocket import ConnectionManager

    for method in (ConnectionManager.broadcast, ConnectionManager.broadcast_to_session):
        src = inspect.getsource(method)
        assert "send_text" not in src, method.__name__
        assert "_offer(" in src, method.__name__


def test_a_socket_with_no_stream_is_reported_undeliverable_not_sent_to():
    from src.api.websocket import ConnectionManager

    manager = ConnectionManager()
    assert manager._offer(object(), '{"type":"log"}') is False


def test_the_feeders_never_touch_the_socket():
    from src.api import websocket as ws_mod

    params = list(inspect.signature(ws_mod._pump_text).parameters)
    assert params == ["queue", "stream"]
    assert "websocket" not in inspect.getsource(ws_mod._pump_text)


def test_text_and_pty_frames_share_one_viewer_budget():
    stream = viewer_fanout.new_viewer_stream("v")
    viewer_fanout.offer_text(stream, "x" * 100)
    assert stream.queued_items == 1
    assert stream.queued_bytes == 100
    viewer_fanout.offer_pty(stream, ENCODED)
    assert stream.queued_items == 2
    assert stream.queued_bytes == 100 + len(ENCODED)


def test_a_finished_stream_takes_nothing_more():
    stream = viewer_fanout.new_viewer_stream("v")
    stream.close()
    assert viewer_fanout.offer_pty(stream, ENCODED) == OFFER_CLOSED
    assert viewer_fanout.offer_text(stream, "hello") == OFFER_CLOSED


def test_unsubscribing_closes_the_stream_so_the_writer_can_finish():
    from src.core.sessions.registry import SessionRegistry

    registry = SessionRegistry(log_cap=lambda: 1000)
    stream = viewer_fanout.new_viewer_stream("v")
    registry.subscribers["ses_1"] = [stream]
    registry.unsubscribe(stream, "ses_1")
    assert stream.closed is True
    assert registry.subscribers["ses_1"] == []


def test_the_stream_check_is_structural_and_not_an_identity_test():
    import inspect

    src = inspect.getsource(viewer_fanout.is_viewer_stream)
    body = src[src.rindex('"""') + 3:]
    assert "isinstance" not in body

    assert viewer_fanout.is_viewer_stream(
        viewer_fanout.new_viewer_stream("v")) is True
    assert viewer_fanout.is_viewer_stream(asyncio.Queue()) is False
    assert viewer_fanout.is_viewer_stream(object()) is False
    assert viewer_fanout.is_viewer_stream(None) is False

    class _Lookalike:
        offer = None
        close = None
        overflowed = False

    assert viewer_fanout.is_viewer_stream(_Lookalike()) is True


def test_unsubscribing_a_bare_queue_does_not_raise():
    from src.core.sessions.registry import SessionRegistry

    registry = SessionRegistry(log_cap=lambda: 1000)
    queue = asyncio.Queue()
    registry.subscribers["ses_1"] = [queue]
    registry.unsubscribe(queue, "ses_1")
    assert registry.subscribers["ses_1"] == []


@pytest.mark.parametrize("bad", [0, -1])
def test_a_bound_must_be_positive(bad):
    from src.core.bounded_stream import BoundedStream

    with pytest.raises(ValueError):
        BoundedStream(max_items=bad, max_bytes=1024)
    with pytest.raises(ValueError):
        BoundedStream(max_items=8, max_bytes=bad)
