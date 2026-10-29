import pytest
import structlog
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from src.api import deps, events_routes, ws_dead_token
from src.api.deps import SUBPROTOCOL_MARKER

DEAD = "dead.token.value"


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(ws_dead_token, "DEAD_TOKENS", ws_dead_token.DeadTokenLog())
    decodes = {"n": 0}
    real = deps.decode_access_token

    def counting(token):
        decodes["n"] += 1
        return real(token)

    monkeypatch.setattr(deps, "decode_access_token", counting)
    app = FastAPI()
    app.include_router(events_routes.router)
    return TestClient(app), decodes


def _handshake(tc, token):
    with pytest.raises(WebSocketDisconnect) as refused:
        with tc.websocket_connect("/ws/events", subprotocols=[SUBPROTOCOL_MARKER, token]):
            pass
    return refused.value.code


def test_a_repeated_dead_token_is_refused_from_memory_and_logged_once(client):
    tc, decodes = client
    with structlog.testing.capture_logs() as logs:
        codes = [_handshake(tc, DEAD) for _ in range(5)]
        other = _handshake(tc, "another.dead.token")
    assert codes == [4401] * 5 and other == 4401
    warned = [e for e in logs if e["event"] == "events_websocket_auth_failed"]
    assert len(warned) == 2, warned
    assert warned[0]["client_ip"] and warned[0]["repeats"] == 0 and "user_agent" in warned[0]
    assert decodes["n"] == 2, "a known dead token must not be decoded again"
    assert all(DEAD not in str(e) for e in logs), "the token must never be logged"


def test_after_the_window_the_next_warning_carries_the_folded_count():
    clock = {"t": 0.0}
    table = ws_dead_token.DeadTokenLog(window_s=600, clock=lambda: clock["t"])
    assert table.refused("t", "1.2.3.4").log is True
    for _ in range(19):
        clock["t"] += 31
        assert table.seen("t", "1.2.3.4") is True
        assert table.refused("t", "1.2.3.4").log is False
    clock["t"] += 31
    later = table.refused("t", "1.2.3.4")
    assert later.log is True and later.repeats == 19
    assert table.seen("t", "5.6.7.8") is False
