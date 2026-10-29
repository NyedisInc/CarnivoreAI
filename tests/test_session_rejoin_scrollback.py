from __future__ import annotations

import base64
import os
import sys
import tempfile
import threading
from pathlib import Path
from unittest.mock import MagicMock

import pytest


os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_rj_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_rj_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from fastapi import FastAPI
from fastapi.testclient import TestClient

import src.api.routes as routes_mod
import src.api.session_rejoin_capture as rejoin_capture_mod
from src.api.auth import require_auth
from src.models import Session, SessionInfo, SessionStats, SessionStatus




def _build_session_info(session_id: str = "sess-1") -> SessionInfo:
    sess = Session(
        id=session_id,
        pty_pid=12345,
        working_dir="/tmp/rejoinproj",
        status=SessionStatus.RUNNING,
        tmux_session="rejoinproj",
    )
    return SessionInfo(
        session=sess,
        recent_logs=[],
        local_servers=[],
        stats=SessionStats(),
        session_backend="tmux",
        tmux_session="rejoinproj",
        agent_type=None,
        pinned_theme=None,
    )


def _build_app_with_capture(
    capture_return: bytes | None = b"",
    capture_raises: BaseException | None = None,
):
    sm = MagicMock()
    info = _build_session_info()

    async def fake_get_info(session_id=None):
        return info

    sm.get_session_info = fake_get_info

    if capture_raises is not None:
        def _raise(*a, **kw):
            raise capture_raises
        sm.capture_scrollback = MagicMock(side_effect=_raise)
    else:
        sm.capture_scrollback = MagicMock(return_value=capture_return)

    app = FastAPI()
    app.state.session_manager = sm
    app.include_router(routes_mod.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: True
    return app, sm, info




def test_get_session_without_flag_returns_no_scrollback():
    app, sm, _info = _build_app_with_capture(capture_return=b"should-not-be-used")
    client = TestClient(app)

    resp = client.get("/api/v1/sessions")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body.get("initial_scrollback_b64") is None
    sm.capture_scrollback.assert_not_called()


def test_get_session_with_flag_zero_does_not_populate():
    app, sm, _info = _build_app_with_capture(capture_return=b"hello")
    client = TestClient(app)

    resp = client.get("/api/v1/sessions?include_scrollback=0")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("initial_scrollback_b64") is None
    sm.capture_scrollback.assert_not_called()




def test_get_session_with_flag_returns_base64_scrollback():
    captured = b"hello\nworld\x1b[31mred\x1b[0m\n"
    app, sm, _info = _build_app_with_capture(capture_return=captured)
    client = TestClient(app)

    resp = client.get("/api/v1/sessions?include_scrollback=1")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    b64 = body.get("initial_scrollback_b64")
    assert isinstance(b64, str) and b64, "expected non-empty base64 string"
    assert base64.b64decode(b64) == captured

    sm.capture_scrollback.assert_called_once()
    kwargs = sm.capture_scrollback.call_args.kwargs
    assert kwargs.get("session_id") == "sess-1"
    assert isinstance(kwargs.get("lines"), int)


def test_get_session_with_flag_empty_capture_leaves_field_none():
    app, sm, _info = _build_app_with_capture(capture_return=b"")
    client = TestClient(app)

    resp = client.get("/api/v1/sessions?include_scrollback=1")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body.get("initial_scrollback_b64") is None
    sm.capture_scrollback.assert_called_once()




def test_get_session_with_flag_handles_capture_failure_gracefully(monkeypatch):
    app, sm, _info = _build_app_with_capture(
        capture_raises=RuntimeError("tmux capture-pane failed")
    )

    seen_events: list[tuple[str, dict]] = []

    def fake_warning(event, **kw):
        seen_events.append((event, kw))

    monkeypatch.setattr(rejoin_capture_mod.logger, "warning", fake_warning)

    client = TestClient(app)
    resp = client.get("/api/v1/sessions?include_scrollback=1")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("initial_scrollback_b64") is None
    sm.capture_scrollback.assert_called_once()

    events = [e for e, _kw in seen_events]
    assert "rejoin_scrollback_capture_failed" in events, (
        f"expected event 'rejoin_scrollback_capture_failed', got: {events!r}"
    )




def test_get_session_with_explicit_id_forwards_to_capture():
    app, sm, _info = _build_app_with_capture(capture_return=b"x")
    client = TestClient(app)

    resp = client.get(
        "/api/v1/sessions?session_id=sess-1&include_scrollback=1"
    )
    assert resp.status_code == 200, resp.text

    sm.capture_scrollback.assert_called_once()
    kwargs = sm.capture_scrollback.call_args.kwargs
    assert kwargs.get("session_id") == "sess-1"


def test_scrollback_lines_sets_the_capture_depth():
    app, sm, _info = _build_app_with_capture(capture_return=b"x")
    resp = TestClient(app).get(
        "/api/v1/sessions?session_id=sess-1&include_scrollback=1&scrollback_lines=7500"
    )
    assert resp.status_code == 200, resp.text
    assert sm.capture_scrollback.call_args.kwargs.get("lines") == 7500
    assert sm.capture_scrollback.call_args.kwargs.get("session_id") == "sess-1"


def test_scrollback_lines_is_bounded_and_integer_only():
    app, sm, _info = _build_app_with_capture(capture_return=b"x")
    client = TestClient(app)
    for bad in ("0", "-5", "50001", "abc", "1.5"):
        resp = client.get(
            f"/api/v1/sessions?session_id=sess-1&include_scrollback=1&scrollback_lines={bad}"
        )
        assert resp.status_code == 422, (bad, resp.status_code)
    sm.capture_scrollback.assert_not_called()
    edge = client.get(
        "/api/v1/sessions?session_id=sess-1&include_scrollback=1&scrollback_lines=50000"
    )
    assert edge.status_code == 200
    assert sm.capture_scrollback.call_args.kwargs.get("lines") == 50000




def _build_app_recording_threads(capture_return: bytes = b"history"):
    sm = MagicMock()
    info = _build_session_info()
    seen: list[tuple[str, int]] = []

    async def fake_get_info(session_id=None):
        seen.append(("loop", threading.get_ident()))
        return info

    def fake_resize(*a, **kw):
        seen.append(("resize", threading.get_ident()))

    def fake_capture(*a, **kw):
        seen.append(("capture", threading.get_ident()))
        return capture_return

    sm.get_session_info = fake_get_info
    sm.resize_terminal = MagicMock(side_effect=fake_resize)
    sm.capture_scrollback = MagicMock(side_effect=fake_capture)

    app = FastAPI()
    app.state.session_manager = sm
    app.include_router(routes_mod.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: True
    return app, sm, seen


def test_resize_and_capture_run_off_the_event_loop():
    app, _sm, seen = _build_app_recording_threads()
    client = TestClient(app)

    resp = client.get(
        "/api/v1/sessions?include_scrollback=1&cols=100&rows=40"
    )
    assert resp.status_code == 200, resp.text

    by_name = dict(seen)
    assert "loop" in by_name, "the async handler never ran"
    assert "resize" in by_name and "capture" in by_name, (
        f"a tmux call never happened: {seen!r}"
    )
    assert by_name["resize"] != by_name["loop"], (
        "resize_terminal ran on the event loop thread; a 20-150 ms tmux "
        "call there stalls every live terminal in the process"
    )
    assert by_name["capture"] != by_name["loop"], (
        "capture_scrollback ran on the event loop thread"
    )


def test_resize_happens_before_the_capture():
    app, _sm, seen = _build_app_recording_threads()
    client = TestClient(app)

    resp = client.get(
        "/api/v1/sessions?include_scrollback=1&cols=100&rows=40"
    )
    assert resp.status_code == 200, resp.text

    order = [name for name, _ident in seen if name != "loop"]
    assert order == ["resize", "capture"], (
        f"expected the resize to land before the capture, got {order!r}"
    )


def test_both_tmux_calls_share_one_thread():
    app, _sm, seen = _build_app_recording_threads()
    client = TestClient(app)
    client.get("/api/v1/sessions?include_scrollback=1&cols=100&rows=40")

    idents = {ident for name, ident in seen if name != "loop"}
    assert len(idents) == 1, f"the two tmux calls ran on {len(idents)} threads"


def test_no_cols_and_rows_skips_the_resize_but_still_captures():
    app, sm, seen = _build_app_recording_threads()
    client = TestClient(app)

    resp = client.get("/api/v1/sessions?include_scrollback=1")
    assert resp.status_code == 200, resp.text

    sm.resize_terminal.assert_not_called()
    assert [name for name, _i in seen if name != "loop"] == ["capture"]




def test_capture_carries_the_panes_own_cursor():
    app, sm, _seen = _build_app_recording_threads(capture_return=b"body")
    backend = sm._registry.get_backend.return_value
    backend.pane_cursor_position.return_value = (5, 2)

    resp = TestClient(app).get("/api/v1/sessions?include_scrollback=1")
    assert resp.status_code == 200, resp.text

    raw = base64.b64decode(resp.json()["initial_scrollback_b64"])
    assert raw == b"body\x1b[3;6H", raw


def test_an_unreadable_cursor_appends_nothing():
    app, sm, _seen = _build_app_recording_threads(capture_return=b"body")
    sm._registry.get_backend.return_value.pane_cursor_position.return_value = None

    resp = TestClient(app).get("/api/v1/sessions?include_scrollback=1")
    raw = base64.b64decode(resp.json()["initial_scrollback_b64"])
    assert raw == b"body", raw


def test_an_empty_capture_is_still_null_even_with_a_live_cursor():
    app, sm, _seen = _build_app_recording_threads(capture_return=b"")
    sm._registry.get_backend.return_value.pane_cursor_position.return_value = (1, 1)

    resp = TestClient(app).get("/api/v1/sessions?include_scrollback=1")
    assert resp.status_code == 200, resp.text
    assert resp.json().get("initial_scrollback_b64") is None


def test_a_backend_that_cannot_report_a_cursor_is_not_a_failure():
    app, sm, _seen = _build_app_recording_threads(capture_return=b"body")
    sm._registry.get_backend.return_value = object()

    resp = TestClient(app).get("/api/v1/sessions?include_scrollback=1")
    assert resp.status_code == 200, resp.text
    assert base64.b64decode(resp.json()["initial_scrollback_b64"]) == b"body"
