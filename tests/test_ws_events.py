
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import jwt as pyjwt
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.bounded_stream import (  # noqa: E402
    OFFER_ACCEPTED,
    OFFER_CLOSED,
    OFFER_OVERFLOWED,
    REASON_DONE,
    REASON_OVERFLOW,
    BoundedStream,
)
from src.core.event_hub import (  # noqa: E402
    EVENTS_OVERFLOW_CLOSE_CODE,
    MAX_EVENT_QUEUE_BYTES,
    MAX_EVENT_QUEUE_ITEMS,
    EventHub,
    get_hub,
)
from src.core import session_change_notice  # noqa: E402
from src.models import WSMessageType  # noqa: E402

JWT_SECRET = "test-secret-for-ws-events"


@pytest.fixture(autouse=True)
def patched_auth_config(monkeypatch):
    from src.config import settings as real_settings

    fake_auth = SimpleNamespace(
        jwt_secret=JWT_SECRET,
        jwt_expiry_minutes=60,
        access_token_ttl_seconds=900,
        refresh_token_ttl_seconds=604800,
        refresh_grace_seconds=10,
        totp_secret="X" * 32,
    )

    class _FakeSettings:
        def load_auth_config(self):
            return fake_auth

        def __getattr__(self, name):
            return getattr(real_settings, name)

    fake_settings = _FakeSettings()
    monkeypatch.setattr("src.api.auth.settings", fake_settings)
    yield


def _mint_token(expiry_minutes: int = 60) -> str:
    payload = {
        "exp": datetime.utcnow() + timedelta(minutes=expiry_minutes),
        "iat": datetime.utcnow(),
        "sub": "claudetunnel_user",
        "typ": "access",
    }
    return pyjwt.encode(payload, JWT_SECRET, algorithm="HS256")


@pytest.fixture
def events_app():
    from fastapi import FastAPI

    from src.api.events_routes import router as events_router

    app = FastAPI()
    app.state.event_hub = EventHub()
    app.include_router(events_router)
    return app




def test_an_unauthenticated_connection_is_refused(events_app):
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect

    client = TestClient(events_app)
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws/events") as ws:
            ws.receive_text()
    assert exc.value.code == 4401


def test_an_invalid_token_is_refused(events_app):
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect

    client = TestClient(events_app)
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(
            "/ws/events", subprotocols=["cloude.jwt.v1", "not-a-jwt"]
        ) as ws:
            ws.receive_text()
    assert exc.value.code == 4401


def test_a_valid_token_is_accepted_and_the_marker_is_echoed(events_app):
    from fastapi.testclient import TestClient

    client = TestClient(events_app)
    with client.websocket_connect(
        "/ws/events", subprotocols=["cloude.jwt.v1", _mint_token()]
    ) as ws:
        assert ws.accepted_subprotocol == "cloude.jwt.v1"
        hello = ws.receive_json()
        assert hello["type"] == WSMessageType.EVENTS_HELLO


def test_the_token_never_appears_in_the_url(events_app):
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect

    client = TestClient(events_app)
    token = _mint_token()
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(f"/ws/events?token={token}") as ws:
            ws.receive_text()
    assert exc.value.code == 4401




def test_the_first_frame_tells_the_client_to_refresh(events_app):
    from fastapi.testclient import TestClient

    client = TestClient(events_app)
    with client.websocket_connect(
        "/ws/events", subprotocols=["cloude.jwt.v1", _mint_token()]
    ) as ws:
        hello = ws.receive_json()
        assert hello["type"] == "events.hello"
        assert hello["client_id"]


def test_the_hello_frame_carries_the_running_server_version(events_app):
    from fastapi.testclient import TestClient

    from src.core.version import resolve_version

    client = TestClient(events_app)
    with client.websocket_connect(
        "/ws/events", subprotocols=["cloude.jwt.v1", _mint_token()]
    ) as ws:
        hello = ws.receive_json()
        assert hello["server_version"] == resolve_version()


def test_the_hello_frame_advertises_every_pushed_resource_topic(events_app):
    from fastapi.testclient import TestClient

    from src.core.resource_push.topics import all_topics

    client = TestClient(events_app)
    with client.websocket_connect(
        "/ws/events", subprotocols=["cloude.jwt.v1", _mint_token()]
    ) as ws:
        hello = ws.receive_json()
        assert hello["resource_topics"] == list(all_topics())
        assert {"browsers", "layouts", "toasts", "projects"} <= set(hello["resource_topics"])


