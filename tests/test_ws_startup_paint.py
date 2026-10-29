
from __future__ import annotations

import os
import tempfile

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_tests_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_tests_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.api.ws_startup_paint import STALL_AFTER_SECONDS, paint_on_attach


class FakeWS:

    def __init__(self) -> None:
        self.frames: list[bytes] = []
        self.fail = False

    async def send_bytes(self, data: bytes) -> None:
        if self.fail:
            raise RuntimeError("socket gone")
        self.frames.append(data)


class FakeBackend:

    def __init__(
        self,
        alternate: bool = False,
        screen: bytes = b"",
        age: "float | None" = 0.0,
    ) -> None:
        self._alternate = alternate
        self._screen = screen
        self._age = age
        self.written: list[bytes] = []
        self.alt_raises = False
        self.capture_raises = False
        self.write_raises = False
        self.age_raises = False

    def session_age_seconds(self) -> "float | None":
        if self.age_raises:
            raise RuntimeError("tmux gone")
        return self._age

    def pane_in_alternate_screen(self) -> bool:
        if self.alt_raises:
            raise RuntimeError("tmux gone")
        return self._alternate

    def capture_visible_screen(self) -> bytes:
        if self.capture_raises:
            raise RuntimeError("tmux gone")
        return self._screen

    async def write(self, data: bytes) -> None:
        if self.write_raises:
            raise RuntimeError("pane gone")
        self.written.append(data)


@pytest.mark.asyncio
async def test_tui_gets_a_capture_and_the_pane_is_never_written_to():
    ws, backend = FakeWS(), FakeBackend(alternate=True, screen=b"the frame")
    assert await paint_on_attach(ws, backend) == "screen"
    assert backend.written == [], "attaching must never write into the pane"
    assert ws.frames == [b"\x1b[H\x1b[2J" + b"the frame"]


@pytest.mark.asyncio
async def test_cooked_pane_gets_a_screen_paint_and_no_pty_write():
    ws = FakeWS()
    backend = FakeBackend(alternate=False, screen=b"password: ")
    assert await paint_on_attach(ws, backend) == "screen"
    assert backend.written == [], "Ctrl+L must never enter a line reader's input"
    assert len(ws.frames) == 1
    assert ws.frames[0].endswith(b"password: ")


@pytest.mark.asyncio
async def test_screen_paint_clears_before_painting():
    ws = FakeWS()
    await paint_on_attach(ws, FakeBackend(screen=b"hello"))
    assert ws.frames[0].startswith(b"\x1b[H\x1b[2J")


@pytest.mark.asyncio
async def test_empty_screen_on_a_young_session_paints_nothing_at_all():
    ws, backend = FakeWS(), FakeBackend(screen=b"", age=0.2)
    assert await paint_on_attach(ws, backend) == "none"
    assert ws.frames == []
    assert backend.written == []




@pytest.mark.asyncio
async def test_blank_screen_on_an_old_session_is_announced():
    ws, backend = FakeWS(), FakeBackend(screen=b"", age=STALL_AFTER_SECONDS + 1)
    assert await paint_on_attach(ws, backend) == "stalled"
    assert len(ws.frames) == 1
    assert b"printed nothing" in ws.frames[0]
    assert b"waiting on input" in ws.frames[0]


@pytest.mark.asyncio
async def test_stall_notice_never_writes_to_the_pane():
    ws, backend = FakeWS(), FakeBackend(screen=b"", age=999.0)
    await paint_on_attach(ws, backend)
    assert backend.written == [], "nothing may enter a pane that may be reading"


@pytest.mark.asyncio
async def test_stall_boundary_is_inclusive_and_below_it_is_silent():
    at = FakeBackend(screen=b"", age=STALL_AFTER_SECONDS)
    assert await paint_on_attach(FakeWS(), at) == "stalled"
    under = FakeBackend(screen=b"", age=STALL_AFTER_SECONDS - 0.01)
    assert await paint_on_attach(FakeWS(), under) == "none"


@pytest.mark.asyncio
async def test_unknown_age_never_invents_an_alarm():
    ws, backend = FakeWS(), FakeBackend(screen=b"", age=None)
    assert await paint_on_attach(ws, backend) == "none"
    assert ws.frames == []


@pytest.mark.asyncio
async def test_age_probe_failure_is_survivable():
    ws, backend = FakeWS(), FakeBackend(screen=b"")
    backend.age_raises = True
    assert await paint_on_attach(ws, backend) == "none"
    assert ws.frames == []


@pytest.mark.asyncio
async def test_backend_without_the_probe_degrades_to_silence():

    class NoProbe:
        def pane_in_alternate_screen(self) -> bool:
            return False

        def capture_visible_screen(self) -> bytes:
            return b""

        async def write(self, data: bytes) -> None:
            raise AssertionError("must not write")

    assert await paint_on_attach(FakeWS(), NoProbe()) == "none"


