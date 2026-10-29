
from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import List, Optional, Tuple

import pytest

from src.core.hosts import remote_backend
from src.core.hosts.pipe_stream import tail_script
from src.core.hosts.remote_backend import RemoteTmuxBackend, remote_env, split_commands
from src.core.hosts.remote_host import RemoteHostUnavailable, RemoteSyncOnLoopError
from src.core.hosts.tmux_control import ControlChannelDown, ControlReply
from src.core.hosts.tmux_quote import command_line, escape_expanded
from src.core.tmux_listing import REASON_HOST_UNREACHABLE


class FakeHost:

    host_key = "fakehost"
    tmux_path = "/opt/tmux"
    socket = "carnivore-remote"
    login_path = "/far/bin:/usr/bin"
    command_timeout = 2.0
    is_up = True
    pipe_dir = "/far/home/.cache/carnivore/pipes"

    def __init__(self, loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
        self.loop = loop
        self.sent: List[Tuple[str, ...]] = []
        self.down = False
        self.delay = 0.0

    def pipe_path(self, slug: str) -> str:
        return f"{self.pipe_dir}/5f4cec3f_{slug}.pipe"

    def mirror_path(self, slug: str) -> Path:
        return Path("/nonexistent") / slug

    async def command(self, verb: str, *args: str, timeout: Optional[float] = None) -> ControlReply:
        if self.down:
            raise RemoteHostUnavailable("host fakehost: " + str(ControlChannelDown("channel_closed")))
        command_line(verb, args)
        self.sent.append((verb, *args))
        if self.delay:
            await asyncio.sleep(self.delay)
        return ControlReply(ok=True, lines=(), number=len(self.sent))


def test_escape_expanded_escapes_exactly_the_expanded_positions() -> None:
    evil = "#(touch /tmp/x)"
    lit = "##(touch /tmp/x)"
    assert escape_expanded("new-session", ["-d", "-s", evil, "-c", evil, "-n", evil, "-e",
                                           f"X={evil}", "-x", "80", "sh -c '#(id)'"]) == \
        ["-d", "-s", lit, "-c", lit, "-n", lit, "-e", f"X={evil}", "-x", "80", "sh -c '#(id)'"]
    assert escape_expanded("new-session", ["-ds" + evil]) == ["-ds" + lit]
    assert escape_expanded("new-session", ["-e", "-s", "-s", evil]) == ["-e", "-s", "-s", lit]
    assert escape_expanded("rename-session", ["-t", "old#", evil]) == ["-t", "old#", lit]
    assert escape_expanded("rename-window", ["-t", "w", "--", evil]) == ["-t", "w", "--", lit]
    assert escape_expanded("pipe-pane", ["-t", "s", "-o", f"cat >> '{evil}'"]) == \
        ["-t", "s", "-o", f"cat >> '{lit}'"]
    assert escape_expanded("respawn-pane", ["-k", "-c", evil, "-t", "s", evil]) == \
        ["-k", "-c", lit, "-t", "s", evil]
    for verb, args in [("send-keys", ["-l", "-t", "s", "--", evil]), ("set-buffer", ["-b", "b", evil]),
                       ("set-option", ["-p", "-t", "s", "@o", evil]),
                       ("display-message", ["-p", "#{pane_pid}"]), ("pipe-pane", ["-t", "s"])]:
        assert escape_expanded(verb, args) == args


def test_remote_env_keeps_only_what_a_far_pane_may_have() -> None:
    env = {"CLOUDECODE_SESSION_ID": "ses_1", "CLAUDE_CONFIG_DIR": "/Users/a/.carnivore/x",
           "CLOUDECODE_HOOK_TOKEN": "secret", "CLOUDECODE_HOOK_URL": "http://127.0.0.1:8000",
           "PATH": "/Users/a/bin", "CLAUDE_CODE_DISABLE_ALTERNATE_SCREEN": "1", "LANG": "C.UTF-8",
           "ANTHROPIC_API_KEY": None}
    assert remote_env(env, "/far/bin") == {
        "CLOUDECODE_SESSION_ID": "ses_1", "CLAUDE_CODE_DISABLE_ALTERNATE_SCREEN": "1",
        "LANG": "C.UTF-8", "ANTHROPIC_API_KEY": None, "PATH": "/far/bin"}
    assert remote_env(None, None) == {}


def test_split_commands_and_tail_script() -> None:
    assert split_commands(["a", "x;", ";", "b", ";"]) == [["a", "x;"], ["b"]]
    assert tail_script("/h/it's.pipe", 41).startswith("tail -c +42 -F '/h/it'\"'\"'s.pipe' &")


@pytest.mark.asyncio
async def test_a_batch_is_one_line_per_command_and_expanded_args_are_escaped() -> None:
    host = FakeHost(asyncio.get_running_loop())
    backend = RemoteTmuxBackend(host, "ses_1", Path("/far/home"), session_name="carnivore_x")
    rc, _, _ = await backend._run_tmux("set-option", "-g", "mouse", "on", ";",
                                       "rename-session", "-t", "carnivore_x", "#(id)")
    assert rc == 0
    assert host.sent == [("set-option", "-g", "mouse", "on"),
                         ("rename-session", "-t", "carnivore_x", "##(id)")]
    rc, _, err = await backend._run_tmux("run-shell", "id", check=False)
    assert rc == 1 and b"not a command" in err and host.sent[-1][0] != "run-shell"


@pytest.mark.asyncio
async def test_pid_is_none_and_never_asks_anything(monkeypatch) -> None:
    backend = RemoteTmuxBackend(FakeHost(asyncio.get_running_loop()), "ses_1", Path("/far"))

    def explode(*_a, **_k):
        raise AssertionError("pid must not query tmux or the process table")

    monkeypatch.setattr(backend, "_run_tmux_sync", explode)
    monkeypatch.setattr("src.core.claude_resume_argv.list_process_table", explode)
    assert backend.pid is None


@pytest.mark.asyncio
async def test_a_sync_call_on_the_loop_refuses_and_off_the_loop_bridges() -> None:
    host = FakeHost(asyncio.get_running_loop())
    backend = RemoteTmuxBackend(host, "ses_1", Path("/far"), session_name="carnivore_x")
    with pytest.raises(RemoteSyncOnLoopError):
        backend.capture_scrollback()
    assert await asyncio.to_thread(backend.is_alive) is True
    assert host.sent[-1] == ("has-session", "-t", "=carnivore_x")


@pytest.mark.asyncio
async def test_is_alive_on_the_loop_answers_the_last_measurement_and_remeasures() -> None:
    host = FakeHost(asyncio.get_running_loop())
    backend = RemoteTmuxBackend(host, "ses_1", Path("/far"), session_name="carnivore_x")
    assert backend.is_alive() is False
    await backend._alive_task
    assert host.sent[-1] == ("has-session", "-t", "=carnivore_x")
    assert backend.is_alive() is True


@pytest.mark.asyncio
async def test_an_unreachable_host_lists_as_unavailable_never_empty() -> None:
    host = FakeHost(asyncio.get_running_loop())
    backend = RemoteTmuxBackend(host, "ses_1", Path("/far"))
    host.down = True
    for listing in [await asyncio.to_thread(backend.discover_existing),
                    await asyncio.to_thread(backend.list_pane_status_all)]:
        assert (listing.ok, listing.reason, listing.sessions) == (False, REASON_HOST_UNREACHABLE, [])
    with pytest.raises(RemoteHostUnavailable):
        await backend.is_alive_async()
    host.down = False
    assert backend.discover_existing().ok is False


@pytest.mark.asyncio
async def test_resize_never_blocks_and_sends_only_the_newest_size() -> None:
    host = FakeHost(asyncio.get_running_loop())
    host.delay = 0.2
    backend = RemoteTmuxBackend(host, "ses_1", Path("/far"), session_name="carnivore_x")
    began = asyncio.get_running_loop().time()
    for cols in range(80, 90):
        backend.resize(cols, 30)
    assert asyncio.get_running_loop().time() - began < 0.05
    for _ in range(50):
        await asyncio.sleep(0.01)
        if host.sent:
            break
    worker = threading.Thread(target=backend.resize, args=(120, 40))
    worker.start()
    worker.join()
    for _ in range(100):
        await asyncio.sleep(0.02)
        if backend._resize_task is not None and backend._resize_task.done():
            break
    sizes = [s[3:] for s in host.sent if s[0] == "resize-window"]
    assert sizes == [("-x", "89", "-y", "30"), ("-x", "120", "-y", "40")]


def test_build_backend_dispatches_a_remote_host_without_a_local_probe(monkeypatch) -> None:
    from src.core import session_backend

    def explode(*_a, **_k):
        raise AssertionError("a remote session must never probe this machine's tmux")

    monkeypatch.setattr(session_backend, "probe_tmux", explode)
    backend = session_backend.build_backend(None, "ses_1", Path("/far"), remote_host=FakeHost(),
                                            session_name="carnivore_x", socket_name_override="cloude")
    assert isinstance(backend, remote_backend.RemoteTmuxBackend)
    assert backend.socket_name == "carnivore-remote" and backend.tmux_session == "carnivore_x"
