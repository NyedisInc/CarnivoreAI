
from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
import time
import uuid
from pathlib import Path

import pytest

from src.core import tmux_one_shot
from src.core.tmux_backend import PASTE_THRESHOLD_BYTES, TmuxBackend

from tests import socket_guard

requires_tmux = pytest.mark.skipif(
    shutil.which("tmux") is None, reason="tmux not on PATH"
)

OPEN = b"\x1b[200~"
CLOSE = b"\x1b[201~"

CHUNK = b'echo "a b" \\\nnext\tline\r\xc3\xa9 done\x1b[A\x01\x7f\n'


@pytest.fixture
def tmux_socket():
    name = socket_guard.derive_test_socket("pastebytes")
    yield name
    tmux = shutil.which("tmux")
    if tmux:
        os.system(f"{tmux} -L {name} kill-server >/dev/null 2>&1")


async def _recording_pane(socket_name: str, out: Path, echo: bool = False) -> TmuxBackend:
    backend = TmuxBackend(
        session_id=f"pastebytes-{uuid.uuid4().hex[:6]}",
        working_dir=Path(tempfile.gettempdir()),
        on_output=None,
        socket_name=socket_name,
    )
    stty = "raw echo" if echo else "raw -echo"
    await backend.start(
        command=f"printf '\\033[?2004h'; stty {stty}; exec dd bs=1 of='{out}' 2>/dev/null"
    )
    deadline = time.monotonic() + 10.0
    while not out.exists():
        assert time.monotonic() < deadline, "the recording pane never started"
        await asyncio.sleep(0.05)
    await asyncio.sleep(0.3)
    return backend


async def _read_settled(out: Path, want_len: int) -> bytes:
    deadline = time.monotonic() + 5.0
    last = b""
    while time.monotonic() < deadline:
        cur = out.read_bytes()
        if len(cur) >= want_len and cur == last:
            return cur
        last = cur
        await asyncio.sleep(0.15)
    return last


async def _deliver(socket_name: str, tmp: Path, payload: bytes) -> bytes:
    out = tmp / f"rec-{uuid.uuid4().hex[:6]}.bin"
    backend = await _recording_pane(socket_name, out)
    try:
        await backend.write(payload)
        return await _read_settled(out, len(payload))
    finally:
        await backend.stop()


@requires_tmux
def test_a_framed_paste_over_the_threshold_arrives_with_exactly_one_marker_pair(
    tmux_socket, tmp_path
):
    body = CHUNK.replace(b"\n", b"\r") * 20
    payload = OPEN + body + CLOSE
    assert len(payload) > PASTE_THRESHOLD_BYTES

    got = asyncio.run(_deliver(tmux_socket, tmp_path, payload))

    assert got.count(OPEN) == 1 and got.count(CLOSE) == 1, (
        f"expected ONE marker pair, got {got.count(OPEN)} open / "
        f"{got.count(CLOSE)} close: {got[:40]!r}"
    )
    assert got == payload


@requires_tmux
@pytest.mark.parametrize("repeat", [1, 20], ids=["under-threshold", "over-threshold"])
def test_the_same_bytes_arrive_identically_under_and_over_the_threshold(
    tmux_socket, tmp_path, repeat
):
    payload = CHUNK * repeat
    if repeat == 1:
        assert len(payload) <= PASTE_THRESHOLD_BYTES
    else:
        assert len(payload) > PASTE_THRESHOLD_BYTES

    got = asyncio.run(_deliver(tmux_socket, tmp_path, payload))

    assert got == payload, f"sent {payload[:48]!r}..., pane read {got[:48]!r}..."


@requires_tmux
def test_the_one_shot_route_still_adds_the_markers(tmux_socket, tmp_path):
    out = tmp_path / "oneshot.bin"

    async def drive() -> bytes:
        backend = await _recording_pane(tmux_socket, out, echo=True)
        try:
            await tmux_one_shot.paste_and_submit(backend, "alphaone bravotwo")
            return await _read_settled(out, len(OPEN) + 17 + len(CLOSE) + 1)
        finally:
            await backend.stop()

    got = asyncio.run(drive())

    assert got.startswith(OPEN + b"alphaone bravotwo" + CLOSE), got[:60]
    assert got.count(OPEN) == 1 and got.count(CLOSE) == 1, got[:60]
