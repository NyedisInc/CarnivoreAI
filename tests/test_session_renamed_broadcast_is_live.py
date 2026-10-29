
from __future__ import annotations

import json
import os
import tempfile

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_ren_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_ren_logs_"))
os.environ.setdefault("TOTP_SECRET", "JBSWY3DPEHPK3PXP")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-not-a-real-one-32b")

# ruff: noqa: E402
from fastapi import FastAPI
from fastapi.testclient import TestClient

import src.api.routes as routes_mod
import src.api.session_rename_routes as rename_routes_mod
from src.api.auth import require_auth
from src.core import session_change_notice
from src.core.event_hub import EventHub
from src.models import SessionRenamedMessage, WSMessageType


class _RecordingConnectionManager:

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def broadcast_to_session(self, session_id: str, payload: str) -> None:
        self.sent.append((session_id, payload))


class _LabelAcceptingManager:

    def set_session_label(self, session_id: str, new_name: str) -> bool:
        return True

    async def get_session_info(self, session_id: str | None = None):
        return None


@pytest.fixture()
def recording_app(monkeypatch):
    recorder = _RecordingConnectionManager()
    monkeypatch.setattr(rename_routes_mod, "connection_manager", recorder)

    app = FastAPI()
    app.state.session_manager = _LabelAcceptingManager()
    app.include_router(routes_mod.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: True

    yield TestClient(app, raise_server_exceptions=False), recorder


def test_a_successful_rename_broadcasts_session_renamed(recording_app) -> None:
    client, recorder = recording_app

    client.patch(
        "/api/v1/sessions/ses_live/name",
        json={"new_name": "Media Compression"},
    )

    assert len(recorder.sent) == 1, (
        "PATCH /sessions/{id}/name broadcast %d frames, expected exactly 1. "
        "Zero means session.renamed has no sender any more and every "
        "attached tab now shows a stale name until it reloads."
        % len(recorder.sent)
    )

    session_id, payload = recorder.sent[0]
    assert session_id == "ses_live"
    frame = json.loads(payload)
    assert frame["type"] == WSMessageType.SESSION_RENAMED.value
    assert frame["type"] == "session.renamed", (
        "the wire string changed. client/js/terminal.js dispatches on the "
        "literal 'session.renamed' and would silently stop handling it."
    )
    assert frame["session_id"] == "ses_live"
    assert frame["new_name"] == "Media Compression", (
        "the frame carries a different label than the one written, so tabs "
        "would update to the wrong name"
    )


def test_a_rejected_rename_broadcasts_nothing(recording_app) -> None:
    client, recorder = recording_app

    response = client.patch(
        "/api/v1/sessions/ses_live/name",
        json={"new_name": "has\na newline"},
    )

    assert response.status_code == 400, (
        "a control character in a label is supposed to be refused; if this "
        "changed, the assertion below is measuring the wrong path"
    )
    assert recorder.sent == [], (
        "a refused rename still broadcast session.renamed, so every tab "
        "would show a name the server did not store"
    )




class _RecordingHub(EventHub):

    def __init__(self) -> None:
        super().__init__()
        self.frames: list[dict] = []

    def publish(self, frame: dict) -> int:
        self.frames.append(frame)
        return super().publish(frame)


@pytest.fixture()
def hub_app(monkeypatch):
    recorder = _RecordingConnectionManager()
    monkeypatch.setattr(rename_routes_mod, "connection_manager", recorder)

    hub = _RecordingHub()
    app = FastAPI()
    app.state.session_manager = _LabelAcceptingManager()
    app.state.event_hub = hub
    app.include_router(routes_mod.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: True

    yield TestClient(app, raise_server_exceptions=False), hub


def test_the_notice_and_the_socket_frame_are_the_same_shape() -> None:
    notice = session_change_notice.build_rename_notice(
        session_id="ses_live", new_name="Media Compression"
    )
    on_the_socket = json.loads(
        SessionRenamedMessage(
            session_id="ses_live", new_name="Media Compression"
        ).model_dump_json()
    )

    assert notice == on_the_socket, (
        "the events-channel notice and the terminal-socket frame describe "
        "the same rename with different fields, so a client cannot keep "
        "one handler for both"
    )


def test_a_successful_rename_also_reaches_the_events_channel(hub_app) -> None:
    client, hub = hub_app
    registered = hub.register()

    client.patch(
        "/api/v1/sessions/ses_live/name",
        json={"new_name": "Media Compression"},
    )

    renames = [f for f in hub.frames if f.get("type") == WSMessageType.SESSION_RENAMED]
    assert len(renames) == 1, (
        "PATCH /sessions/{id}/name put %d rename notices on /ws/events, "
        "expected exactly 1. Zero means a browser showing this session's "
        "name without a terminal socket for it never hears about the "
        "rename." % len(renames)
    )
    assert renames[0]["session_id"] == "ses_live"
    assert renames[0]["new_name"] == "Media Compression"
    assert registered.stream.queued_items == 1, (
        "the notice was published but no connected client accepted it"
    )


def test_a_rejected_rename_puts_nothing_on_the_events_channel(hub_app) -> None:
    client, hub = hub_app

    response = client.patch(
        "/api/v1/sessions/ses_live/name",
        json={"new_name": "has\na newline"},
    )

    assert response.status_code == 400, (
        "a control character in a label is supposed to be refused; if this "
        "changed, the assertion below is measuring the wrong path"
    )
    assert [f for f in hub.frames if f.get("type") == WSMessageType.SESSION_RENAMED] == []
