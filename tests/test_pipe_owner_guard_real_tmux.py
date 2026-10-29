
from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_pog_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_pog_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.core import pipe_liveness as pl
from src.core.tmux_backend import SESSION_PREFIX, TmuxBackend

from tests import socket_guard

requires_tmux = pytest.mark.skipif(
    shutil.which("tmux") is None, reason="tmux not on PATH"
)

NAME = f"{SESSION_PREFIX}pipe_owner_probe"

TICKER = "i=0; while [ $i -lt 300 ]; do echo tick $i; i=$((i+1)); sleep 0.2; done"


@pytest.fixture
def tmux_socket():
    name = socket_guard.derive_test_socket("pipeowner")
    yield name
    tmux = shutil.which("tmux")
    if tmux:
        os.system(f"{tmux} -L {name} kill-server >/dev/null 2>&1")


def _backend(socket_name: str, pipe_path: Path) -> TmuxBackend:
    backend = TmuxBackend.for_external(
        session_name=NAME,
        working_dir=Path(tempfile.gettempdir()),
        on_output=None,
        socket_name=socket_name,
    )
    backend._pipe_path = pipe_path
    return backend


def _start_ticking_pane(backend: TmuxBackend) -> None:
    rc, _, err = backend._run_tmux_sync(
        "new-session", "-d", "-s", NAME, "sh", "-c", TICKER, check=False
    )
    assert rc == 0, err


def _read(backend: TmuxBackend, fmt: str) -> str:
    rc, out, err = backend._run_tmux_sync(
        "display-message", "-t", NAME, "-p", fmt, check=False
    )
    assert rc == 0, err
    return out.decode("utf-8", errors="replace").strip()


def _size(path: Path) -> int:
    return path.stat().st_size if path.exists() else 0


def _growth(path: Path, seconds: float = 1.0) -> int:
    before = _size(path)
    time.sleep(seconds)
    return _size(path) - before


def _wait_for_growth(path: Path, timeout: float = 5.0) -> int:
    before = _size(path)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        gained = _size(path) - before
        if gained > 0:
            return gained
        time.sleep(0.1)
    return _size(path) - before


def _copier_targets() -> set:
    out = subprocess.run(
        ["lsof", "-nP", "-c", "cat"], capture_output=True
    ).stdout.decode("utf-8", errors="replace")
    found = set()
    for line in out.splitlines():
        last = line.rsplit(None, 1)[-1] if line.strip() else ""
        if last.endswith(".pipe"):
            found.add(last)
    return found


def _spy(backend: TmuxBackend) -> list:
    issued: list = []
    real = backend._run_tmux

    async def _record(*args, **kwargs):
        issued.append(tuple(args))
        return await real(*args, **kwargs)

    backend._run_tmux = _record
    return issued


def _pipe_pane_starts(issued: list) -> int:
    return sum(
        1
        for argv in issued
        if argv and argv[0] == "pipe-pane" and any("cat >>" in a for a in argv)
    )


@requires_tmux
def test_tmux_cannot_name_the_copier_which_is_why_the_option_exists(
    tmux_socket, tmp_path
):
    ours = tmp_path / "ours.pipe"
    backend = _backend(tmux_socket, ours)
    _start_ticking_pane(backend)

    asyncio.run(backend.ensure_pipe_pane())

    assert _read(backend, "#{pane_pipe}") == "1"
    assert _read(backend, "#{pane_pipe_command}") == "", (
        "tmux now reports the piped command; the pane option in "
        "src/core/pipe_liveness.py may be redundant"
    )
    assert _read(backend, "#{" + pl.PIPE_OWNER_OPTION + "}") == str(ours)


@requires_tmux
def test_an_unrecording_thief_steals_the_stream_and_the_probe_takes_it_back(
    tmux_socket, tmp_path
):
    ours = tmp_path / "ours.pipe"
    theirs = tmp_path / "theirs.pipe"
    backend = _backend(tmux_socket, ours)
    _start_ticking_pane(backend)

    asyncio.run(backend.ensure_pipe_pane())
    assert _wait_for_growth(ours) > 0, "the stream never started"

    recorded = _read(backend, "#{" + pl.PIPE_OWNER_OPTION + "}")
    assert recorded and recorded.startswith("/"), (
        f"the pane recorded no absolute owner path: {recorded!r}"
    )
    assert str(ours) in _copier_targets(), (
        "no live copier holds our pipe file open, so every later "
        "assertion about which file is being fed proves nothing"
    )

    rc, _, err = backend._run_tmux_sync(
        "pipe-pane", "-t", NAME, f"cat >> {theirs}", check=False
    )
    assert rc == 0, err
    time.sleep(0.5)

    assert _read(backend, "#{pane_pipe}") == "1"
    assert _read(backend, "#{" + pl.PIPE_OWNER_OPTION + "}") == str(ours)
    stolen_growth = _growth(theirs, 1.0)
    frozen = _growth(ours, 1.0)
    assert stolen_growth > 0, "the thief's file is not growing; no theft"
    assert frozen == 0, f"our file still grew {frozen} bytes; no theft"

    verdict = asyncio.run(backend._repair_stolen_pipe(ours))
    assert verdict == pl.SILENT_WHILE_PANE_ACTIVE

    assert _wait_for_growth(ours) > 0, "the stream did not come back"
    assert _growth(theirs, 0.6) == 0, "the thief is still being fed"
    assert _read(backend, "#{" + pl.PIPE_OWNER_OPTION + "}") == str(ours)


