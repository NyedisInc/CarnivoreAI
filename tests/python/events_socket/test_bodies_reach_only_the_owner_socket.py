import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import events_routes
from src.api.deps import SUBPROTOCOL_MARKER
from src.core.event_hub import EventHub

FULL = {"type": "resources.changed", "topics": ["pack_machines"], "seq": 1, "bodies": {"pack_machines": {"machines": ["studio"]}}}
REDUCED = {"type": "resources.changed", "topics": ["pack_machines"], "seq": 1}


class ScopeTag:

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "websocket":
            tag = dict(scope["headers"]).get(b"x-test-via")
            if tag:
                scope[tag.decode()] = True
        await self.app(scope, receive, send)


@pytest.fixture()
def rig(monkeypatch):
    monkeypatch.setattr(events_routes, "verify_jwt_from_subprotocol", lambda ws: (True, ""))
    app = FastAPI()
    app.include_router(events_routes.router)
    app.state.event_hub = EventHub()
    with TestClient(ScopeTag(app)) as tc:
        yield tc, app.state.event_hub


def _frame_after_publish(tc, hub, headers):
    with tc.websocket_connect("/ws/events", subprotocols=[SUBPROTOCOL_MARKER, "t"], headers=headers) as ws:
        assert json.loads(ws.receive_text())["type"] == "events.hello"
        tc.portal.call(lambda: hub.publish(FULL, reduced=REDUCED))
        return json.loads(ws.receive_text())


@pytest.mark.parametrize("tag", ["via_link", "via_peer_link"])
def test_a_phone_link_or_paired_mac_socket_gets_the_frame_without_bodies(rig, tag):
    tc, hub = rig
    assert _frame_after_publish(tc, hub, {"x-test-via": tag}) == REDUCED


def test_the_owner_socket_gets_the_bodies(rig):
    tc, hub = rig
    assert _frame_after_publish(tc, hub, {}) == FULL
    assert hub.has_owner_client() is False
