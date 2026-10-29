import asyncio
import base64
import json
from pathlib import Path
from types import SimpleNamespace

from src.api.ws_viewer_drain import _drain_viewer
from src.core import viewer_fanout
from src.core.bounded_stream import OFFER_ACCEPTED, OFFER_OVERFLOWED

CLEAR_AND_HOME = b"\x1b[H\x1b[2J"
BOUND = viewer_fanout.MAX_VIEWER_QUEUE_CHUNKS


def _chunk(i: int) -> str:
    return base64.b64encode(f"c{i:04d}".encode()).decode()


class _Backend:

    def __init__(self, screen=b"SCREEN", error=None):
        self.screen, self.error, self.captures = screen, error, 0

    def capture_visible_screen(self):
        self.captures += 1
        if self.error is not None:
            raise self.error
        return self.screen


class _Socket:

    def __init__(self, backend):
        registry = SimpleNamespace(get_backend=lambda sid: backend,
                                   current_backend=lambda: backend)
        self.app = SimpleNamespace(state=SimpleNamespace(
            services=SimpleNamespace(registry=registry)))
        self.sent, self.closed_with = [], []

    async def send_text(self, data):
        self.sent.append(("text", data))

    async def send_bytes(self, data):
        self.sent.append(("bytes", data))

    async def close(self, *args, **kwargs):
        self.closed_with.append((args, kwargs))


async def _queued_frames(stream):
    out = []
    while stream.queued_items:
        out.append(await asyncio.wait_for(stream.get(), timeout=1))
    return out


def test_resync_stream_absorbs_a_flood_and_keeps_text():
    async def go():
        stream = viewer_fanout.new_viewer_stream("t", resync=True)
        assert viewer_fanout.offer_text(stream, '{"type":"toast"}') == OFFER_ACCEPTED
        outcomes = {viewer_fanout.offer_pty(stream, _chunk(i)) for i in range(BOUND + 44)}
        assert outcomes == {OFFER_ACCEPTED}
        assert not stream.overflowed and not stream.closed
        assert stream.queued_items <= BOUND
        frames = await _queued_frames(stream)
        assert frames[0] == viewer_fanout.ViewerFrame(viewer_fanout.FRAME_TEXT, '{"type":"toast"}')
        markers = [f for f in frames if f.kind == viewer_fanout.FRAME_RESYNC]
        assert len(markers) == 1 and frames.index(markers[0]) == 1
        body = json.loads(markers[0].payload)
        assert body["type"] == "terminal.resync"
        assert body["dropped_chunks"] > 0 and body["dropped_bytes"] > 0
    asyncio.run(go())


def test_writer_sends_text_then_resync_then_capture_then_later_chunks_in_order():
    async def go():
        backend = _Backend()
        ws = _Socket(backend)
        stream = viewer_fanout.new_viewer_stream("t", resync=True)
        viewer_fanout.offer_text(stream, '{"type":"toast"}')
        for i in range(BOUND + 44):
            assert viewer_fanout.offer_pty(stream, _chunk(i)) == OFFER_ACCEPTED
        stream.close()
        await asyncio.wait_for(_drain_viewer(ws, stream, None, "ses_1"), timeout=5)
        return ws, backend, stream
    ws, backend, stream = asyncio.run(go())
    assert [kind for kind, _ in ws.sent[:3]] == ["text", "text", "bytes"]
    assert ws.sent[0][1] == '{"type":"toast"}'
    marker = json.loads(ws.sent[1][1])
    assert marker["type"] == "terminal.resync" and marker["dropped_chunks"] > 0
    assert ws.sent[2][1] == CLEAR_AND_HOME + b"SCREEN"
    later = [data for kind, data in ws.sent[3:] if kind == "bytes"]
    numbers = [int(c[1:]) for c in later]
    assert marker["dropped_chunks"] == BOUND - 1
    assert numbers == list(range(BOUND - 1, BOUND + 44))
    assert len(later) == len(ws.sent) - 3
    assert backend.captures == 1
    assert ws.closed_with == [] and not stream.overflowed