@requires_tmux
def test_a_recording_thief_is_caught_by_the_option_on_the_attach_guard(
    tmux_socket, tmp_path
):
    ours = tmp_path / "ours.pipe"
    theirs = tmp_path / "theirs.pipe"
    backend = _backend(tmux_socket, ours)
    _start_ticking_pane(backend)

    asyncio.run(backend.ensure_pipe_pane())
    assert _wait_for_growth(ours) > 0

    backend._run_tmux_sync(
        "pipe-pane", "-t", NAME, f"cat >> {theirs}", check=False
    )
    backend._run_tmux_sync(
        "set-option", "-p", "-t", NAME, pl.PIPE_OWNER_OPTION, str(theirs),
        check=False,
    )
    assert _read(backend, "#{" + pl.PIPE_OWNER_OPTION + "}") == str(theirs)

    reading = asyncio.run(backend.read_pipe_ownership())
    assert reading is not None
    assert pl.classify_ownership(reading, str(ours), True) == pl.FOREIGN_OWNER

    asyncio.run(backend.ensure_pipe_pane())
    assert _read(backend, "#{" + pl.PIPE_OWNER_OPTION + "}") == str(ours)
    assert _wait_for_growth(ours) > 0
    assert _growth(theirs, 0.6) == 0


@requires_tmux
def test_the_guard_leaves_its_own_healthy_copier_alone(tmux_socket, tmp_path):
    ours = tmp_path / "ours.pipe"
    backend = _backend(tmux_socket, ours)
    _start_ticking_pane(backend)

    asyncio.run(backend.ensure_pipe_pane())
    assert _wait_for_growth(ours) > 0

    issued = _spy(backend)
    asyncio.run(backend.ensure_pipe_pane())
    assert len(issued) > 0, (
        "the guard issued no tmux command at all, so the zero-re-issue "
        "assertion below is looking at nothing"
    )
    assert issued[0][0] == "display-message", (
        f"the guard must probe the pane before deciding, got {issued[0]}"
    )
    assert _pipe_pane_starts(issued) == 0, (
        f"the guard re-issued pipe-pane on its own healthy copier: {issued}"
    )
    assert _wait_for_growth(ours) > 0, "the stream did not survive the guard"


@requires_tmux
def test_a_pane_producing_nothing_is_left_alone_by_the_probe(
    tmux_socket, tmp_path
):
    ours = tmp_path / "ours.pipe"
    backend = _backend(tmux_socket, ours)
    rc, _, err = backend._run_tmux_sync(
        "new-session", "-d", "-s", NAME, "sh", "-c", "sleep 600", check=False
    )
    assert rc == 0, err

    asyncio.run(backend.ensure_pipe_pane())
    time.sleep(1.5)

    issued = _spy(backend)
    verdict = asyncio.run(backend._repair_stolen_pipe(ours))
    assert len(issued) > 0 and issued[0][0] == "display-message", (
        f"the probe never read the pane, so the zero-re-issue assertion "
        f"below is looking at nothing: {issued}"
    )
    assert str(ours) in _copier_targets(), (
        "no live copier holds our pipe file open, so 'the probe left it "
        "alone' proves nothing about a working stream"
    )
    assert verdict == pl.QUIET
    assert _pipe_pane_starts(issued) == 0, (
        f"a quiet pane was re-piped: {issued}"
    )


@requires_tmux
def test_no_probe_is_spawned_for_a_pane_nobody_is_watching(
    tmux_socket, tmp_path
):
    ours = tmp_path / "ours.pipe"
    backend = _backend(tmux_socket, ours)
    assert backend.has_viewers() is False
    assert backend._liveness.due(now=time.monotonic() + 3600, has_viewers=False) is False

    backend._viewer_probe = lambda: True
    assert backend.has_viewers() is True

    def _explode() -> bool:
        raise RuntimeError("registry is gone")

    backend._viewer_probe = _explode
    assert backend.has_viewers() is False
