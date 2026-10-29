
from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from starlette.websockets import WebSocketDisconnect

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_pause_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_pause_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.api.ws_receive import receive_messages  # noqa: E402
from src.api.ws_startup_paint import _CLEAR_AND_HOME  # noqa: E402
from src.api.ws_viewer_drain import _drain_viewer  # noqa: E402
from src.core import viewer_fanout  # noqa: E402
from src.core.federation.peer_terminal_proxy import up_text  # noqa: E402


class _Backend:
    def capture_visible_screen(self) -> bytes:
        return b"current screen"


class _Socket:

    def __init__(self, frames):
        self._frames = list(frames)
        self.sent = []
        backend = _Backend()
        registry = SimpleNamespace(get_backend=lambda sid: backend, current_backend=lambda: backend)
        self.app = SimpleNamespace(state=SimpleNamespace(services=SimpleNamespace(registry=registry)))
        self.scope = {}

    async def receive(self):
        while self._frames and callable(self._frames[0]):
            self._frames.pop(0)()
        if not self._frames:
            raise WebSocketDisconnect(1000)
        return {"text": json.dumps({"type": self._frames.pop(0)})}

    async def send_bytes(self, data):
        self.sent.append(data)

    async def send_text(self, data):
        self.sent.append(data)


async def _run(frames, stream):
    ws = _Socket(frames)
    with pytest.raises(WebSocketDisconnect):
        await asyncio.wait_for(receive_messages(ws, SimpleNamespace(), "s", stream), 2)
    stream.close()
    await asyncio.wait_for(_drain_viewer(ws, stream), 2)
    return ws


def _publish(stream, *chunks):
    for chunk in chunks:
        viewer_fanout.offer_pty(stream, base64.b64encode(chunk).decode())


@pytest.mark.asyncio
async def test_held_terminal_receives_no_bytes_and_resume_repaints():
    stream = viewer_fanout.new_viewer_stream("t", resync=True)
    ws = await _run(["pause", lambda: _publish(stream, b"unseen one", b"unseen two"), "resume"], stream)
    assert b"unseen one" not in ws.sent and b"unseen two" not in ws.sent, "a held terminal gets no pane bytes"
    assert ws.sent == [_CLEAR_AND_HOME + b"current screen"], "resume repaints the current screen, once"


@pytest.mark.asyncio
async def test_unheld_terminal_streams_and_a_resume_without_pause_repaints_nothing():
    stream = viewer_fanout.new_viewer_stream("t", resync=True)
    ws = await _run([lambda: _publish(stream, b"live"), "resume"], stream)
    assert ws.sent == [b"live"]


def test_pause_and_resume_pass_the_peer_proxy_stripped_of_extra_fields():
    assert json.loads(up_text('{"type": "pause", "x": 1}')) == {"type": "pause"}
    assert json.loads(up_text('{"type": "resume"}')) == {"type": "resume"}


def _patch_capture(monkeypatch, results, during=None):
    from src.api import ws_repaint
    answers = list(results)

    async def fake(websocket, session_id):
        if during is not None and len(answers) == len(results):
            during()
        return answers.pop(0)

    monkeypatch.setattr(ws_repaint, "capture_screen", fake)


@pytest.mark.asyncio
async def test_output_during_the_resume_capture_never_precedes_the_repaint_and_the_stale_capture_is_retaken(monkeypatch):
    stream = viewer_fanout.new_viewer_stream("t", resync=True)
    _patch_capture(monkeypatch, [(b"stale", "ok"), (b"fresh", "ok")], during=lambda: _publish(stream, b"printed mid-capture"))
    ws = await _run(["pause", "resume"], stream)
    assert ws.sent == [_CLEAR_AND_HOME + b"fresh"], "no live bytes ahead of the clear-and-home frame, and a capture that went stale is retaken"
    assert stream.paused is False


@pytest.mark.asyncio
@pytest.mark.parametrize("answer", [(None, "capture_failed"), (None, "nothing")])
async def test_a_failed_or_empty_resume_capture_falls_back_to_a_full_resync(monkeypatch, answer):
    stream = viewer_fanout.new_viewer_stream("t", resync=True)
    _patch_capture(monkeypatch, [answer] * 3)
    ws = await _run(["pause", "resume"], stream)
    assert stream.paused is False
    texts = [m for m in ws.sent if isinstance(m, str)]
    assert len(texts) == 1 and json.loads(texts[0])["type"] == "terminal.resync", "the viewer is told to resync"
    assert ws.sent[-1] == _CLEAR_AND_HOME + b"current screen", "and gets a fresh capture from the writer"
