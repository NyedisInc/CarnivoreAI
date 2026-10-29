
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import List, Optional, Tuple

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_ccr_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_ccr_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core.tmux_backend import TmuxBackend
from tests.socket_guard import derive_test_socket

pytestmark = pytest.mark.skipif(
    shutil.which("tmux") is None, reason="real tmux binary not available"
)

COLUMNS = 80
ROWS = 24

CURSOR_ROW = 3
CURSOR_COL = 6

TEXT_LINES = 10


def _tmux(socket: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["tmux", "-L", socket, *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )


def _cursor_of(socket: str, session: str) -> Tuple[int, int]:
    result = _tmux(socket, "display-message", "-p", "-t", session,
                   "#{cursor_x} #{cursor_y}")
    parts = result.stdout.split()
    assert len(parts) == 2, f"tmux gave no cursor for {session!r}: {result!r}"
    return int(parts[0]), int(parts[1])


def _wait_for_cursor(
    socket: str, session: str, want: Tuple[int, int], timeout: float = 8.0
) -> Tuple[int, int]:
    deadline = time.monotonic() + timeout
    seen = _cursor_of(socket, session)
    while seen != want and time.monotonic() < deadline:
        time.sleep(0.05)
        seen = _cursor_of(socket, session)
    return seen


def _painter_script(directory: Path) -> Path:
    path = directory / "paint.sh"
    path.write_text(
        "#!/bin/sh\n"
        "printf '\\033[H\\033[2J'\n"
        "i=1\n"
        f"while [ $i -le {TEXT_LINES} ]; do\n"
        "  printf 'row %s of source text\\r\\n' \"$i\"\n"
        "  i=$((i+1))\n"
        "done\n"
        f"printf '\\033[{CURSOR_ROW};{CURSOR_COL}H'\n"
        "sleep 300\n",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def _new_pane(socket: str, name: str, command: str, cwd: Path) -> None:
    result = _tmux(
        socket, "new-session", "-d",
        "-s", name,
        "-c", str(cwd),
        "-x", str(COLUMNS), "-y", str(ROWS),
        "-e", "TERM=xterm-256color",
        command,
    )
    assert result.returncode == 0, f"tmux new-session failed: {result.stderr}"


def _backend_for(socket: str, session: str, cwd: Path) -> TmuxBackend:
    return TmuxBackend(
        session_id=session,
        working_dir=cwd,
        socket_name=socket,
        session_name=session,
    )


def _replay_into(socket: str, mirror: str, stream: bytes) -> None:
    tty = _tmux(socket, "display-message", "-p", "-t", mirror,
                "#{pane_tty}").stdout.strip()
    assert tty.startswith("/dev/"), f"no tty for mirror pane: {tty!r}"
    with open(tty, "wb", buffering=0) as handle:
        handle.write(stream)


@pytest.fixture()
def socket_name():
    name = derive_test_socket("capture_cursor")
    try:
        yield name
    finally:
        _tmux(name, "kill-server")


@pytest.fixture()
def panes(socket_name, tmp_path):
    script = _painter_script(tmp_path)
    _new_pane(socket_name, "src", f"sh {script}", tmp_path)
    _new_pane(socket_name, "mirror", "sleep 300", tmp_path)
    want = (CURSOR_COL - 1, CURSOR_ROW - 1)
    seen = _wait_for_cursor(socket_name, "src", want)
    assert seen == want, (
        f"the painter never parked the cursor at {want}, it is at {seen}; "
        "the fixture is broken and nothing below would mean anything"
    )
    return socket_name, "src", "mirror"


def test_the_replayed_capture_leaves_the_cursor_where_the_pane_has_it(
    panes, tmp_path
):
    socket, source, mirror = panes
    backend = _backend_for(socket, source, tmp_path)

    screen = backend.capture_visible_screen()
    assert screen, "the source pane captured empty; the fixture never painted"

    _replay_into(socket, mirror, b"\x1b[H\x1b[2J" + screen)

    want = _cursor_of(socket, source)
    seen = _wait_for_cursor(socket, mirror, want, timeout=5.0)
    assert seen == want, (
        f"the mirror's cursor is at {seen} but the source pane's is at "
        f"{want}. Every subsequent keystroke is drawn with relative motion "
        "from wherever the cursor is, so this offset never heals: it is "
        "the whole defect."
    )


def test_the_two_panes_agree_cell_for_cell_after_the_replay(panes, tmp_path):
    socket, source, mirror = panes
    backend = _backend_for(socket, source, tmp_path)

    _replay_into(socket, mirror, b"\x1b[H\x1b[2J" + backend.capture_visible_screen())
    time.sleep(0.3)

    def text(session: str) -> List[str]:
        out = _tmux(socket, "capture-pane", "-p", "-S", "0", "-t", session)
        return [line.rstrip() for line in out.stdout.rstrip("\n").split("\n")]

    assert text(mirror) == text(source)


def test_the_capture_ends_with_the_cursor_the_pane_reports(panes, tmp_path):
    socket, source, mirror = panes
    backend = _backend_for(socket, source, tmp_path)

    x, y = backend.pane_cursor_position()
    assert (x, y) == (CURSOR_COL - 1, CURSOR_ROW - 1)
    assert backend.capture_visible_screen().endswith(
        f"\x1b[{CURSOR_ROW};{CURSOR_COL}H".encode("ascii")
    )


def test_an_unreadable_cursor_appends_nothing_rather_than_guessing(
    panes, tmp_path, monkeypatch
):
    socket, source, mirror = panes
    backend = _backend_for(socket, source, tmp_path)

    restored = backend.capture_visible_screen()

    def no_cursor() -> Optional[Tuple[int, int]]:
        return None

    monkeypatch.setattr(backend, "pane_cursor_position", no_cursor)
    plain = backend.capture_visible_screen()

    assert plain, "the fallback must still return the screen"
    assert restored == plain + f"\x1b[{CURSOR_ROW};{CURSOR_COL}H".encode("ascii"), (
        "the cursor restoration must be the ONLY difference between the two, "
        "so a failed reading costs the caller the cursor and nothing else"
    )


def test_a_pane_that_does_not_exist_refuses_to_report_a_cursor(
    socket_name, tmp_path
):
    backend = _backend_for(socket_name, "no_such_session_here", tmp_path)
    assert backend.pane_cursor_position() is None
    assert backend.capture_visible_screen() == b""
