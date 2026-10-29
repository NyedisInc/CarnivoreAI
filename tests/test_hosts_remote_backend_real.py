
from __future__ import annotations

import asyncio
import os
import shutil
import signal
import tempfile
import time
from pathlib import Path
from typing import AsyncIterator, Callable, List

import pytest
import pytest_asyncio

from src.core.hosts import remote_transport
from src.core.hosts.pipe_stream import STREAMING
from src.core.hosts.remote_backend import make_remote_backend
from src.core.tmux_backend import TmuxBackend
from src.core.hosts.remote_host import RemoteHost, RemoteSyncOnLoopError
from src.core.hosts.ssh_exec import SshDestination
from src.core.hosts.ssh_pool import SshMasterPool
from src.core.hosts.tmux_control import UP, ControlChannelError, TmuxControlChannel
from src.core.tmux_listing import REASON_HOST_UNREACHABLE, REASON_NO_SERVER, classify_listing_failure
from src.core.tmux_listing_parse import CONTROL_SESSION_NAME
from tests.helpers.fake_ssh import FakeSshHost

TMUX = shutil.which("tmux")
SOCKET = "carnivore-remote"
FAST = dict(gate_interval=0.05, linger=0.3, stable_after=0.5, delay=lambda attempt: 0.1)

pytestmark = pytest.mark.skipif(TMUX is None, reason="tmux is not installed")


class Rig:

    def __init__(self, fake: FakeSshHost, pool: SshMasterPool, channel: TmuxControlChannel,
                 host: RemoteHost, mirror_dir: Path) -> None:
        self.fake, self.pool, self.channel, self.host = fake, pool, channel, host
        self.mirror_dir = mirror_dir
        self.output = bytearray()
        self.viewed = True
        self.backends: List[TmuxBackend] = []

    def backend(self, name: str, working_dir: Path | None = None) -> TmuxBackend:
        backend = make_remote_backend(self.host, "ses_" + name, working_dir or self.fake.root / "home",
                                    self.output.extend, session_name=name,
                                    viewer_probe=lambda: self.viewed, stream_options=FAST)
        self.backends.append(backend)
        return backend

    async def wait_for(self, marker: bytes, timeout: float = 15.0) -> None:
        deadline = time.monotonic() + timeout
        while marker not in self.output:
            assert time.monotonic() < deadline, f"{marker!r} never arrived: {bytes(self.output[-600:])!r}"
            await asyncio.sleep(0.05)


async def server_is_gone(pool: SshMasterPool) -> bool:
    result = await pool.run([str(TMUX), "-L", SOCKET, "has-session"], timeout=10)
    return result.returncode != 0 and classify_listing_failure(
        result.returncode, result.stderr_text).reason == REASON_NO_SERVER


async def wait_until(check: Callable[[], bool], timeout: float = 15.0, what: str = "") -> None:
    deadline = time.monotonic() + timeout
    while not check():
        assert time.monotonic() < deadline, f"timed out waiting for {what}"
        await asyncio.sleep(0.05)


@pytest_asyncio.fixture
async def rig() -> AsyncIterator[Rig]:
    fake = FakeSshHost()
    mirror_dir = Path(tempfile.mkdtemp(prefix="s4mirror"))
    pool = SshMasterPool("fakehost", SshDestination("alex@fakehost"), login_shell="/bin/sh",
                         control_dir=fake.control_dir, instance_tag="0123abcd",
                         ssh_binary=fake.ssh_binary, connect_timeout=5.0, check_interval=0.5,
                         delay=lambda attempt: 0.05)
    channel = TmuxControlChannel("fakehost", pool.spawn, str(TMUX), SOCKET, command_timeout=10.0,
                                 connect_timeout=10.0, delay=lambda attempt: 0.05)
    host = RemoteHost("fakehost", pool, channel, tmux_path=str(TMUX), socket=SOCKET,
                      login_path="/usr/bin:/bin:/usr/sbin:/sbin", instance_tag="0123abcd",
                      mirror_dir=mirror_dir, command_timeout=5.0)
    rig = Rig(fake, pool, channel, host, mirror_dir)
    try:
        await pool.connect()
        assert (await channel.start()).state == UP, channel.status
        assert await host.prepare() == str(fake.root / "home")
        yield rig
    finally:
        try:
            for backend in rig.backends:
                if backend._lifecycle._stream is not None:
                    await backend._lifecycle._stream.stop()
                if backend._reader_task is not None:
                    backend._reader_task.cancel()
            await host.close()
            fake.set("scenario", "ok")
            if pool.status.state != UP:
                await pool.connect()
            if channel.is_up:
                try:
                    await channel.command("kill-server", timeout=5)
                except ControlChannelError:
                    pass
            await channel.stop()
            if not await server_is_gone(pool):
                await pool.run([str(TMUX), "-L", SOCKET, "kill-server"], timeout=10)
            assert await server_is_gone(pool), "the fake host's tmux server was left running"
        finally:
            await pool.disconnect()
            fake.cleanup()
            shutil.rmtree(mirror_dir, ignore_errors=True)