def test_a_published_notice_reaches_a_connected_client(events_app):
    from fastapi.testclient import TestClient

    client = TestClient(events_app)
    with client.websocket_connect(
        "/ws/events", subprotocols=["cloude.jwt.v1", _mint_token()]
    ) as ws:
        ws.receive_json()
        hub = events_app.state.event_hub
        hub.publish(
            session_change_notice.build_status_notice(
                session_id="ses_b", activity_status="question", unread=True
            )
        )
        frame = ws.receive_json()
    assert frame["type"] == "session.status"
    assert frame["session_id"] == "ses_b"
    assert frame["activity_status"] == "question"
    assert frame["unread"] is True




def test_a_stream_inside_its_bound_keeps_every_item():
    stream = BoundedStream(max_items=4, max_bytes=1024)
    for i in range(4):
        assert stream.offer(f"frame-{i}", 8) == OFFER_ACCEPTED
    assert stream.closed is False
    assert stream.overflowed is False
    assert stream.queued_items == 4


def test_crossing_the_item_bound_overflows_and_latches():
    stream = BoundedStream(max_items=2, max_bytes=1 << 20)
    assert stream.offer("a", 1) == OFFER_ACCEPTED
    assert stream.offer("b", 1) == OFFER_ACCEPTED
    assert stream.offer("c", 1) == OFFER_OVERFLOWED
    assert stream.offer("d", 1) == OFFER_CLOSED
    assert stream.overflowed is True
    assert stream.reason == REASON_OVERFLOW


def test_crossing_the_byte_bound_overflows_even_under_the_item_bound():
    stream = BoundedStream(max_items=1000, max_bytes=100)
    assert stream.offer("small", 60) == OFFER_ACCEPTED
    assert stream.offer("big", 60) == OFFER_OVERFLOWED
    assert stream.overflowed is True


def test_an_ordinary_close_cannot_overwrite_a_recorded_overflow():
    stream = BoundedStream(max_items=1, max_bytes=1 << 20)
    stream.offer("a", 1)
    assert stream.offer("b", 1) == OFFER_OVERFLOWED
    stream.close(REASON_DONE)
    assert stream.reason == REASON_OVERFLOW
    assert stream.overflowed is True


def test_a_reader_drains_what_was_admitted_before_it_learns_of_closure():

    async def scenario():
        stream = BoundedStream(max_items=4, max_bytes=1 << 20)
        stream.offer("one", 3)
        stream.offer("two", 3)
        stream.close(REASON_DONE)
        assert await stream.get() == "one"
        assert await stream.get() == "two"
        assert await stream.get() is None

    asyncio.run(scenario())


def test_the_offer_path_is_synchronous_so_a_producer_never_awaits():
    assert not asyncio.iscoroutinefunction(BoundedStream.offer)
    assert not asyncio.iscoroutinefunction(EventHub.publish)




def test_a_stalled_client_never_delays_a_healthy_one():
    hub = EventHub(max_items=4, max_bytes=1 << 20)
    fast = hub.register()
    slow = hub.register()

    async def scenario():
        for i in range(3):
            assert hub.publish({"type": "sessions.changed", "reason": str(i)}) == 2
            frame = await asyncio.wait_for(fast.stream.get(), timeout=1.0)
            assert json.loads(frame)["reason"] == str(i)

        assert fast.stream.queued_items == 0
        assert slow.stream.queued_items == 3
        assert slow.stream.overflowed is False

    asyncio.run(scenario())
    assert hub.client_count == 2


def test_an_overflowing_client_is_dropped_and_the_other_is_untouched():
    hub = EventHub(max_items=2, max_bytes=1 << 20)
    fast = hub.register()
    slow = hub.register()

    async def scenario():
        for i in range(4):
            hub.publish({"type": "sessions.changed", "reason": str(i)})
            if not fast.stream.closed:
                await asyncio.wait_for(fast.stream.get(), timeout=1.0)

        assert slow.stream.overflowed is True
        assert fast.stream.overflowed is False
        assert fast.stream.closed is False
        assert hub.client_count == 1

    asyncio.run(scenario())


def test_an_overflowing_client_is_closed_with_a_distinguishable_code(events_app):
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect

    events_app.state.event_hub = EventHub(max_items=1, max_bytes=1 << 20)
    client = TestClient(events_app)

    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(
            "/ws/events", subprotocols=["cloude.jwt.v1", _mint_token()]
        ) as ws:
            ws.receive_json()
            hub = events_app.state.event_hub
            hub.publish({"type": "sessions.changed", "reason": "a"})
            hub.publish({"type": "sessions.changed", "reason": "b"})
            for _ in range(4):
                ws.receive_text()
    assert exc.value.code == EVENTS_OVERFLOW_CLOSE_CODE




