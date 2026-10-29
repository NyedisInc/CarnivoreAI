
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_xsock_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_xsock_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core.session_status_map import StatusMap, listing_proves_alive
from src.core.tmux_backend import TmuxBackend
from tests.socket_guard import derive_test_socket

requires_tmux = pytest.mark.skipif(
    shutil.which("tmux") is None, reason="tmux not on PATH"
)

SHARED_NAME = "cloude_xsock_probe"


def _tmux(socket: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["tmux", "-L", socket, *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _pre_fix_proves_alive(
    status_map: Optional[Dict[str, Any]], tmux_name: Optional[str]
) -> bool:
    if not tmux_name:
        return False
    if status_map is None:
        return False
    if not getattr(status_map, "complete", False):
        return False
    return tmux_name in status_map


@pytest.fixture
def two_sockets():
    sock_a = derive_test_socket("xsock_a")
    sock_b = derive_test_socket("xsock_b")
    try:
        yield sock_a, sock_b
    finally:
        _tmux(sock_a, "kill-server")
        _tmux(sock_b, "kill-server")


@requires_tmux
def test_a_listing_from_another_socket_cannot_vouch_for_a_dead_session(
    two_sockets,
):
    sock_a, sock_b = two_sockets

    assert _tmux(sock_a, "new-session", "-d", "-s", SHARED_NAME).returncode == 0
    assert _tmux(sock_b, "new-session", "-d", "-s", SHARED_NAME).returncode == 0
    assert _tmux(sock_b, "kill-session", "-t", SHARED_NAME).returncode == 0

    backend_b = TmuxBackend.for_external(
        session_name=SHARED_NAME,
        working_dir=Path(tempfile.gettempdir()),
        socket_name=sock_b,
    )

    assert backend_b.is_alive() is False

    listing_from_a = StatusMap(
        {SHARED_NAME: {"status": "running"}}, complete=True, socket=sock_a
    )

    assert _pre_fix_proves_alive(listing_from_a, SHARED_NAME) is True

    assert (
        listing_proves_alive(
            listing_from_a, SHARED_NAME, backend_socket=backend_b.socket_name
        )
        is False
    )


@requires_tmux
def test_the_saving_survives_for_a_backend_on_the_listings_own_socket(
    two_sockets,
):
    sock_a, _sock_b = two_sockets
    assert _tmux(sock_a, "new-session", "-d", "-s", SHARED_NAME).returncode == 0

    backend_a = TmuxBackend.for_external(
        session_name=SHARED_NAME,
        working_dir=Path(tempfile.gettempdir()),
        socket_name=sock_a,
    )
    assert backend_a.is_alive() is True

    listing_from_a = StatusMap(
        {SHARED_NAME: {"status": "running"}}, complete=True, socket=sock_a
    )
    assert (
        listing_proves_alive(
            listing_from_a, SHARED_NAME, backend_socket=backend_a.socket_name
        )
        is True
    )


def test_an_unstated_socket_on_either_side_refuses():
    stated = StatusMap({SHARED_NAME: {}}, complete=True, socket="cloude")
    unstated = StatusMap({SHARED_NAME: {}}, complete=True)

    assert listing_proves_alive(stated, SHARED_NAME, backend_socket=None) is False
    assert (
        listing_proves_alive(unstated, SHARED_NAME, backend_socket="cloude")
        is False
    )
    assert listing_proves_alive(stated, SHARED_NAME, backend_socket="cloude") is True

    assert (
        listing_proves_alive({SHARED_NAME: {}}, SHARED_NAME, backend_socket="cloude")
        is False
    )
