
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_rpe_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_rpe_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core.tmux_backend import TmuxBackend
from tests.socket_guard import derive_test_socket

pytestmark = pytest.mark.skipif(
    shutil.which("tmux") is None, reason="real tmux binary not available"
)

STALE = "tok_the_pane_was_born_with"
CURRENT = "tok_the_store_holds_now"


def _tmux(socket: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["tmux", "-L", socket, *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )


def _wait_for_file(path: Path, timeout: float = 8.0) -> bool:
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists() and path.read_text().strip():
            return True
        time.sleep(0.1)
    return False


def _wait_for_dead_pane(socket: str, name: str, timeout: float = 8.0) -> bool:
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        got = _tmux(
            socket, "list-panes", "-t", name, "-F", "#{pane_dead}"
        ).stdout.strip()
        if got == "1":
            return True
        time.sleep(0.1)
    return False


@pytest.fixture()
def socket_name():
    name = derive_test_socket("respawn_env")
    try:
        yield name
    finally:
        _tmux(name, "kill-server")


@pytest.mark.asyncio
async def test_the_respawned_process_inherits_the_refreshed_env(
    socket_name, tmp_path
):
    name = f"cloude_rpe_{uuid.uuid4().hex[:6]}"
    marker = tmp_path / "seen_token.txt"

    _tmux(
        socket_name, "new-session", "-d", "-s", name, "-c", str(tmp_path),
        "-x", "80", "-y", "24",
        "-e", f"CLOUDECODE_HOOK_TOKEN={STALE}",
        "-e", "CLOUDECODE_SESSION_ID=ses_before",
    )
    _tmux(socket_name, "set-option", "-t", name, "remain-on-exit", "on")
    _tmux(socket_name, "send-keys", "-t", name, "exit", "Enter")

    if not _wait_for_dead_pane(socket_name, name):
        pytest.skip("setup: the pane never reached a dead state")

    backend = TmuxBackend.for_external(
        session_name=name,
        working_dir=tmp_path,
        on_output=None,
        socket_name=socket_name,
    )

    probe = tmp_path / "probe.sh"
    probe.write_text(
        "#!/bin/sh\n"
        f'printf %s "$CLOUDECODE_HOOK_TOKEN" > {marker}\n'
        "sleep 30\n"
    )

    result = await backend.respawn(
        chosen_agent_command=f"sh {probe}",
        chosen_agent_type="probe",
        spawn_env={
            "CLOUDECODE_HOOK_TOKEN": CURRENT,
            "CLOUDECODE_SESSION_ID": "ses_after",
        },
    )

    assert result.ok is True, result.detail
    assert _wait_for_file(marker), (
        "the respawned command never wrote its token; nothing can be "
        "concluded about what it inherited"
    )
    seen = marker.read_text().strip()
    assert seen == CURRENT, (
        f"the restarted process inherited {seen!r}; the environment was "
        f"not refreshed before the spawn"
    )
    assert seen != STALE


@pytest.mark.asyncio
async def test_the_session_environment_itself_is_updated(
    socket_name, tmp_path
):
    name = f"cloude_rpe_{uuid.uuid4().hex[:6]}"
    _tmux(
        socket_name, "new-session", "-d", "-s", name, "-c", str(tmp_path),
        "-x", "80", "-y", "24",
        "-e", f"CLOUDECODE_HOOK_TOKEN={STALE}",
    )
    _tmux(socket_name, "set-option", "-t", name, "remain-on-exit", "on")
    _tmux(socket_name, "send-keys", "-t", name, "exit", "Enter")
    if not _wait_for_dead_pane(socket_name, name):
        pytest.skip("setup: the pane never reached a dead state")

    backend = TmuxBackend.for_external(
        session_name=name,
        working_dir=tmp_path,
        on_output=None,
        socket_name=socket_name,
    )
    await backend.respawn(
        agent_command="sh -c 'sleep 30'",
        spawn_env={"CLOUDECODE_HOOK_TOKEN": CURRENT},
    )

    env = _tmux(socket_name, "show-environment", "-t", name).stdout
    assert f"CLOUDECODE_HOOK_TOKEN={CURRENT}" in env
    assert f"CLOUDECODE_HOOK_TOKEN={STALE}" not in env


@pytest.mark.asyncio
async def test_no_spawn_env_leaves_the_pane_environment_alone(
    socket_name, tmp_path
):
    name = f"cloude_rpe_{uuid.uuid4().hex[:6]}"
    _tmux(
        socket_name, "new-session", "-d", "-s", name, "-c", str(tmp_path),
        "-x", "80", "-y", "24",
        "-e", f"CLOUDECODE_HOOK_TOKEN={STALE}",
    )
    _tmux(socket_name, "set-option", "-t", name, "remain-on-exit", "on")
    _tmux(socket_name, "send-keys", "-t", name, "exit", "Enter")
    if not _wait_for_dead_pane(socket_name, name):
        pytest.skip("setup: the pane never reached a dead state")

    backend = TmuxBackend.for_external(
        session_name=name,
        working_dir=tmp_path,
        on_output=None,
        socket_name=socket_name,
    )
    await backend.respawn(agent_command="sh -c 'sleep 30'")

    env = _tmux(socket_name, "show-environment", "-t", name).stdout
    assert f"CLOUDECODE_HOOK_TOKEN={STALE}" in env, (
        "a restart with no spawn_env changed the pane's environment"
    )
