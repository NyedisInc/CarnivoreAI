
from __future__ import annotations

import pathlib
import re

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from relay import app as relay_app
from relay import redaction
from relay.app import create_app
from relay.protocol import PUBLISH_SUBPROTOCOL
from relay.publish_socket import UNAVAILABLE_CLOSE_CODE
from relay.redaction import RedactorUnavailableError, build_redactor_factory
from tests.test_relay_sockets import PUBLISH_TOKEN, build_settings

RELAY_DIR = pathlib.Path(__file__).resolve().parents[1] / "relay"

_APP_IMPORT_RE = re.compile(
    r"^\s*(?:from|import)\s+(src(?:\.[A-Za-z_][A-Za-z0-9_]*)+)", re.MULTILINE
)


def relay_sources() -> list:
    return sorted(RELAY_DIR.glob("*.py"))


def test_the_relay_reaches_for_exactly_one_application_module():
    files = relay_sources()
    assert len(files) >= 8, f"relay package looks empty: {[f.name for f in files]}"
    found = set()
    for path in files:
        found.update(_APP_IMPORT_RE.findall(path.read_text()))
    assert found == {"src.core.stream_redactor"}, found


def test_no_detector_pattern_is_vendored_into_the_relay():
    markers = ("AKIA", "xox", "BEGIN RSA", "AIza")
    for path in relay_sources():
        body = path.read_text()
        for marker in markers:
            assert marker not in body, f"{path.name} carries {marker!r}"


def test_the_factory_builds_a_fresh_redactor_every_call(monkeypatch):

    class FakeRedactor:
        def __init__(self, *, tail_bytes: int, max_buffer: int) -> None:
            self.tail_bytes = tail_bytes
            self.max_buffer = max_buffer

    monkeypatch.setattr(redaction, "_StreamRedactor", FakeRedactor)
    factory = build_redactor_factory(tail_bytes=2048, max_buffer=65536)
    first, second = factory(), factory()
    assert first is not second
    assert first.tail_bytes == 2048
    assert first.max_buffer == 65536


def test_the_factory_refuses_when_the_shared_module_is_absent(monkeypatch):
    monkeypatch.setattr(redaction, "_StreamRedactor", None)
    with pytest.raises(RedactorUnavailableError):
        build_redactor_factory(tail_bytes=2048, max_buffer=65536)


def test_a_relay_that_cannot_scrub_refuses_every_publisher(monkeypatch):
    monkeypatch.setattr(relay_app, "redaction_available", lambda: False)
    app = create_app(build_settings())
    with TestClient(app) as client:
        assert client.get("/healthz").json()["redaction"] == "unavailable"
        with pytest.raises(WebSocketDisconnect) as refused:
            with client.websocket_connect(
                "/publish",
                headers={"Authorization": f"Bearer {PUBLISH_TOKEN}"},
                subprotocols=[PUBLISH_SUBPROTOCOL],
            ):
                pass
    assert refused.value.code == UNAVAILABLE_CLOSE_CODE


def test_healthz_still_answers_when_the_relay_cannot_scrub(monkeypatch):
    monkeypatch.setattr(relay_app, "redaction_available", lambda: False)
    app = create_app(build_settings())
    with TestClient(app) as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["redaction"] == "unavailable"


def test_an_unauthenticated_publisher_is_refused_before_the_redactor_check():
    import relay.app as module

    original = module.redaction_available
    module.redaction_available = lambda: False
    try:
        app = create_app(build_settings())
        with TestClient(app) as client:
            with pytest.raises(WebSocketDisconnect) as refused:
                with client.websocket_connect(
                    "/publish",
                    headers={"Authorization": "Bearer wrong"},
                    subprotocols=[PUBLISH_SUBPROTOCOL],
                ):
                    pass
    finally:
        module.redaction_available = original
    assert refused.value.code == 4401
    assert refused.value.code != UNAVAILABLE_CLOSE_CODE
