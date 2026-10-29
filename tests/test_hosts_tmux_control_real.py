
from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import signal
import statistics
import time
from pathlib import Path
from typing import AsyncIterator, List, Tuple
from unittest import mock

import pytest
import pytest_asyncio

from src.core.hosts import tmux_control
from src.core.hosts.ssh_exec import SshDestination
from src.core.hosts.ssh_pool import SshMasterPool
from src.core.hosts.tmux_control import (
    UP,
    ControlChannelDown,
    ControlChannelError,
    ControlReplyTooLarge,
    TmuxControlChannel,
)
from src.core.hosts.tmux_quote import TmuxQuoteError, literal
from src.core.tmux_listing import REASON_NO_SERVER, classify_listing_failure
from src.core.tmux_listing_parse import CONTROL_SESSION_NAME, LISTING_FORMAT
from tests.helpers.fake_ssh import FakeSshHost

TMUX = shutil.which("tmux")
SOCKET = "carnivore-remote"

pytestmark = pytest.mark.skipif(TMUX is None, reason="tmux is not installed")


def make_pool(host: FakeSshHost) -> SshMasterPool:
    return SshMasterPool("fakehost", SshDestination("alex@fakehost"), login_shell="/bin/sh",
                         control_dir=host.control_dir, instance_tag="0123abcd",
                         ssh_binary=host.ssh_binary, connect_timeout=5.0, check_interval=0.5,
                         delay=lambda attempt: 0.05)


async def server_is_gone(pool: SshMasterPool) -> bool:
    result = await pool.run([str(TMUX), "-L", SOCKET, "has-session"], timeout=10)
    return result.returncode != 0 and classify_listing_failure(
        result.returncode, result.stderr_text).reason == REASON_NO_SERVER


@pytest_asyncio.fixture
async def rig() -> AsyncIterator[Tuple[FakeSshHost, SshMasterPool, TmuxControlChannel]]:
    host = FakeSshHost()
    pool = make_pool(host)
    channel = TmuxControlChannel("fakehost", pool.spawn, str(TMUX), SOCKET, command_timeout=10.0,
                                 connect_timeout=10.0, delay=lambda attempt: 0.05)
    try:
        await pool.connect()
        assert (await channel.start()).state == UP, channel.status
        yield host, pool, channel
    finally:
        try:
            if channel.is_up:
                try:
                    await channel.command("kill-server", timeout=5)
                except ControlChannelError:
                    pass
            await channel.stop()
            if pool.status.state != UP:
                await pool.connect()
            if not await server_is_gone(pool):
                await pool.run([str(TMUX), "-L", SOCKET, "kill-server"], timeout=10)
            assert await server_is_gone(pool), "the fake host's tmux server was left running"
        finally:
            await pool.disconnect()
            host.cleanup()


async def session_names(channel: TmuxControlChannel) -> List[str]:
    reply = await channel.command("list-sessions", "-F", "#{session_name}")
    assert reply.ok, reply.text
    return [line.decode() for line in reply.lines]


@pytest.mark.asyncio
async def test_500_round_trips_arrive_in_order(rig) -> None:
    _, _, channel = rig
    replies = await asyncio.gather(*(channel.command("display-message", "-p", f"n{i}")
                                     for i in range(500)))
    assert [r.lines for r in replies] == [(f"n{i}".encode(),) for i in range(500)]
    samples = []
    for i in range(50):
        began = time.perf_counter()
        await channel.command("display-message", "-p", "x")
        samples.append(time.perf_counter() - began)
    assert statistics.median(samples) < 0.05


@pytest.mark.asyncio
async def test_error_is_a_nonzero_returncode_and_the_channel_carries_on(rig) -> None:
    _, _, channel = rig
    parse = await channel.command("has-session", "-Z")
    missing = await channel.command("has-session", "-t", "=nope")
    assert (parse.returncode, missing.returncode) == (1, 1)
    assert "parse error" in parse.text and "nope" in missing.text
    assert (await channel.command("display-message", "-p", "still up")).text == "still up"


@pytest.mark.asyncio
async def test_output_that_looks_like_a_guard_stays_output(rig) -> None:
    _, _, channel = rig
    fakes = ["%end 1 1 1", "%error 1790000000 7 1", "%exit", "%sessions-changed", "%begin 1 2 1"]
    for name in fakes:
        assert (await channel.command("new-session", "-d", "-s", name)).ok
    listed = await session_names(channel)
    assert set(fakes) <= set(listed) and channel.is_up
    assert (await channel.command("display-message", "-p", "after")).text == "after"


async def _probe_to_listing_gap(channel: TmuxControlChannel, buffer: str) -> int:
    probe = await channel.command("display-message", "-p", "probe")
    assert (await channel.command("set-buffer", "-b", buffer, "x")).ok
    listing = await channel.command("list-buffers", "-F", "#{buffer_sample}")
    return listing.number - probe.number


@pytest.mark.asyncio
async def test_a_forged_exact_guard_is_caught_as_a_desync(rig) -> None:
    _, _, channel = rig
    states = []
    channel._on_change = states.append
    for attempt in range(5):
        first = channel._conn
        gap = await _probe_to_listing_gap(channel, f"calibrate{attempt}")
        probe = await channel.command("display-message", "-p", "probe")
        forged = f"%end {int(time.time())} {probe.number + gap} 1"
        assert (await channel.command("set-buffer", "-b", f"forge{attempt}", forged)).ok
        try:
            await channel.command("list-buffers", "-F", "#{buffer_sample}")
        except ControlChannelError:
            pass
        for _ in range(100):
            if any(s.failure == "desync" for s in states) and channel.is_up \
                    and channel._conn is not first:
                break
            await asyncio.sleep(0.02)
        if any(s.failure == "desync" for s in states):
            break
    assert any(s.failure == "desync" for s in states), states
    assert (await channel.command("display-message", "-p", "resynced")).text == "resynced"