def far_file(rig: Rig, backend: TmuxBackend) -> Path:
    path = Path(backend._pipe_write_path())
    assert path.is_relative_to(rig.fake.root / "home" / ".cache" / "carnivore" / "pipes")
    return path


@pytest.mark.asyncio
async def test_the_backend_contract_over_the_control_channel(rig: Rig) -> None:
    backend = rig.backend("carnivore_s4contract")
    await backend.start(env={"CLOUDECODE_SESSION_ID": "ses_s4", "CLAUDE_CONFIG_DIR": "/Users/x/p",
                             "CLOUDECODE_HOOK_TOKEN": "hook-secret"})
    assert await backend.ensure_streaming()
    await backend.write(b"echo mark-$((6*7))\r")
    await rig.wait_for(b"mark-42")
    await backend.write(b'printf "%s|%s|%s\\n" "$CLOUDECODE_SESSION_ID" '
                        b'"${CLAUDE_CONFIG_DIR-unset}" "${CLOUDECODE_HOOK_TOKEN-unset}"\r')
    await rig.wait_for(b"ses_s4|unset|unset")
    shown = await rig.host.command("show-environment", "-t", "carnivore_s4contract", "PATH")
    assert shown.text == "PATH=/usr/bin:/bin:/usr/sbin:/sbin"
    await backend.write(b"echo big-" + b"x" * 400 + b"-end\r")
    await rig.wait_for(b"big-" + b"x" * 400 + b"-end")
    await backend.paste_and_submit("echo pasted-$((2+3))")
    await rig.wait_for(b"pasted-5")
    backend.resize(101, 33)
    await wait_until(lambda: backend._lifecycle._resize_task is not None and backend._lifecycle._resize_task.done(),
                     what="the resize")
    size = await rig.host.command("display-message", "-p", "-t", "carnivore_s4contract",
                                  "#{window_width}x#{window_height}")
    assert size.text == "101x33"
    assert b"mark-42" in await asyncio.to_thread(backend.capture_scrollback)
    assert b"pasted-5" in await asyncio.to_thread(backend.capture_visible_screen)
    with pytest.raises(RemoteSyncOnLoopError):
        backend.capture_scrollback()
    assert backend.pid is None
    assert await asyncio.to_thread(backend.is_alive) and await backend.is_alive_async()
    owned = await asyncio.to_thread(backend.discover_existing)
    assert owned.ok and owned.sessions == ["carnivore_s4contract"]
    raw = await rig.host.command("list-panes", "-a", "-F", "#{session_name}")
    assert CONTROL_SESSION_NAME.encode() in raw.lines
    panes = await asyncio.to_thread(backend.list_pane_status_all)
    assert panes.ok and [row["name"] for row in panes.sessions] == ["carnivore_s4contract"]
    assert all(row["pid"] is None for row in panes.sessions)
    far = far_file(rig, backend)
    assert far.exists() and far.stat().st_mode & 0o077 == 0
    await backend.rename_session("carnivore_s4renamed")
    assert await backend.is_alive_async()
    await backend.stop()
    assert not await backend.is_alive_async()
    assert not far.exists()


