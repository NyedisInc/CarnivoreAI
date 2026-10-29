
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_roe_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_roe_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core.tmux_backend import TmuxBackend
from tests.socket_guard import derive_test_socket

pytestmark = pytest.mark.skipif(
    shutil.which("tmux") is None, reason="real tmux binary not available"
)

DOOMED_BINARY = "/nonexistent/cloude-remain-on-exit-ordering-probe"


def _tmux(socket: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["tmux", "-L", socket, *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )


@pytest.fixture()
def hostile_socket(request, tmp_path):
    socket = derive_test_socket(f"roe_{request.node.name[:18]}")
    _tmux(socket, "new-session", "-d", "-s", "keeper", "-x", "80", "-y", "24")
    _tmux(socket, "set-option", "-wg", "remain-on-exit", "off")
    yield socket, tmp_path
    _tmux(socket, "kill-server")


@pytest.mark.asyncio
async def test_instant_exit_is_reported_not_silently_accepted(hostile_socket):
    socket, work = hostile_socket
    backend = TmuxBackend(
        session_id="roe_probe",
        working_dir=work,
        on_output=None,
        socket_name=socket,
        session_name="roe_probe",
    )

    with pytest.raises(RuntimeError) as caught:
        await backend.start(command=DOOMED_BINARY)

    message = str(caught.value)
    assert DOOMED_BINARY in message, (
        "start() raised, but not with what the dying pane printed. The pane "
        "was almost certainly gone before the probe could read it, which is "
        "the ordering bug: " + message
    )
