
from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import tempfile

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_born_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_born_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core.tmux_transport import local as local_transport
from src.core.tmux_backend import HISTORY_LIMIT, TmuxBackend
from src.core.tmux_server_config import (
    SERVER_CONFIG_FILENAME,
    render_config,
    render_config_line,
    write_server_config,
)
from tests.socket_guard import derive_test_socket

pytestmark = pytest.mark.skipif(
    shutil.which("tmux") is None, reason="real tmux binary not available"
)

LONG_LIVED = "sleep 120"

STOCK_HISTORY_LIMIT = "2000"

COLD_LAUNCH_TMUX_PROCESSES = 8


def _tmux(socket: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["tmux", "-L", socket, *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )


def _pane_depth(socket: str, name: str) -> str:
    probe = _tmux(socket, "display-message", "-p", "-t", name, "#{history_limit}")
    if probe.returncode != 0:
        return ""
    return probe.stdout.strip()


@pytest.fixture()
def cold_socket(request):
    socket = derive_test_socket(f"born_{request.node.name[:16]}")
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




def test_a_command_renders_as_the_line_you_would_type():
    assert render_config_line(
        ("set-option", "-g", "history-limit", "50000")
    ) == "set-option -g history-limit 50000"


def test_a_token_that_would_change_the_parse_is_refused():
    assert render_config_line(("set-option", "-g", "a b")) is None
    assert render_config_line(("set-option", "-g", 'a"b')) is None
    assert render_config_line(("set-option", "-g", "a#b")) is None
    assert render_config_line(("set-option", "-g", "a;b")) is None
    assert render_config_line(()) is None


def test_one_unrenderable_command_refuses_the_whole_file():
    assert render_config([("set-option", "-g", "mouse", "on")]) == (
        "set-option -g mouse on\n"
    )
    assert render_config(
        [("set-option", "-g", "mouse", "on"), ("set-option", "-g", "a b")]
    ) is None
    assert render_config([]) is None


def test_an_unwritable_directory_answers_none_rather_than_raising(tmp_path):
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    blocked.chmod(0o500)
    try:
        assert write_server_config(
            blocked, [("set-option", "-g", "mouse", "on")]
        ) is None
    finally:
        blocked.chmod(0o700)


def test_the_write_is_atomic_and_leaves_no_temp_file_behind(tmp_path):
    written = write_server_config(
        tmp_path,
        [("set-option", "-g", "history-limit", str(HISTORY_LIMIT))],
    )
    assert written == tmp_path / SERVER_CONFIG_FILENAME
    assert written.read_text(encoding="utf-8") == (
        f"set-option -g history-limit {HISTORY_LIMIT}\n"
    )
    assert [p.name for p in tmp_path.iterdir()] == [SERVER_CONFIG_FILENAME]




def test_a_cold_socket_without_the_config_is_born_on_the_stock_depth(
    cold_socket, tmp_path
):
    socket = cold_socket
    created = _tmux(
        socket,
        "new-session", "-d", "-s", "born_control",
        "-c", str(tmp_path), "-x", "100", "-y", "40", LONG_LIVED,
    )
    assert created.returncode == 0, created.stderr
    assert _pane_depth(socket, "born_control") == STOCK_HISTORY_LIMIT


@pytest.mark.asyncio
async def test_the_first_pane_on_a_cold_socket_is_born_at_the_full_depth(
    cold_socket, tmp_path
):
    socket = cold_socket
    backend = await _launch(socket, tmp_path, "cloude_born_first")
    try:
        assert _pane_depth(socket, "cloude_born_first") == str(HISTORY_LIMIT), (
            "the first pane on a cold socket is still carrying tmux's stock "
            "scrollback depth, so this session holds 48000 fewer lines of "
            "history than every other session on the box"
        )
    finally:
        await backend.stop()


@pytest.mark.asyncio
async def test_a_second_session_on_a_warm_socket_is_still_born_at_the_full_depth(
    cold_socket, tmp_path
):
    socket = cold_socket
    first = await _launch(socket, tmp_path, "cloude_born_warm_a")
    try:
        second = await _launch(socket, tmp_path, "cloude_born_warm_b")
        try:
            assert _pane_depth(socket, "cloude_born_warm_b") == str(HISTORY_LIMIT)
        finally:
            await second.stop()
    finally:
        await first.stop()


@pytest.mark.asyncio
async def test_a_config_that_cannot_be_written_still_launches_a_session(
    cold_socket, tmp_path, monkeypatch
):
    socket = cold_socket
    monkeypatch.setattr(
        local_transport, "write_server_config", lambda *_a, **_k: None
    )
    backend = await _launch(socket, tmp_path, "cloude_born_nofile")
    try:
        assert _tmux(socket, "has-session", "-t", "cloude_born_nofile").returncode == 0
        assert _pane_depth(socket, "cloude_born_nofile") == STOCK_HISTORY_LIMIT
    finally:
        await backend.stop()




@pytest.mark.asyncio
async def test_the_launch_spends_no_extra_tmux_process(cold_socket, tmp_path):
    socket = cold_socket
    spawned: list = []
    stdin_scripts: list = []
    original_async = asyncio.create_subprocess_exec
    original_sync = subprocess.run

    async def counting_async(*args, **kwargs):
        spawned.append(args)
        return await original_async(*args, **kwargs)

    def counting_sync(*args, **kwargs):
        argv = tuple(args[0])
        spawned.append(argv)
        stdin_scripts.append((argv, kwargs.get("input")))
        return original_sync(*args, **kwargs)

    asyncio.create_subprocess_exec = counting_async
    subprocess.run = counting_sync
    try:
        backend = await _launch(socket, tmp_path, "cloude_born_count")
    finally:
        asyncio.create_subprocess_exec = original_async
        subprocess.run = original_sync

    try:
        tmux_calls = [a for a in spawned if a and str(a[0]).endswith("tmux")]
        assert len(tmux_calls) <= COLD_LAUNCH_TMUX_PROCESSES, (
            "the launch grew a tmux process. -f is supposed to be two argv "
            f"elements on a call already being made: {len(tmux_calls)} calls "
            f"against a measured ceiling of {COLD_LAUNCH_TMUX_PROCESSES}"
        )
        with_config = [a for a in tmux_calls if "-f" in a]
        assert len(with_config) == 1, (
            "-f must ride on exactly one invocation, the spawn: "
            f"{len(with_config)}"
        )
        spawn = with_config[0]
        assert spawn[spawn.index("-f") - 1] == socket, (
            "-f must sit among the server options, after -L <socket> and "
            "before the command word, which is where tmux requires it"
        )
        assert "start-server" in spawn and "source-file" in spawn
        assert spawn.index("-f") < spawn.index("start-server")
        assert "new-session" not in spawn, "the private command must stay off argv"
        scripts = [script for argv, script in stdin_scripts if argv == spawn]
        assert len(scripts) == 1 and b"new-session" in scripts[0]
    finally:
        await backend.stop()


@pytest.mark.asyncio
async def test_concurrent_launches_on_a_cold_socket_all_start_at_full_depth(
    cold_socket, tmp_path
):
    socket = cold_socket
    names = [f"cloude_born_par_{i}" for i in range(4)]
    started = await asyncio.gather(
        *(_launch(socket, tmp_path, name) for name in names), return_exceptions=True
    )
    try:
        failures = [s for s in started if isinstance(s, BaseException)]
        assert not failures, f"a concurrent cold launch failed: {failures!r}"
        assert {_pane_depth(socket, name) for name in names} == {str(HISTORY_LIMIT)}
    finally:
        for backend in started:
            if isinstance(backend, TmuxBackend):
                await backend.stop()
