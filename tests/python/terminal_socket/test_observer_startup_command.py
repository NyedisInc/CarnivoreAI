
from __future__ import annotations

from tests.test_terminal_observer_socket import (  # noqa: F401
    SESSION_ID, PRIMARY_COLS, PRIMARY_ROWS, _build_app, _connect, _drive_handshake, _read_until_paint, _FakeLogMonitor,
    _mint_token, patched_auth_config)


class _Flushing:

    def __init__(self, inner):
        self._inner, self.flushed = inner, []

    def __getattr__(self, name):
        return getattr(self._inner, name)

    async def flush_pending_login(self, sid):
        self.flushed.append(("login", sid))
        return "none"


def _flushed_by(interactive: str | None, observer: str | None = "1"):
    from fastapi.testclient import TestClient

    app = _build_app(_FakeLogMonitor())
    app.state.session_manager = manager = _Flushing(app.state.session_manager)
    with _connect(TestClient(app), observer, interactive) as ws:
        if observer:
            _read_until_paint(ws)
        else:
            _drive_handshake(ws, cols=PRIMARY_COLS, rows=PRIMARY_ROWS)
    return manager.flushed


def test_read_only_observer_never_flushes_the_pending_command():
    assert _flushed_by(None) == [], "a read-only observer typed the pane's pending command"


def test_interactive_observer_flushes_the_pending_command():
    assert _flushed_by("1") == [("login", SESSION_ID)]


def test_primary_flushes_the_pending_command():
    assert _flushed_by(None, observer=None) == [("login", SESSION_ID)]
