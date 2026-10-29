
from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_paint_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_paint_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.api.ws_startup_paint import paint_on_attach
from src.core.tmux_backend import TmuxBackend
from tests.socket_guard import derive_test_socket

TMUX = shutil.which("tmux") or "/opt/homebrew/bin/tmux"
SOCKET = derive_test_socket("attachpaint")

MARKER = "PAINTPROBE"

ALT_SCREEN_CMD = (
    "printf '\\033[?1049h\\033[2J\\033[H" + MARKER + " alt screen'; "
    "while true; do sleep 5; done"
)

MAIN_SCREEN_CMD = "printf '" + MARKER + " main screen\\n'; while true; do sleep 5; done"


pytestmark = pytest.mark.skipif(
    not Path(TMUX).exists(), reason="tmux is not installed on this host"
)


class _RecordingSocket:

    def __init__(self) -> None:
        self.frames: list[bytes] = []

    async def send_bytes(self, data: bytes) -> None:
        self.frames.append(data)

    def painted(self) -> bytes:
        return b"".join(self.frames)


def _tmux(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [TMUX, "-L", SOCKET, *args], capture_output=True, text=True
    )


@pytest.fixture
def socket_cleanup():
    _tmux("kill-server")
    yield
    _tmux("kill-server")


async def _start(session_id: str, command: str) -> TmuxBackend:
    backend = TmuxBackend(
        session_id=session_id, working_dir=Path("/tmp"), socket_name=SOCKET
    )
    await backend.start(command=f"sh -c {command!r}")
    await asyncio.sleep(1.0)
    return backend


@pytest.mark.asyncio
async def test_fullscreen_pane_paints_on_first_attach(socket_cleanup) -> None:
    backend = await _start("paint_alt", ALT_SCREEN_CMD)
    try:
        assert backend.pane_in_alternate_screen() is True, (
            "the fixture is not on the alternate screen, so this test "
            "would not exercise the case that was rolled back"
        )
        ws = _RecordingSocket()
        assert await paint_on_attach(ws, backend) == "screen"
        assert ws.painted(), "the client received no frame at all"
        assert backend.is_alive()
    finally:
        await backend.stop()


@pytest.mark.asyncio
async def test_fullscreen_pane_paints_again_on_reattach(socket_cleanup) -> None:
    backend = await _start("paint_alt_re", ALT_SCREEN_CMD)
    try:
        first = await paint_on_attach(_RecordingSocket(), backend)
        rejoined = TmuxBackend(
            session_id="paint_alt_re", working_dir=Path("/tmp"), socket_name=SOCKET
        )
        await rejoined.attach_existing()
        assert rejoined.pane_in_alternate_screen() is True
        second = await paint_on_attach(_RecordingSocket(), rejoined)
        assert (first, second) == ("screen", "screen")
        assert rejoined.capture_scrollback(), (
            "an alternate-screen pane must still capture bytes on rejoin; "
            "this is the exact invariant a685242 broke"
        )
    finally:
        _tmux("kill-session", "-t", backend.tmux_session)


@pytest.mark.asyncio
async def test_normal_pane_sends_a_non_empty_capture(socket_cleanup) -> None:
    backend = await _start("paint_main", MAIN_SCREEN_CMD)
    try:
        assert backend.pane_in_alternate_screen() is False
        ws = _RecordingSocket()
        assert await paint_on_attach(ws, backend) == "screen"
        painted = ws.painted()
        assert painted, "the client received no bytes at all"
        assert MARKER.encode() in painted, (
            "the capture reached the client but carried none of the "
            f"screen: {painted[:200]!r}"
        )
    finally:
        await backend.stop()


@pytest.mark.asyncio
async def test_normal_pane_repaints_on_reattach(socket_cleanup) -> None:
    backend = await _start("paint_main_re", MAIN_SCREEN_CMD)
    try:
        first = _RecordingSocket()
        await paint_on_attach(first, backend)
        rejoined = TmuxBackend(
            session_id="paint_main_re", working_dir=Path("/tmp"), socket_name=SOCKET
        )
        await rejoined.attach_existing()
        second = _RecordingSocket()
        assert await paint_on_attach(second, rejoined) == "screen"
        assert MARKER.encode() in second.painted()
        assert MARKER.encode() in first.painted()
    finally:
        _tmux("kill-session", "-t", backend.tmux_session)


@pytest.mark.asyncio
async def test_scrollback_capture_is_non_empty_for_both_pane_types(
    socket_cleanup,
) -> None:
    alt = await _start("paint_sb_alt", ALT_SCREEN_CMD)
    main = await _start("paint_sb_main", MAIN_SCREEN_CMD)
    try:
        assert alt.pane_in_alternate_screen() is True
        assert main.pane_in_alternate_screen() is False
        assert alt.capture_scrollback(), "alternate-screen capture was empty"
        assert main.capture_scrollback(), "normal-screen capture was empty"
        assert MARKER.encode() in main.capture_scrollback()
    finally:
        await alt.stop()
        await main.stop()