@pytest.mark.asyncio
async def test_a_painted_screen_is_never_called_a_stall():
    ws, backend = FakeWS(), FakeBackend(screen=b"hello", age=99999.0)
    assert await paint_on_attach(ws, backend) == "screen"
    assert b"printed nothing" not in ws.frames[0]


@pytest.mark.asyncio
async def test_missing_backend_is_a_noop():
    ws = FakeWS()
    assert await paint_on_attach(ws, None) == "none"
    assert ws.frames == []


@pytest.mark.asyncio
async def test_unreadable_pane_state_falls_back_to_the_safe_branch():
    ws = FakeWS()
    backend = FakeBackend(alternate=True, screen=b"prompt: ")
    backend.alt_raises = True
    assert await paint_on_attach(ws, backend) == "screen"
    assert backend.written == []


@pytest.mark.asyncio
async def test_capture_failure_is_survivable():
    ws = FakeWS()
    backend = FakeBackend(screen=b"x")
    backend.capture_raises = True
    assert await paint_on_attach(ws, backend) == "none"
    assert ws.frames == []


@pytest.mark.asyncio
async def test_a_blank_alternate_screen_is_never_called_a_startup_hang():
    ws, backend = FakeWS(), FakeBackend(alternate=True, screen=b"", age=999.0)
    assert await paint_on_attach(ws, backend) == "none"
    assert ws.frames == []
    assert backend.written == []


@pytest.mark.asyncio
async def test_send_failure_is_survivable():
    ws = FakeWS()
    ws.fail = True
    assert await paint_on_attach(ws, FakeBackend(screen=b"x")) == "none"



import asyncio  # noqa: E402
import shutil  # noqa: E402
import uuid  # noqa: E402
from pathlib import Path  # noqa: E402

from src.core.tmux_backend import TmuxBackend  # noqa: E402
from tests.socket_guard import derive_test_socket

requires_tmux = pytest.mark.skipif(
    shutil.which("tmux") is None, reason="tmux not on PATH"
)


def _paint_against_pane(command: str, socket: str) -> tuple:
    seen = bytearray()
    backend = TmuxBackend(
        session_id=f"paint-{uuid.uuid4().hex[:6]}",
        working_dir=Path(tempfile.gettempdir()),
        on_output=seen.extend,
        socket_name=socket,
    )
    ws = FakeWS()

    async def _inner():
        await backend.start(command=command)
        await asyncio.sleep(0.4)
        backend.resize(100, 30)
        await asyncio.sleep(0.15)
        strategy = await paint_on_attach(ws, backend)
        await asyncio.sleep(0.3)
        return strategy, backend.capture_visible_screen()

    try:
        strategy, pane = asyncio.run(_inner())
    finally:
        asyncio.run(backend.stop())
    return strategy, bytes(seen) + b"".join(ws.frames), pane


@pytest.fixture
def tmux_socket():
    name = derive_test_socket("paint")
    yield name
    tmux = shutil.which("tmux")
    if tmux:
        os.system(f"{tmux} -L {name} kill-server >/dev/null 2>&1")


@requires_tmux
def test_startup_prompt_reaches_the_client_and_no_caret_l_appears(tmux_socket):
    if shutil.which("zsh") is None:
        pytest.skip("zsh not available")

    script = Path(tempfile.gettempdir()) / f"cc_pw_{uuid.uuid4().hex[:6]}.zsh"
    script.write_text('read "?password: " pw\nprint "GOT[$pw]"\nsleep 20\n')
    try:
        strategy, client, pane = _paint_against_pane(f"/bin/zsh -f {script}", tmux_socket)
    finally:
        script.unlink(missing_ok=True)

    assert strategy == "screen"
    assert b"password:" in client, client[:200]
    assert b"^L" not in client, client[:200]
    assert b"^L" not in pane, pane[:200]


@requires_tmux
def test_full_screen_app_is_painted_from_a_capture_not_a_redraw(tmux_socket):
    if shutil.which("less") is None:
        pytest.skip("less not available")
    strategy, client, _ = _paint_against_pane(
        "/bin/sh -c 'seq 1 200 | less'", tmux_socket
    )
    assert strategy == "screen"
    assert b"^L" not in client, client[:200]
    assert b"1" in client and b"20" in client, client[:200]


@pytest.mark.asyncio
async def test_local_backend_probes_run_off_the_event_loop():
    import threading

    loop_thread = threading.get_ident()
    seen: dict[str, int] = {}

    class ThreadBackend(FakeBackend):
        def pane_in_alternate_screen(self) -> bool:
            seen["alt"] = threading.get_ident()
            return False

        def capture_visible_screen(self) -> bytes:
            seen["capture"] = threading.get_ident()
            return b""

        def session_age_seconds(self):
            seen["age"] = threading.get_ident()
            return STALL_AFTER_SECONDS + 1

    assert await paint_on_attach(FakeWS(), ThreadBackend()) == "stalled"
    assert set(seen) == {"alt", "capture", "age"}
    assert all(ident != loop_thread for ident in seen.values()), seen