def test_the_endpoint_has_exactly_one_coroutine_that_sends(events_app):
    import inspect

    from src.api import events_routes

    source = inspect.getsource(events_routes)
    senders = [
        name
        for name, fn in vars(events_routes).items()
        if inspect.iscoroutinefunction(fn)
        and "websocket.send_" in inspect.getsource(fn)
    ]
    assert senders == ["_drain_to_socket"], senders
    reader_src = inspect.getsource(events_routes._read_from_socket)
    assert "websocket.send" not in reader_src
    assert "stream.offer" in reader_src
    assert source.count("await websocket.send_text(") == 1


def test_a_ping_is_answered_through_the_one_writer(events_app):
    from fastapi.testclient import TestClient

    client = TestClient(events_app)
    with client.websocket_connect(
        "/ws/events", subprotocols=["cloude.jwt.v1", _mint_token()]
    ) as ws:
        ws.receive_json()
        ws.send_text(json.dumps({"type": "ping"}))
        assert ws.receive_json()["type"] == "pong"


def test_an_unrecognised_client_frame_does_not_close_the_socket(events_app):
    from fastapi.testclient import TestClient

    client = TestClient(events_app)
    with client.websocket_connect(
        "/ws/events", subprotocols=["cloude.jwt.v1", _mint_token()]
    ) as ws:
        ws.receive_json()
        ws.send_text(json.dumps({"type": "something.new"}))
        ws.send_text("not json at all")
        ws.send_text(json.dumps({"type": "ping"}))
        assert ws.receive_json()["type"] == "pong"




def test_a_status_notice_omits_what_was_not_measured():
    frame = session_change_notice.build_status_notice(session_id="ses_1")
    assert frame == {"type": "session.status", "session_id": "ses_1"}
    assert "unread" not in frame
    assert "startup_gate" not in frame


def test_a_status_notice_carries_only_compact_fields():
    frame = session_change_notice.build_status_notice(
        session_id="ses_1",
        tmux_session="cloude_x",
        epoch=1700000000,
        activity_status="working",
        unread=False,
        startup_gate="ready",
    )
    assert set(frame) == {
        "type",
        "session_id",
        "tmux_session",
        "epoch",
        "activity_status",
        "unread",
        "startup_gate",
    }


def test_the_structural_notice_carries_no_data():
    frame = session_change_notice.build_structural_notice("created")
    assert frame == {"type": "sessions.changed", "reason": "created"}


def test_creating_and_destroying_a_session_publish_the_structural_notice():
    import inspect

    from src.api import session_crud_routes as routes

    create_src = inspect.getsource(routes.create_session_with_extra)
    public_src = inspect.getsource(routes.create_session)
    destroy_src = inspect.getsource(routes.destroy_session)
    assert "create_session_with_extra(request, body)" in public_src
    assert 'build_structural_notice("created")' in create_src
    assert 'build_structural_notice("destroyed")' in destroy_src
    assert create_src.index("build_structural_notice") < create_src.index(
        "except HTTPException:"
    )


def test_publishing_without_a_hub_is_a_no_op():
    assert session_change_notice.publish(SimpleNamespace(), {"type": "x"}) == 0
    assert get_hub(SimpleNamespace()) is None


def test_an_unencodable_frame_is_refused_rather_than_delivered_broken():
    hub = EventHub()
    client = hub.register()
    assert hub.publish({"type": "x", "bad": object()}) == 0
    assert client.stream.closed is False
    assert hub.client_count == 1


def test_the_published_bounds_are_the_ones_the_plan_named():
    assert MAX_EVENT_QUEUE_ITEMS == 256
    assert MAX_EVENT_QUEUE_BYTES == 1 * 1024 * 1024


def test_the_frame_types_live_in_the_one_message_enum():
    assert WSMessageType.EVENTS_HELLO.value == "events.hello"
    assert WSMessageType.SESSION_STATUS_CHANGED.value == "session.status"
    assert WSMessageType.SESSIONS_CHANGED.value == "sessions.changed"
    assert WSMessageType.PREFERENCES_CHANGED.value == "preferences.changed"

    from src.api.preferences_routes import PREFERENCES_CHANGED_EVENT

    assert PREFERENCES_CHANGED_EVENT == WSMessageType.PREFERENCES_CHANGED.value


def test_the_status_notice_is_not_gated_by_the_notification_mute():
    import inspect

    source = inspect.getsource(session_change_notice.publish_attention_status)
    assert "policy" not in source
    assert "mute" not in source
