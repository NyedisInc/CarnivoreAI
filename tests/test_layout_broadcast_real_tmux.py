
from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_lbr_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_lbr_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core.layouts import broadcast as layout_broadcast
from src.core.layouts.store import LayoutMember, SavedLayout
from src.core.tmux_backend import SESSION_PREFIX, TmuxBackend

from tests import socket_guard

requires_tmux = pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux not on PATH")

READ_LOOP = 'while IFS= read -r l; do printf "GOT<%s>\\n" "$l"; done'
LINE = "echo broadcast-837"
NAMES = [f"{SESSION_PREFIX}bcast_{tag}" for tag in ("on_a", "off_b", "on_c")]


@pytest.fixture
def tmux_socket():
    name = socket_guard.derive_test_socket("bcast")
    yield name
    tmux = shutil.which("tmux")
    if tmux:
        os.system(f"{tmux} -L {name} kill-server >/dev/null 2>&1")


def _backend(name: str, socket_name: str) -> TmuxBackend:
    return TmuxBackend.for_external(session_name=name, working_dir=Path(tempfile.gettempdir()),
                                    on_output=None, socket_name=socket_name)


def _capture(backend: TmuxBackend, name: str) -> str:
    rc, out, _ = backend._run_tmux_sync("capture-pane", "-p", "-t", name, check=False)
    return out.decode("utf-8", errors="replace") if rc == 0 else ""


def _settled(backend: TmuxBackend, name: str) -> str:
    previous, stable, deadline = None, 0, time.monotonic() + 3.0
    while time.monotonic() < deadline:
        current = _capture(backend, name)
        stable = stable + 1 if current == previous else 0
        if stable >= 3:
            return current
        previous = current
        time.sleep(0.1)
    return previous or ""


@requires_tmux
def test_the_line_lands_once_in_every_on_pane_and_never_in_the_off_one(tmux_socket):
    backends = [_backend(name, tmux_socket) for name in NAMES]
    for backend, name in zip(backends, NAMES):
        rc, _, err = backend._run_tmux_sync("new-session", "-d", "-s", name, "-x", "120", "-y", "20",
                                            "sh", "-c", READ_LOOP, check=False)
        assert rc == 0, err.decode("utf-8", errors="replace")
        backend._running = True
    assert all(b.is_alive() for b in backends), "the stand-in panes never came up"

    members = tuple(LayoutMember(row_id, f"u{row_id}", row_id - 1, broadcast=(row_id != 2))
                    for row_id in (1, 2, 3))
    layout = SavedLayout(layout_uuid="lay-837", name="trio", position=0, shape={}, revision=1,
                         source_key=None, created_at="", updated_at="", members=members)
    infos = [SimpleNamespace(session_row_id=i + 1, session=SimpleNamespace(id=f"ses_{i}"),
                             activity_status="idle", startup_gate="ready") for i in range(3)]
    by_id = {f"ses_{i}": backends[i] for i in range(3)}

    outcomes = asyncio.run(layout_broadcast.broadcast(layout, LINE, infos=infos,
                                                      backend_for=by_id.get))

    assert [o.status for o in outcomes] == ["sent", "skipped_off", "sent"], outcomes
    screens = [_settled(b, n) for b, n in zip(backends, NAMES)]
    for index in (0, 2):
        assert screens[index].count(f"GOT<{LINE}>") == 1, screens[index]
        assert "GOT<>" not in screens[index], "a second Enter was sent:\n" + screens[index]
    assert "GOT<" not in screens[1] and "broadcast-837" not in screens[1], (
        "the toggled-off pane received the broadcast:\n" + screens[1])
