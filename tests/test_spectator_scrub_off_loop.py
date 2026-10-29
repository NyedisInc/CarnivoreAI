
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_scrub_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_scrub_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

import asyncio
import base64
import threading
import time
from typing import List

import pytest

# ruff: noqa: E402
from src.core import relay_publisher, viewer_fanout
from src.core.spectator_redaction import build_scrubber

SCAN_SECONDS = 0.25


class _SlowRedactor:

    def __init__(self, fail: bool = False) -> None:
        self._lock = threading.Lock()
        self._fail = fail
        self.active = 0
        self.max_active = 0
        self.fed: List[str] = []

    def feed(self, chunk: str) -> str:
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            time.sleep(SCAN_SECONDS)
            if self._fail:
                raise RuntimeError("scan failed")
            self.fed.append(chunk)
            return chunk
        finally:
            with self._lock:
                self.active -= 1

    def flush(self) -> str:
        return ""

    @property
    def stats(self):
        return type("S", (), {"chunks_in": len(self.fed), "findings": 0,
                              "detectors": ()})()


async def _heartbeat(gaps: List[float], stop: asyncio.Event) -> None:
    last = time.perf_counter()
    while not stop.is_set():
        await asyncio.sleep(0.01)
        now = time.perf_counter()
        gaps.append(now - last)
        last = now


def _offer(stream, text: str) -> None:
    viewer_fanout.offer_pty(stream, base64.b64encode(text.encode()).decode())


@pytest.mark.asyncio
async def test_a_cancelled_pump_waits_for_the_scan_in_flight() -> None:
    redactor = _SlowRedactor()
    scrubber = build_scrubber(label="lnk", factory=lambda: redactor)
    stream = viewer_fanout.new_viewer_stream("t")
    outbox = viewer_fanout.new_viewer_stream("out")
    pump = asyncio.create_task(relay_publisher._pump("lnk", stream, scrubber, outbox, lambda: None, asyncio.Event()))
    _offer(stream, "x")
    await asyncio.sleep(SCAN_SECONDS / 3)
    assert redactor.active == 1, "the scan never started; nothing to measure"
    pump.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pump
    assert redactor.active == 0, "the pump let go while its scan was running"


@pytest.mark.asyncio
async def test_a_scan_that_raises_ends_the_pump_without_offering() -> None:
    scrubber = build_scrubber(label="lnk", factory=lambda: _SlowRedactor(fail=True))
    stream = viewer_fanout.new_viewer_stream("t")
    outbox = viewer_fanout.new_viewer_stream("out")
    _offer(stream, "secret-ish")
    with pytest.raises(RuntimeError):
        await asyncio.wait_for(relay_publisher._pump("lnk", stream, scrubber, outbox, lambda: None, asyncio.Event()), 5)
    outbox.close()
    assert await outbox.get() is None, "the chunk the scan failed on was offered"


@pytest.mark.asyncio
async def test_the_relay_publisher_pump_scans_off_the_loop() -> None:
    redactor = _SlowRedactor()
    scrubber = build_scrubber(label="lnk", factory=lambda: redactor)
    stream = viewer_fanout.new_viewer_stream("t")
    outbox = viewer_fanout.new_viewer_stream("out")
    gaps: List[float] = []
    stop = asyncio.Event()
    beat = asyncio.create_task(_heartbeat(gaps, stop))
    pump = asyncio.create_task(relay_publisher._pump("lnk", stream, scrubber, outbox, lambda: None, asyncio.Event()))
    for index in range(3):
        _offer(stream, f"c{index}")
    await asyncio.sleep(3 * SCAN_SECONDS + 0.3)
    stream.close()
    await pump
    stop.set()
    await beat
    assert redactor.fed == ["c0", "c1", "c2"] and redactor.max_active == 1
    assert max(gaps) < SCAN_SECONDS / 2, f"loop stalled {max(gaps):.3f}s"
