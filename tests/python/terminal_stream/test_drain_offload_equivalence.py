import asyncio
from types import SimpleNamespace

from src.api.ws_viewer_drain import _drain_viewer
from src.core import viewer_fanout
from src.core.log_monitor import LogMonitor
from src.core.session_output import tap as output_tap

LINES = [
    "plain line", "Server listening on port 8123", "see http://localhost:3000/ now",
    "error: it broke", "WARNING: careful", "build complete", "tests passed", "",
    "Created file: /tmp/x.txt", "dev server running at http://127.0.0.1:5173", "xxxx " * 20,
    "visit https://example.dev:8080/a", "unicode ✦ 15.3k tokens 31% left",
]


def _chunks():
    blob = ("\n".join(LINES) + "\n") * 40
    data = blob.encode()
    sizes, i, out, k = [7, 61, 300, 1024, 5, 4096], 0, [], 0
    while i < len(data):
        n = sizes[k % len(sizes)]
        out.append(data[i:i + n]); i += n; k += 1
    return out


def _reference(chunks):
    mon = LogMonitor(None); seen = []
    for name in mon.pattern_detector.PATTERNS:
        mon.register_pattern_callback(name, lambda m: seen.append((m.pattern_name, m.matched_text, m.groups, m.line_number)))
    for c in chunks:
        for i, line in enumerate(c.decode("utf-8", errors="replace").split("\n")):
            if line.strip():
                mon.pattern_detector.detect_patterns(line, i)
    return seen


def _offloaded(chunks, monitor_cls=LogMonitor):
    mon = monitor_cls(None); seen = []; sent = []
    for name in mon.pattern_detector.PATTERNS:
        mon.register_pattern_callback(name, lambda m: seen.append((m.pattern_name, m.matched_text, m.groups, m.line_number)))

    async def send_bytes(b):
        sent.append(b)
    ws = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(services=None)), send_bytes=send_bytes)
    stream = viewer_fanout.new_viewer_stream("t")

    async def go():
        await mon.start_monitoring()
        try:
            for c in chunks:
                viewer_fanout.offer_pty(stream, c)
                output_tap.TAP.emit("ses_1", c)
            stream.close()
            await asyncio.wait_for(_drain_viewer(ws, stream, mon), timeout=20)
        finally:
            await mon.stop_monitoring()
    asyncio.run(go())
    return seen, sent


def test_offload_matches_reference_and_bytes_pass_through():
    chunks = _chunks()
    ref = _reference(chunks)
    assert len(ref) > 100
    seen, sent = _offloaded(chunks)
    assert seen == ref
    assert b"".join(sent) == b"".join(chunks)


def test_check_goes_red_when_a_pattern_is_dropped():
    class Dropping(LogMonitor):
        def scan_chunk(self, content):
            return [m for m in super().scan_chunk(content) if m.pattern_name != "error"]
    chunks = _chunks()
    seen, _ = _offloaded(chunks, Dropping)
    assert seen != _reference(chunks)
