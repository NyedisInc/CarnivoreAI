
from __future__ import annotations

import asyncio
import logging
import secrets
import time
from types import SimpleNamespace

import pytest
import structlog

from src.core.log_monitor import LogMonitor

from tests.test_ws_subprotocol_auth import (  # noqa: F401
    _mint_token,
    patched_auth_config,
)
from tests.test_ws_handshake_paint import _drive_handshake, _FakeLogMonitor
from tests.test_terminal_observer_socket import SESSION_ID, _build_app
from tests.test_session_registry_live import _session, manager  # noqa: F401

UNDECODABLE = b"\xfe"


def _canary() -> str:
    return f"CANARY-{secrets.token_hex(4)}"


def _needles(canary: str) -> list[str]:
    raw = canary.encode()
    return [canary, raw.hex(), raw.hex().upper()]


@pytest.fixture
def every_log_line(caplog):
    old_wrapper = structlog.get_config()["wrapper_class"]
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(logging.DEBUG)
    )
    caplog.set_level(logging.DEBUG)
    try:
        with structlog.testing.capture_logs() as entries:
            yield entries, caplog
    finally:
        structlog.configure(wrapper_class=old_wrapper)


def _leaks(entries: list, caplog, needles: list[str]) -> list[str]:
    found = [
        str(entry.get("event")) for entry in entries
        if any(n in repr(entry) for n in needles)
    ]
    found += [
        f"stdlib:{record.name}" for record in caplog.records
        if any(n in record.getMessage() or n in repr(record.args)
               for n in needles)
    ]
    return found


def _events(entries: list, name: str) -> list[dict]:
    return [entry for entry in entries if entry.get("event") == name]


def _wait_for(predicate, what: str, budget: float = 5.0) -> None:
    deadline = time.monotonic() + budget
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError(f"never observed: {what}")
        time.sleep(0.02)


class _PatternMonitor(LogMonitor):

    def __init__(self) -> None:
        super().__init__(session_manager=None)

    subscribe = _FakeLogMonitor.subscribe
    unsubscribe = _FakeLogMonitor.unsubscribe


def test_terminal_socket_logs_no_input_and_no_output_text(every_log_line):
    from fastapi.testclient import TestClient

    entries, caplog = every_log_line
    canary = _canary()
    app = _build_app(_PatternMonitor())
    manager_ = app.state.session_manager
    registry = app.state.services.registry
    client = TestClient(app)

    with client.websocket_connect(
        f"/ws/terminal?session_id={SESSION_ID}",
        subprotocols=["cloude.jwt.v1", _mint_token()],
    ) as ws:
        assert _drive_handshake(ws) is not None, "the primary never painted"
        ws.send_bytes(canary.encode())
        ws.send_text(f"{canary} is not json")
        ws.send_bytes(UNDECODABLE)
        registry.publish(SESSION_ID, f"Wrote to: {canary}\r\n".encode())
        for _ in range(40):
            frame = ws.receive()
            if canary.encode() in (frame.get("bytes") or b""):
                break
        else:
            raise AssertionError("the pane output never reached the viewer")
        _wait_for(lambda: canary in manager_.inputs, "the input reached the pane")
        _wait_for(lambda: _events(entries, "invalid_json_received"),
                  "the non-JSON frame was logged")
        _wait_for(lambda: any(event.get("length") == len(UNDECODABLE)
                              for event in _events(entries, "input_failed")),
                  "the undecodable frame length was logged")

    typed = _events(entries, "pty_input_received")
    assert len(canary) in [e.get("data_len") for e in typed], typed
    matched = _events(entries, "pattern_detected_in_output")
    assert "file_created" in [e.get("pattern") for e in matched], matched

    leaks = _leaks(entries, caplog, _needles(canary) + ["0xfe"])
    assert leaks == [], f"input or output text reached the log via {leaks}"

    assert _events(entries, "invalid_json_received")[0]["length"] == len(
        f"{canary} is not json")
    assert len(UNDECODABLE) in [event["length"] for event in _events(entries, "input_failed")]
    assert isinstance(matched[0].get("length"), int), matched


def test_command_route_logs_only_the_length(manager, every_log_line, monkeypatch):  # noqa: F811
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.api.auth import require_auth
    from src.api.session_input_routes import router

    class _Backend:
        tmux_session = "cloude_ses_canary"

        def __init__(self) -> None:
            self.written: list[bytes] = []

        async def write(self, data: bytes) -> None:
            self.written.append(data)

    entries, caplog = every_log_line
    canary = _canary()
    backend = _Backend()
    manager._registry.register(_session("ses_canary"), backend)
    app = FastAPI()
    app.state.session_manager = manager
    app.state.services = SimpleNamespace(registry=manager._registry)
    from src.core.approvals import dialog_gate

    async def _clear(_app, _session_id):
        return dialog_gate.CLEAR

    monkeypatch.setattr(dialog_gate, "dialog_verdict", _clear)
    app.dependency_overrides[require_auth] = lambda: True
    app.include_router(router)

    response = TestClient(app).post("/sessions/command", json={"command": canary})

    assert response.status_code == 200, response.text
    assert backend.written == [canary.encode() + b"\n"]
    names = ("api_send_command", "sending_command")
    assert [len(_events(entries, n)) for n in names] == [1, 1], entries
    leaks = _leaks(entries, caplog, _needles(canary))
    assert leaks == [], f"the command reached the log via {leaks}"
    for name in names:
        assert _events(entries, name)[0]["length"] == len(canary), name


@pytest.mark.real_tmux
def test_a_failed_tmux_write_logs_no_keystrokes(tmp_path, every_log_line):
    from src.core.tmux_backend import TmuxBackend
    from tests.socket_guard import TEST_SOCKET_NAME

    entries, caplog = every_log_line
    canary = _canary()
    backend = TmuxBackend(
        "ses_canary", tmp_path, socket_name=TEST_SOCKET_NAME,
        session_name=f"cloude_canary_absent_{secrets.token_hex(4)}",
    )
    backend._running = True
    plain = canary.encode()
    keyed = b"\x1b" + plain

    for payload, route in ((plain, "send-keys -l"), (keyed, "send-keys -H")):
        with pytest.raises(RuntimeError, match=route):
            asyncio.run(backend.write(payload))

    hex_pairs = ", ".join(repr(f"{b:02x}") for b in keyed)
    leaks = _leaks(entries, caplog, _needles(canary) + [hex_pairs])
    assert leaks == [], f"the keystrokes reached the log via {leaks}"