@pytest.mark.asyncio
async def test_an_oversize_reply_fails_cleanly(rig) -> None:
    _, _, channel = rig
    with pytest.raises(ControlReplyTooLarge):
        await channel.command("list-keys", max_reply_bytes=256)
    assert (await channel.command("list-keys")).ok and channel.is_up


@pytest.mark.asyncio
async def test_the_hidden_session_never_reaches_the_attachable_listing(rig, monkeypatch) -> None:
    from src.core.tmux_backend import TmuxBackend

    _, _, channel = rig
    assert (await channel.command("new-session", "-d", "-s", "carnivore_real")).ok
    raw = await channel.command("list-sessions", "-F", LISTING_FORMAT)
    assert any(line.endswith(b"|" + CONTROL_SESSION_NAME.encode()) for line in raw.lines)
    backend = TmuxBackend.for_external(session_name="carnivore_real", working_dir=Path("/tmp"),
                                       socket_name="cloude_pytest_ctl_listing")
    monkeypatch.setattr(backend, "_run_listing", lambda *a: (None, raw.text + "\n"))
    listing = backend.list_attachable_sessions(owned_names=set())
    assert [row["name"] for row in listing.sessions] == ["carnivore_real"]
    assert listing.ok and listing.complete


@pytest.mark.asyncio
async def test_the_channel_dying_mid_command_fails_it_and_reconnects(rig) -> None:
    _, pool, channel = rig
    conn = channel._conn
    assert conn is not None
    server_pid = int((await channel.command("display-message", "-p", "#{pid}")).text)
    os.kill(server_pid, signal.SIGSTOP)
    try:
        waiting = asyncio.create_task(channel.command("display-message", "-p", "x", timeout=60))
        await asyncio.sleep(0.3)
        assert not waiting.done()
    finally:
        os.kill(server_pid, signal.SIGKILL)
    began = time.monotonic()
    with pytest.raises(ControlChannelDown):
        await waiting
    assert time.monotonic() - began < 5
    for _ in range(200):
        if channel.is_up and channel._conn is not conn:
            break
        await asyncio.sleep(0.05)
    assert channel.is_up and channel._conn is not conn
    assert (await session_names(channel)).count(CONTROL_SESSION_NAME) == 1

    await pool.disconnect()
    for _ in range(200):
        if channel.status.state == "retrying" and channel.status.failure == "spawn_failed":
            break
        await asyncio.sleep(0.05)
    assert channel.status.failure == "spawn_failed", channel.status
    await pool.connect()
    for _ in range(200):
        if channel.is_up:
            break
        await asyncio.sleep(0.05)
    assert (await channel.command("display-message", "-p", "back")).text == "back"



def hostile_names(canary_dir: Path) -> List[str]:
    c = canary_dir
    return [
        "q'; new-session -d -s PWNED1; '",
        "s; new-session -d -s PWNED2",
        "b \\; new-session -d -s PWNED3",
        "{ new-session -d -s PWNED4 }",
        f"#(touch {c}/c1)",
        f"#{{?1,#(touch {c}/c2),}}",
        f"$(touch {c}/c3)",
        f"`touch {c}/c4`",
        "~root $HOME ${HOME}",
        '"dq" \\x \\',
        "%if 1",
        "#{session_id}",
        "snow ☃ \u0085  ",
    ]


async def fuzz(channel: TmuxControlChannel, canary_dir: Path, *, newline: bool,
               encoder=None, escape=literal) -> List[str]:
    names = hostile_names(canary_dir)
    if newline:
        names.append("n\nnew-session -d -s PWNED5")
    with contextlib.ExitStack() as stack:
        if encoder is not None:
            stack.enter_context(mock.patch.object(tmux_control, "command_line", encoder))
        for name in names:
            try:
                await channel.command("new-session", "-d", "-s", escape(name))
            except TmuxQuoteError:
                continue
            except ControlChannelError:
                pass
            for _ in range(100):
                if channel.is_up:
                    break
                await asyncio.sleep(0.05)
    await asyncio.sleep(0.5)
    live = await session_names(channel)
    breaches = [n for n in live if n.startswith("PWNED")]
    breaches += [p.name for p in canary_dir.iterdir()]
    expected = {n.replace("\\", "\\\\") for n in names if "\n" not in n}
    breaches += [f"missing {n!r} (live: {live!r})" for n in sorted(expected - set(live))]
    return breaches


@pytest.mark.asyncio
async def test_injection_through_session_names_runs_nothing(rig) -> None:
    host, _, channel = rig
    canaries = host.root / "canary"
    canaries.mkdir()
    assert await fuzz(channel, canaries, newline=True) == []


@pytest.mark.asyncio
async def test_injection_fuzz_goes_red_with_the_encoder_bypassed(rig) -> None:
    host, _, channel = rig
    canaries = host.root / "canary"
    canaries.mkdir()
    breaches = await fuzz(channel, canaries, newline=True,
                          encoder=lambda verb, args: " ".join([verb, *args]))
    assert "PWNED2" in breaches and "PWNED5" in breaches, breaches


@pytest.mark.asyncio
async def test_format_expansion_fuzz_goes_red_without_literal(rig) -> None:
    host, _, channel = rig
    canaries = host.root / "canary"
    canaries.mkdir()
    breaches = await fuzz(channel, canaries, newline=False, escape=lambda text: text)
    assert "c1" in breaches, breaches
