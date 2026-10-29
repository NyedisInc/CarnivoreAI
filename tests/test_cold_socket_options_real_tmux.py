
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_cold_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_cold_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core.tmux_backend import HISTORY_LIMIT, TmuxBackend
from tests.socket_guard import derive_test_socket

pytestmark = pytest.mark.skipif(
    shutil.which("tmux") is None, reason="real tmux binary not available"
)

LONG_LIVED = "sleep 120"


def _tmux(socket: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["tmux", "-L", socket, *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )


def _option(socket: str, *args: str) -> str:
    result = _tmux(socket, "show-options", *args)
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


@pytest.fixture()
def cold_socket(request):
    socket = derive_test_socket(f"cold_{request.node.name[:16]}")
    _tmux(socket, "kill-server")
    probe = _tmux(socket, "list-sessions")
    assert probe.returncode != 0, (
        f"socket {socket!r} already has a tmux server on it, so this test "
        f"would measure the warm path: {probe.stdout.strip()!r}"
    )
    try:
        yield socket
    finally:
        _tmux(socket, "kill-server")


async def _launch(socket: str, work_dir, name: str) -> TmuxBackend:
    backend = TmuxBackend(
        session_id=name,
        working_dir=work_dir,
        on_output=None,
        socket_name=socket,
        session_name=name,
    )
    await backend.start(command=LONG_LIVED)
    return backend




def test_the_pre_spawn_options_alone_leave_a_cold_socket_on_the_defaults(
    cold_socket, tmp_path
):
    socket = cold_socket

    pre = _tmux(
        socket,
        "set-option", "-g", "history-limit", str(HISTORY_LIMIT),
        ";",
        "set-option", "-wg", "remain-on-exit", "on",
    )
    assert pre.returncode != 0, (
        "set-option started a tmux server on this build of tmux, which is "
        "the premise of the whole defect. Re-measure before trusting any "
        "other test in this file."
    )
    assert "error connecting" in pre.stderr, pre.stderr

    created = _tmux(
        socket,
        "new-session", "-d", "-s", "cold_control",
        "-c", str(tmp_path), "-x", "100", "-y", "40", LONG_LIVED,
    )
    assert created.returncode == 0, created.stderr

    assert _option(socket, "-gv", "history-limit") == "2000"
    assert _option(socket, "-wgv", "remain-on-exit") == "off"




@pytest.mark.asyncio
async def test_a_launch_on_a_cold_socket_leaves_the_socket_carrying_both_options(
    cold_socket, tmp_path
):
    socket = cold_socket
    backend = await _launch(socket, tmp_path, "cloude_cold_first")
    try:
        assert _option(socket, "-gv", "history-limit") == str(HISTORY_LIMIT), (
            "the socket is still on tmux's stock scrollback depth after a "
            "launch, so every session created on it from here inherits 2000"
        )
        assert _option(socket, "-wgv", "remain-on-exit") == "on"
    finally:
        await backend.stop()


@pytest.mark.asyncio
async def test_remain_on_exit_actually_holds_a_dead_pane_on_a_cold_socket(
    cold_socket, tmp_path
):
    socket = cold_socket
    backend = await _launch(socket, tmp_path, "cloude_cold_corpse")
    try:
        killed = _tmux(socket, "respawn-pane", "-k", "-t", "cloude_cold_corpse",
                       "true")
        assert killed.returncode == 0, killed.stderr

        panes = ""
        for _ in range(40):
            probe = _tmux(socket, "list-panes", "-t", "cloude_cold_corpse",
                          "-F", "#{pane_dead}")
            if probe.returncode != 0:
                break
            panes = probe.stdout.strip()
            if panes == "1":
                break
            time.sleep(0.05)

        assert panes == "1", (
            "the pane did not survive its process exiting, so there is "
            "nothing for the dead-on-arrival probe to read: " + repr(panes)
        )
    finally:
        await backend.stop()




@pytest.mark.asyncio
async def test_a_second_session_on_a_warm_socket_still_gets_both_options(
    cold_socket, tmp_path
):
    socket = cold_socket
    first = await _launch(socket, tmp_path, "cloude_warm_first")
    try:
        second = await _launch(socket, tmp_path, "cloude_warm_second")
        try:
            assert _option(socket, "-gv", "history-limit") == str(HISTORY_LIMIT)
            assert _option(socket, "-wgv", "remain-on-exit") == "on"

            born = _tmux(socket, "display-message", "-p",
                         "-t", "cloude_warm_second", "#{history_limit}")
            assert born.stdout.strip() == str(HISTORY_LIMIT), (
                "a pane born on a warm socket must carry the full depth in "
                "its own grid, which is the only way any pane ever gets it"
            )
        finally:
            await second.stop()
    finally:
        await first.stop()




def test_a_later_set_option_cannot_move_an_existing_panes_scrollback(
    cold_socket, tmp_path
):
    socket = cold_socket
    created = _tmux(
        socket,
        "new-session", "-d", "-s", "cold_grid",
        "-c", str(tmp_path), "-x", "100", "-y", "40", LONG_LIVED,
    )
    assert created.returncode == 0, created.stderr

    def depth() -> str:
        probe = _tmux(socket, "display-message", "-p", "-t", "cold_grid",
                      "#{history_limit}")
        return probe.stdout.strip()

    assert depth() == "2000"

    _tmux(socket, "set-option", "-g", "history-limit", str(HISTORY_LIMIT))
    assert depth() == "2000"

    _tmux(socket, "set-option", "-t", "cold_grid", "history-limit",
          str(HISTORY_LIMIT))
    assert depth() == "2000"

    _tmux(socket, "respawn-pane", "-k", "-t", "cold_grid", LONG_LIVED)
    assert depth() == "2000"
