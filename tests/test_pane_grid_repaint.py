
from __future__ import annotations

import asyncio
import base64
import inspect
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import List

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_repaint_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_repaint_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.api import ws_repaint  # noqa: E402
from src.api.resize_negotiation import apply_negotiated_resize  # noqa: E402
from src.api.ws_startup_paint import _CLEAR_AND_HOME  # noqa: E402
from src.api.ws_viewer_drain import _drain_viewer  # noqa: E402
from src.core import viewer_fanout  # noqa: E402


class Recorder:

    def __init__(self) -> None:
        self.resizes: List[tuple] = []
        self.frames: List[dict] = []

    def resize_terminal(self, cols: int, rows: int, session_id: str) -> None:
        self.resizes.append((cols, rows))

    async def broadcast_to_session(self, session_id: str, message: str) -> None:
        self.frames.append(json.loads(message))


def _manager() -> SimpleNamespace:
    rec = Recorder()
    return SimpleNamespace(resize_terminal=rec.resize_terminal, rec=rec)




@pytest.mark.asyncio
async def test_a_pane_measured_off_the_negotiated_size_is_put_back():
    sm = _manager()
    await apply_negotiated_resize(sm, "s", "small", 160, 47, sm.rec)
    await apply_negotiated_resize(sm, "s", "big", 177, 60, sm.rec)
    assert sm.rec.resizes == [(160, 47)]
    outcome = await apply_negotiated_resize(
        sm, "s", "big", 177, 60, sm.rec, known_pane_size=(177, 60))
    assert sm.rec.resizes == [(160, 47), (160, 47)], "the bypass must be undone"
    assert outcome.issued is True
    assert sm.rec.frames[-1]["cols"] == 160 and sm.rec.frames[-1]["clients"] == 2


@pytest.mark.asyncio
async def test_a_pane_already_at_the_negotiated_size_is_left_alone():
    sm = _manager()
    await apply_negotiated_resize(sm, "s", "small", 160, 47, sm.rec)
    await apply_negotiated_resize(sm, "s", "big", 177, 60, sm.rec)
    outcome = await apply_negotiated_resize(
        sm, "s", "big", 177, 60, sm.rec, known_pane_size=(160, 47))
    assert sm.rec.resizes == [(160, 47)]
    assert outcome.issued is False


@pytest.mark.asyncio
async def test_a_hidden_handshake_never_moves_the_pane():
    sm = _manager()
    await apply_negotiated_resize(sm, "s", "small", 160, 47, sm.rec)
    await apply_negotiated_resize(sm, "s", "big", 177, 60, sm.rec, hidden=True)
    await apply_negotiated_resize(
        sm, "s", "big", 177, 60, sm.rec, known_pane_size=(177, 60), hidden=True)
    assert sm.rec.resizes == [(160, 47)]




class FakeBackend:

    def __init__(self, screen: bytes) -> None:
        self.screen = screen
        self.writes: List[str] = []

    def capture_visible_screen(self) -> bytes:
        return self.screen

    def write(self, data: str) -> None:
        self.writes.append(data)


def _socket(backend) -> SimpleNamespace:
    registry = SimpleNamespace(get_backend=lambda sid: backend,
                               current_backend=lambda: backend)
    sent: List[tuple] = []

    async def send_bytes(data: bytes) -> None:
        sent.append(("bytes", data))

    async def send_text(data: str) -> None:
        sent.append(("text", data))

    app = SimpleNamespace(state=SimpleNamespace(services=SimpleNamespace(registry=registry)))
    return SimpleNamespace(app=app, sent=sent, send_bytes=send_bytes, send_text=send_text)


@pytest.mark.asyncio
async def test_repaint_queues_the_capture_behind_earlier_output():
    backend = FakeBackend(b"row one\r\nrow two")
    ws = _socket(backend)
    stream = viewer_fanout.new_viewer_stream("t")
    viewer_fanout.offer_pty(stream, base64.b64encode(b"earlier").decode())
    assert await ws_repaint.repaint(ws, "s", stream) == "queued"
    stream.close()
    await asyncio.wait_for(_drain_viewer(ws, stream), timeout=2)
    assert [d for kind, d in ws.sent] == [b"earlier", _CLEAR_AND_HOME + b"row one\r\nrow two"]
    assert backend.writes == [], "nothing is ever written into the pane"


@pytest.mark.asyncio
async def test_an_empty_capture_clears_nothing():
    ws = _socket(FakeBackend(b""))
    stream = viewer_fanout.new_viewer_stream("t")
    assert await ws_repaint.repaint(ws, "s", stream) == "nothing"
    assert stream.queued_items == 0


@pytest.mark.asyncio
async def test_repaint_without_a_backend_or_stream_sends_nothing():
    ws = _socket(None)
    stream = viewer_fanout.new_viewer_stream("t")
    assert await ws_repaint.repaint(ws, "s", stream) == "no_backend"
    assert stream.queued_items == 0
    assert await ws_repaint.repaint(_socket(FakeBackend(b"x")), "s", None) == "no_stream"


def test_the_paint_skips_pattern_detection_and_the_module_never_sends():
    drain_src = inspect.getsource(_drain_viewer)
    paint_at = drain_src.index("FRAME_PAINT")
    detect_at = drain_src.index("_detect_patterns")
    assert paint_at < detect_at
    assert "websocket.send" not in inspect.getsource(ws_repaint)


def test_the_read_loop_routes_repaint():
    from src.api import ws_receive

    src = inspect.getsource(ws_receive.receive_messages)
    assert "WSMessageType.REPAINT" in src
    assert "ws_repaint.repaint(websocket, session_id, stream)" in src