@pytest.mark.asyncio
async def test_no_loss_across_a_dead_channel_and_a_dead_master(rig: Rig) -> None:
    backend = rig.backend("carnivore_s4stream")
    await backend.start(command="i=0; while [ $i -lt 300 ]; do echo L$i; i=$((i+1)); "
                                "sleep 0.02; done; echo DONE-300; sleep 300")
    assert await backend.ensure_streaming()
    stream = backend._lifecycle._stream
    assert stream is not None
    start_offset = stream.position
    mirror, far = backend._resolve_pipe_path(), far_file(rig, backend)
    await rig.wait_for(b"L40")
    os.killpg(stream._channel.process.pid, signal.SIGKILL)
    await wait_until(lambda: stream.restarts == 1 and stream.state == STREAMING,
                     what="the stream to restart")
    await rig.wait_for(b"L120")
    await rig.pool.disconnect()
    await wait_until(lambda: not rig.channel.is_up, what="the channel to go down")
    listing = await asyncio.to_thread(backend.discover_existing)
    assert (listing.ok, listing.reason, listing.sessions) == (False, REASON_HOST_UNREACHABLE, [])
    await asyncio.sleep(0.5)
    assert stream.state != STREAMING
    await rig.pool.connect()
    await wait_until(lambda: rig.channel.is_up and stream.state == STREAMING, timeout=30,
                     what="the host to come back")
    await rig.wait_for(b"DONE-300", timeout=30)
    await asyncio.sleep(0.3)
    expected = far.read_bytes()[start_offset:]
    assert b"L41\r\n" in expected and b"L299\r\n" in expected
    assert mirror.read_bytes() == expected
    assert stream.restarts >= 2
    await backend.stop()


@pytest.mark.asyncio
async def test_the_stream_follows_a_far_rotation_and_closes_when_unwatched(rig: Rig) -> None:
    backend = rig.backend("carnivore_s4rotate")
    rig.host._max_pipe_bytes = 2000
    await backend.start()
    assert await backend.ensure_streaming()
    await backend.write(b"i=0; while [ $i -lt 100 ]; do echo fill-$i-........................; "
                        b"i=$((i+1)); done\r")
    await rig.wait_for(b"fill-99-")
    far = far_file(rig, backend)
    assert far.stat().st_size > 2000
    await rig.host.rotate_once()
    assert far.stat().st_size < 2000
    await backend.write(b"echo after-$((40+2))\r")
    await rig.wait_for(b"after-42")
    rig.viewed = False
    await wait_until(lambda: backend._lifecycle._stream.state == "idle", what="the stream to go idle")
    assert backend._lifecycle._stream._channel is None
    await backend.stop()


@pytest.mark.asyncio
async def test_a_hostile_name_directory_and_rename_never_run_on_the_far_box(rig: Rig) -> None:
    marks = Path(tempfile.mkdtemp(dir="/tmp", prefix="s4pwn"))
    try:
        name = f"carnivore_#(touch {marks}/name)"
        backend = rig.backend(name, working_dir=Path(f"/tmp/#(touch {marks}/cwd)"))
        await backend.start()
        await asyncio.sleep(1.5)
        assert list(marks.iterdir()) == []
        await backend.rename_session(f"carnivore_#(touch {marks}/rename)")
        await asyncio.sleep(1.5)
        assert list(marks.iterdir()) == []
        names = (await rig.host.command("list-sessions", "-F", "#{session_name}")).text.split("\n")
        assert f"carnivore_#(touch {marks}/rename)" in names
        await backend.stop()
    finally:
        shutil.rmtree(marks, ignore_errors=True)


@pytest.mark.asyncio
async def test_negative_control_without_the_escape_the_far_box_runs_it(rig: Rig, monkeypatch) -> None:
    monkeypatch.setattr(remote_transport, "escape_expanded", lambda verb, args: list(args))
    marks = Path(tempfile.mkdtemp(dir="/tmp", prefix="s4pwn"))
    try:
        backend = rig.backend("carnivore_s4neg")
        await backend.start()
        await backend.rename_session(f"carnivore_#(touch {marks}/rename)")
        await wait_until(lambda: (marks / "rename").exists(), timeout=10,
                         what="the unescaped #() to run")
    finally:
        shutil.rmtree(marks, ignore_errors=True)
