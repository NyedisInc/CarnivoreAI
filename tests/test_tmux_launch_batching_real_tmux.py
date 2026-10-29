
from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_lb_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_lb_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core.tmux_backend import TmuxBackend
from src.core.tmux_command_batch import (
    build_batch_argv,
    environment_commands,
    run_optional_batch,
)
from tests.socket_guard import TEST_SOCKET_NAME

requires_tmux = pytest.mark.skipif(
    shutil.which("tmux") is None, reason="tmux not on PATH"
)


def _tmux(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["tmux", "-L", TEST_SOCKET_NAME, *args],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture()
def scratch_session(tmp_path):
    name = f"cloude_lb_{uuid.uuid4().hex[:8]}"
    result = _tmux("new-session", "-d", "-s", name, "-c", str(tmp_path),
                   "-x", "100", "-y", "40")
    assert result.returncode == 0, f"tmux new-session failed: {result.stderr}"
    backend = TmuxBackend(
        session_id=name,
        working_dir=tmp_path,
        socket_name=TEST_SOCKET_NAME,
        session_name=name,
    )
    try:
        yield backend, name
    finally:
        _tmux("kill-session", "-t", name)




def test_the_builder_separates_commands_with_a_standalone_semicolon():
    assert build_batch_argv([
        ("set-option", "-g", "mouse", "on"),
        ("set-option", "-s", "escape-time", "0"),
    ]) == [
        "set-option", "-g", "mouse", "on", ";",
        "set-option", "-s", "escape-time", "0",
    ]


def test_a_semicolon_inside_a_token_is_carried_through_untouched():
    inner = "copy-mode -e ; send-keys -X -N 3 scroll-up"
    argv = build_batch_argv([("bind-key", "-T", "root", "X", inner)])
    assert inner in argv
    assert argv.count(";") == 0


def test_a_token_that_would_split_the_batch_is_refused():
    with pytest.raises(ValueError):
        build_batch_argv([("set-option", "-g", "mouse;"), ("kill-server",)])
    with pytest.raises(ValueError):
        build_batch_argv([("set-option", ";"), ("kill-server",)])


def test_the_environment_builder_makes_one_command_per_pair():
    assert environment_commands("cloude_x", {"A": "1", "B": "2"}) == [
        ("set-environment", "-t", "cloude_x", "A", "1"),
        ("set-environment", "-t", "cloude_x", "B", "2"),
    ]
    assert environment_commands("cloude_x", None) == []
    assert environment_commands("cloude_x", {}) == []




@requires_tmux
def test_every_command_in_a_real_batch_actually_lands(scratch_session):
    backend, name = scratch_session
    _tmux("set-option", "-g", "mouse", "off")

    outcome = asyncio.run(run_optional_batch(
        backend._run_tmux,
        [
            ("set-option", "-g", "mouse", "on"),
            ("set-option", "-s", "escape-time", "0"),
            ("set-option", "-t", name, "window-size", "manual"),
            ("bind-key", "-T", "root", "WheelUpPane",
             "if-shell", "-Ft=", "#{alternate_on}",
             "copy-mode -e ; send-keys -X -N 3 scroll-up",
             "send-keys -M"),
        ],
        note="test_batch",
    ))
    assert outcome.batched is True
    assert outcome.failures == ()

    assert _tmux("show-options", "-g", "mouse").stdout.strip() == "mouse on"
    assert _tmux("show-options", "-s", "escape-time").stdout.strip() == "escape-time 0"
    assert _tmux(
        "show-options", "-t", name, "window-size"
    ).stdout.strip() == "window-size manual"
    assert _tmux("list-keys", "-T", "root", "WheelUpPane").stdout.strip()


@requires_tmux
def test_a_failing_batch_aborts_the_rest_and_the_runner_repairs_it(scratch_session):
    backend, name = scratch_session
    _tmux("set-option", "-g", "mouse", "off")

    outcome = asyncio.run(run_optional_batch(
        backend._run_tmux,
        [
            ("set-option", "-g", "no-such-option-xyz", "on"),
            ("set-option", "-g", "mouse", "on"),
        ],
        note="test_broken_batch",
    ))

    assert outcome.batched is False
    assert len(outcome.failures) == 1
    argv, rc, stderr = outcome.failures[0]
    assert argv == ("set-option", "-g", "no-such-option-xyz", "on")
    assert rc != 0
    assert "no-such-option-xyz" in stderr

    assert _tmux("show-options", "-g", "mouse").stdout.strip() == "mouse on"


@requires_tmux
def test_a_single_command_group_still_reports_its_failure(scratch_session):
    backend, _ = scratch_session
    outcome = asyncio.run(run_optional_batch(
        backend._run_tmux,
        [("set-option", "-g", "no-such-option-xyz", "on")],
        note="test_single",
    ))
    assert outcome.batched is False
    assert len(outcome.failures) == 1
    assert outcome.failures[0][0] == ("set-option", "-g", "no-such-option-xyz", "on")




@requires_tmux
def test_a_batched_environment_write_still_precedes_the_spawn(tmp_path):
    name = f"cloude_lb_{uuid.uuid4().hex[:8]}"
    marker = tmp_path / "inherited.txt"
    backend = TmuxBackend(
        session_id=name,
        working_dir=tmp_path,
        socket_name=TEST_SOCKET_NAME,
        session_name=name,
    )
    target = name
    spawn_env = {
        "CLOUDECODE_SESSION_ID": "ses_batched_ordering",
        "CLOUDECODE_HOOK_TOKEN": "tok_batched_ordering",
    }

    async def scenario():
        result = _tmux("new-session", "-d", "-s", name, "-c", str(tmp_path))
        assert result.returncode == 0, result.stderr

        outcome = await run_optional_batch(
            backend._run_tmux,
            environment_commands(target, spawn_env),
            note="test_env_ordering",
        )
        assert outcome.batched is True, outcome.failures

        command = (
            f"sh -c 'printf \"%s %s\" "
            f"\"$CLOUDECODE_SESSION_ID\" \"$CLOUDECODE_HOOK_TOKEN\" "
            f"> {marker}; sleep 30'"
        )
        rc, _, err = await backend._run_tmux(
            "respawn-pane", "-k", "-t", target, command, check=False,
        )
        assert rc == 0, err.decode()

    try:
        asyncio.run(scenario())
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if marker.exists() and marker.read_text().strip():
                break
            time.sleep(0.05)
        written = marker.read_text().strip() if marker.exists() else ""
    finally:
        _tmux("kill-session", "-t", name)

    assert written == "ses_batched_ordering tok_batched_ordering", (
        "the pane did not inherit the batched environment, which means the "
        "set-environment writes no longer complete before the spawn"
    )


@requires_tmux
def test_a_real_start_injects_the_environment_into_its_own_pane(tmp_path):
    name = f"cloude_lb_{uuid.uuid4().hex[:8]}"
    marker = tmp_path / "start_inherited.txt"
    backend = TmuxBackend(
        session_id=name,
        working_dir=tmp_path,
        socket_name=TEST_SOCKET_NAME,
        session_name=name,
    )
    command = (
        f"sh -c 'printf \"%s\" \"$CLOUDECODE_SESSION_ID\" > {marker}; sleep 30'"
    )

    try:
        asyncio.run(backend.start(
            command=command,
            env={"CLOUDECODE_SESSION_ID": "ses_start_batched"},
        ))
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if marker.exists() and marker.read_text().strip():
                break
            time.sleep(0.05)
        written = marker.read_text().strip() if marker.exists() else ""

        assert _tmux(
            "show-options", "-t", name, "window-size"
        ).stdout.strip() == "window-size manual"
    finally:
        asyncio.run(backend.stop())
        _tmux("kill-session", "-t", name)

    assert written == "ses_start_batched", (
        "the pane launched by start() did not inherit CLOUDECODE_SESSION_ID"
    )