def test_failed_capture_falls_back_to_the_4429_close():
    for backend in (_Backend(error=RuntimeError("tmux gone")), _Backend(screen=b"")):
        async def go():
            ws = _Socket(backend)
            stream = viewer_fanout.new_viewer_stream("t", resync=True)
            for i in range(BOUND + 5):
                viewer_fanout.offer_pty(stream, _chunk(i))
            await asyncio.wait_for(_drain_viewer(ws, stream, None, "ses_1"), timeout=5)
            return ws, stream
        ws, stream = asyncio.run(go())
        assert stream.overflowed and stream.closed
        assert all(data != CLEAR_AND_HOME + b"SCREEN" for _, data in ws.sent)
        assert not any(kind == "text" and "terminal.resync" in data for kind, data in ws.sent)


def test_resync_rate_is_bounded_per_viewer():
    async def go():
        stream = viewer_fanout.new_viewer_stream("t", resync=True, min_resync_interval=0.05)
        for i in range(BOUND * 3):
            assert viewer_fanout.offer_pty(stream, _chunk(i)) == OFFER_ACCEPTED
        assert stream.resyncs == 1 and stream.queued_items <= BOUND
        await asyncio.sleep(0.12)
        assert stream.resyncs == 2 and not stream.closed
        frames = await _queued_frames(stream)
        assert sum(f.kind == viewer_fanout.FRAME_RESYNC for f in frames) == 1
        loop, start = asyncio.get_running_loop(), asyncio.get_running_loop().time()
        n = 0
        while loop.time() - start < 0.3:
            viewer_fanout.offer_pty(stream, _chunk(n % 9999))
            n += 1
            if n % 50 == 0:
                await asyncio.sleep(0)
        assert stream.queued_items <= BOUND and not stream.closed
        assert 2 < stream.resyncs <= 2 + int(0.3 / 0.05) + 2
        stream.close()
    asyncio.run(go())


def test_no_pane_output_follows_a_cut_before_the_marker():
    async def go():
        stream = viewer_fanout.ResyncViewerStream(max_items=4, max_bytes=10_000, label="t", min_resync_interval=0.1)
        for i in range(5):
            viewer_fanout.offer_pty(stream, _chunk(i))
        first = await _queued_frames(stream)
        assert first[0].kind == viewer_fanout.FRAME_RESYNC
        viewer_fanout.offer_text(stream, json.dumps({"type": "terminal.size", "cols": 80, "rows": 24}))
        for i in range(10, 16):
            assert viewer_fanout.offer_pty(stream, _chunk(i)) == OFFER_ACCEPTED
        assert viewer_fanout.offer_paint(stream, base64.b64encode(b"SCREEN").decode()) == OFFER_ACCEPTED
        gap = await _queued_frames(stream)
        assert [f.kind for f in gap] == [viewer_fanout.FRAME_TEXT], "only the text frame is queued while the resync is deferred"
        await asyncio.sleep(0.15)
        after = await _queued_frames(stream)
        assert [f.kind for f in after][0] == viewer_fanout.FRAME_RESYNC, "the marker is the first stale-kind frame the writer gets"
        owed = json.loads(after[0].payload)
        assert owed["dropped_chunks"] >= 7, owed
        viewer_fanout.offer_pty(stream, _chunk(99))
        assert [f.kind for f in await _queued_frames(stream)] == [viewer_fanout.FRAME_PTY], "output flows again after the marker"
        assert not stream.closed
        stream.close()
    asyncio.run(go())


def test_default_stream_still_overflows_and_closes():
    stream = viewer_fanout.new_viewer_stream("t")
    outcomes = [viewer_fanout.offer_pty(stream, _chunk(i)) for i in range(BOUND + 1)]
    assert outcomes[-1] == OFFER_OVERFLOWED
    assert stream.overflowed and stream.closed


def test_terminal_endpoint_opts_in():
    src = (Path(__file__).resolve().parents[3] / "src" / "api" / "websocket.py").read_text()
    assert "registry.subscribe(target_sid, resync=True)" in src
