
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_rcg_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_rcg_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core.session_recreate_presence import (
    TMUX_GONE,
    TMUX_PRESENT,
    tmux_presence,
)
from src.core.tmux_backend import SESSION_PREFIX, TmuxBackend
from tests.socket_guard import derive_test_socket

requires_tmux = pytest.mark.skipif(
    shutil.which("tmux") is None, reason="tmux not on PATH"
)


@pytest.fixture
def tmux_socket():
    name = derive_test_socket("recreate")
    yield name
    tmux = shutil.which("tmux")
    if tmux:
        os.system(f"{tmux} -L {name} kill-server >/dev/null 2>&1")


def _read(name: str, socket_name: str):
    probe = TmuxBackend.for_external(
        session_name=name,
        working_dir=Path(tempfile.gettempdir()),
        on_output=None,
        socket_name=socket_name,
    )
    listing = probe.discover_existing()
    return tmux_presence(
        name,
        listing_ok=bool(listing.ok),
        listing_complete=bool(listing.complete),
        names=list(listing.sessions or []),
        namespace_prefix=SESSION_PREFIX,
    )


@requires_tmux
def test_a_live_session_reads_present_and_a_killed_one_reads_gone(tmux_socket):
    name = f"{SESSION_PREFIX}recreate_probe"
    backend = TmuxBackend.for_external(
        session_name=name,
        working_dir=Path(tempfile.gettempdir()),
        on_output=None,
        socket_name=tmux_socket,
    )
    rc, _, err = backend._run_tmux_sync(
        "new-session", "-d", "-s", name, "sh", check=False
    )
    assert rc == 0, err

    live = _read(name, tmux_socket)
    assert live.outcome == TMUX_PRESENT, live.detail
    assert live.gone is False, (
        "a running session read as gone would be recreated over, and the "
        "pane the user is talking to would be orphaned"
    )

    rc, _, err = backend._run_tmux_sync(
        "kill-session", "-t", name, check=False
    )
    assert rc == 0, err

    dead = _read(name, tmux_socket)
    assert dead.outcome == TMUX_GONE, dead.detail
    assert dead.gone is True


@requires_tmux
def test_a_name_that_never_existed_reads_gone_against_a_live_server(
    tmux_socket,
):
    name = f"{SESSION_PREFIX}recreate_neighbour"
    backend = TmuxBackend.for_external(
        session_name=name,
        working_dir=Path(tempfile.gettempdir()),
        on_output=None,
        socket_name=tmux_socket,
    )
    rc, _, err = backend._run_tmux_sync(
        "new-session", "-d", "-s", name, "sh", check=False
    )
    assert rc == 0, err

    assert _read(name, tmux_socket).outcome == TMUX_PRESENT
    assert _read(
        f"{SESSION_PREFIX}never_existed", tmux_socket
    ).outcome == TMUX_GONE


@requires_tmux
def test_a_name_outside_the_namespace_is_never_measured_gone(tmux_socket):
    name = "someone_elses_tmux"
    backend = TmuxBackend.for_external(
        session_name=name,
        working_dir=Path(tempfile.gettempdir()),
        on_output=None,
        socket_name=tmux_socket,
    )
    rc, _, err = backend._run_tmux_sync(
        "new-session", "-d", "-s", name, "sh", check=False
    )
    assert rc == 0, err

    verdict = _read(name, tmux_socket)
    assert verdict.gone is False
    assert "namespace" in verdict.detail
