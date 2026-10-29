from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.api.ws_receive import receive_messages  # noqa: E402
from src.core.session_manager import SessionManager  # noqa: E402
from src.core.sessions.registry import SessionRegistry  # noqa: E402
from src.core.tmux_backend import TmuxBackend  # noqa: E402
from src.models import Session, SessionStatus  # noqa: E402


class _StopLoop(Exception):
    pass


class FakeWebSocket:

    def __init__(self, frames: list[dict]) -> None:
        self._frames = list(frames)
        self.sent: list[str] = []

    async def receive(self) -> dict:
        if not self._frames:
            raise _StopLoop()
        return self._frames.pop(0)

    async def send_text(self, text: str) -> None:
        self.sent.append(text)


def make_backend(recorder: list[list[str]]) -> TmuxBackend:
    backend = TmuxBackend(
        session_id="sess-resize-1",
        working_dir=Path("/tmp"),
        session_name="cloude_resize_test",
    )

    def _fake_run(*args: str, stdin_bytes=None, check: bool = True):
        recorder.append(list(args))
        return 0, b"", b""

    backend._run_tmux_sync = _fake_run  # type: ignore[assignment]
    return backend


def make_session_manager(backend: TmuxBackend, session_id: str):
    registry = SessionRegistry(log_cap=lambda: 1000)
    registry.register(
        Session(
            id=session_id,
            working_dir="/tmp",
            status=SessionStatus.RUNNING,
            tmux_session=f"cloude_{session_id}",
        ),
        backend,
    )
    holder = SimpleNamespace(_registry=registry)
    holder.resize_terminal = SessionManager.resize_terminal.__get__(holder)
    return holder


@pytest.mark.asyncio
async def test_pty_resize_frame_issues_tmux_resize_window():
    calls: list[list[str]] = []
    backend = make_backend(calls)
    manager = make_session_manager(backend, "sess-resize-1")

    ws = FakeWebSocket([
        {"text": json.dumps({"type": "pty_resize", "cols": 42, "rows": 48})},
    ])

    with pytest.raises(_StopLoop):
        await receive_messages(ws, manager, session_id="sess-resize-1")

    resizes = [c for c in calls if c and c[0] == "resize-window"]
    assert len(resizes) == 1, f"expected one resize-window, got {calls}"
    argv = resizes[0]
    assert argv[argv.index("-x") + 1] == "42"
    assert argv[argv.index("-y") + 1] == "48"
    assert argv[argv.index("-t") + 1] == "cloude_resize_test"


@pytest.mark.asyncio
async def test_phone_sized_geometry_reaches_tmux_verbatim():
    calls: list[list[str]] = []
    backend = make_backend(calls)
    manager = make_session_manager(backend, "sess-resize-1")

    ws = FakeWebSocket([
        {"text": json.dumps({"type": "pty_resize", "cols": 42, "rows": 16})},
    ])
    with pytest.raises(_StopLoop):
        await receive_messages(ws, manager, session_id="sess-resize-1")

    argv = [c for c in calls if c and c[0] == "resize-window"][0]
    assert argv[argv.index("-x") + 1] == "42"
    assert argv[argv.index("-y") + 1] == "16"


@pytest.mark.asyncio
async def test_successive_resizes_each_reach_tmux():
    calls: list[list[str]] = []
    backend = make_backend(calls)
    manager = make_session_manager(backend, "sess-resize-1")

    ws = FakeWebSocket([
        {"text": json.dumps({"type": "pty_resize", "cols": 95, "rows": 16})},
        {"text": json.dumps({"type": "pty_resize", "cols": 42, "rows": 21})},
    ])
    with pytest.raises(_StopLoop):
        await receive_messages(ws, manager, session_id="sess-resize-1")

    resizes = [c for c in calls if c and c[0] == "resize-window"]
    assert len(resizes) == 2
    assert [r[r.index("-x") + 1] for r in resizes] == ["95", "42"]
    assert [r[r.index("-y") + 1] for r in resizes] == ["16", "21"]


@pytest.mark.asyncio
async def test_resize_for_a_dead_session_is_a_no_op_not_a_crash():
    calls: list[list[str]] = []
    backend = make_backend(calls)
    manager = make_session_manager(backend, "sess-resize-1")
    manager._registry.backends = {}

    ws = FakeWebSocket([
        {"text": json.dumps({"type": "pty_resize", "cols": 42, "rows": 48})},
    ])
    with pytest.raises(_StopLoop):
        await receive_messages(ws, manager, session_id="sess-resize-1")

    assert calls == []
    assert ws.sent == []
