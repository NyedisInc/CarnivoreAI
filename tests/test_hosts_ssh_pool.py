
from __future__ import annotations

import asyncio
import os
import signal
from pathlib import Path
from typing import Iterator

import pytest

from src.core.hosts.ssh_exec import SshDestination, argv_command, mux_argv, run_process
from src.core.hosts.ssh_pool import (
    ChannelBudgetExhausted,
    HostNotConnected,
    ShellNotVerified,
    SshMasterPool,
)
from tests.helpers.fake_ssh import FakeSshHost, fake_ssh_host_fixture

DEST = SshDestination("acme@fakehost")


@pytest.fixture
def host() -> Iterator[FakeSshHost]:
    yield from fake_ssh_host_fixture()


def make_pool(host: FakeSshHost, **options) -> SshMasterPool:
    settings = dict(login_shell="/bin/sh", control_dir=host.control_dir, instance_tag="5f4cec3f",
                    ssh_binary=host.ssh_binary, connect_timeout=5.0, check_interval=0.5,
                    delay=lambda attempt: 0.05, idle_slot_linger=0.2)
    settings.update(options)
    return SshMasterPool("fakehost", DEST, **settings)


def hostile_words(canary: Path) -> list:
    return ["it's", '"', f"$(touch {canary})", f"`touch {canary}`", f"; touch {canary}",
            "a b", "\n", "*", "~", "=ls", "-n", "$HOME", "\\", ""]


@pytest.mark.asyncio
async def test_run_delivers_hostile_arguments_verbatim(host: FakeSshHost, tmp_path: Path) -> None:
    canary = tmp_path / "ran"
    pool = make_pool(host)
    try:
        await pool.connect()
        words = hostile_words(canary)
        result = await pool.run(["printf", "%s\\0", *words])
        assert result.ok, result.stderr_text
        assert result.stdout.split(b"\0")[:-1] == [w.encode() for w in words]
        assert not canary.exists()
        assert host.calls("mux") and not host.calls("direct_fallback")

        await pool.run(script="printf %s " + " ".join(words[2:3]))
        assert canary.exists()
    finally:
        await pool.disconnect()


@pytest.mark.asyncio
async def test_run_feeds_stdin_and_keeps_stderr(host: FakeSshHost) -> None:
    pool = make_pool(host)
    try:
        await pool.connect()
        result = await pool.run(script="cat; echo warn >&2; exit 4", stdin_data=b"payload")
        assert (result.returncode, result.stdout, result.stderr) == (4, b"payload", b"warn\n")
    finally:
        await pool.disconnect()


@pytest.mark.asyncio
async def test_channels_are_counted_and_spill_to_a_second_master(host: FakeSshHost) -> None:
    pool = make_pool(host, channel_budget=2)
    try:
        await pool.connect()
        channels = [await pool.spawn(["cat"]) for _ in range(3)]
        assert pool.usage() == {0: 2, 1: 1}
        assert [c.slot for c in channels] == [0, 0, 1]
        assert len(host.calls("master")) == 2 and len(host.master_pids()) == 2
        channels[2].process.stdin.write(b"ping\n")
        await channels[2].process.stdin.drain()
        assert await asyncio.wait_for(channels[2].process.stdout.readline(), 5) == b"ping\n"
        for channel in channels:
            await channel.close()
        await asyncio.sleep(0.6)
        assert pool.usage() == {0: 0}
        assert len(host.master_pids()) == 1, "the empty extra master was not closed"
    finally:
        await pool.disconnect()


@pytest.mark.asyncio
async def test_a_channel_that_ends_by_itself_is_uncounted(host: FakeSshHost) -> None:
    pool = make_pool(host, channel_budget=1, max_slots=1)
    try:
        await pool.connect()
        channel = await pool.spawn(["true"])
        assert await asyncio.wait_for(channel.process.wait(), 5) == 0
        await asyncio.sleep(0.05)
        assert pool.usage() == {0: 0}
        second = await pool.spawn(["true"])
        await asyncio.wait_for(second.process.wait(), 5)
    finally:
        await pool.disconnect()


@pytest.mark.asyncio
async def test_a_full_pool_is_refused_by_name(host: FakeSshHost) -> None:
    pool = make_pool(host, channel_budget=1, max_slots=2)
    try:
        await pool.connect()
        await pool.spawn(["sleep", "30"])
        await pool.spawn(["sleep", "30"])
        with pytest.raises(ChannelBudgetExhausted):
            await pool.spawn(["sleep", "30"])
        assert pool.usage() == {0: 1, 1: 1}
    finally:
        await pool.disconnect()


@pytest.mark.asyncio
async def test_a_command_never_falls_back_to_a_direct_connection(
        host: FakeSshHost, tmp_path: Path) -> None:
    canary = tmp_path / "ran"
    pool = make_pool(host)
    await pool.connect()
    path = pool._slots[0].master.control_path
    os.kill(pool.status.pid, signal.SIGKILL)
    try:
        command = argv_command(["touch", str(canary)])
        argv = mux_argv(DEST, path, command, ssh_binary=host.ssh_binary)
        result = await run_process(argv, timeout=10)
        assert result.returncode == 255 and not canary.exists()
        assert host.calls("mux_refused") and not host.calls("direct_fallback")

        at = argv.index("ProxyCommand=false")
        await run_process(argv[:at - 1] + argv[at + 1:], timeout=10)
        assert canary.exists() and host.calls("direct_fallback")
    finally:
        await pool.disconnect()


@pytest.mark.asyncio
async def test_nothing_is_sent_to_a_host_whose_shell_is_not_measured(host: FakeSshHost) -> None:
    for shell in (None, "/usr/local/bin/fish", "/bin/csh"):
        pool = make_pool(host, login_shell=shell)
        try:
            await pool.connect()
            with pytest.raises(ShellNotVerified):
                await pool.run(["true"])
            with pytest.raises(ShellNotVerified):
                await pool.spawn(["true"])
            assert pool.usage() == {0: 0}
        finally:
            await pool.disconnect()
    assert not host.calls("mux")
    pool = make_pool(host, login_shell=None)
    try:
        await pool.connect()
        pool.set_login_shell("/bin/zsh")
        assert (await pool.run(["true"])).ok
    finally:
        await pool.disconnect()


@pytest.mark.asyncio
async def test_nothing_rides_a_master_that_is_not_up(host: FakeSshHost) -> None:
    pool = make_pool(host)
    with pytest.raises(HostNotConnected):
        await pool.run(["true"])
    host.set("scenario", "auth_failed")
    try:
        await pool.connect()
        with pytest.raises(HostNotConnected, match="refused"):
            await pool.spawn(["true"])
    finally:
        await pool.disconnect()


@pytest.mark.asyncio
async def test_run_is_bounded_in_time_and_bytes(host: FakeSshHost) -> None:
    pool = make_pool(host)
    try:
        await pool.connect()
        flood = await pool.run(script="yes | head -c 3000000", max_output=1000)
        assert flood.overflowed and len(flood.stdout) == 1000
        hang = await pool.run(script="sleep 30", timeout=0.3)
        assert hang.timed_out and hang.failure == "timeout"
        assert pool.usage() == {0: 0}
    finally:
        await pool.disconnect()


@pytest.mark.asyncio
async def test_disconnect_closes_every_channel_and_master(host: FakeSshHost) -> None:
    pool = make_pool(host, channel_budget=1)
    await pool.connect()
    channels = [await pool.spawn(["sleep", "30"]) for _ in range(2)]
    await pool.disconnect()
    assert all(c.process.returncode is not None for c in channels)
    assert host.master_pids() == [] and pool.usage() == {0: 0}
    assert pool.status.state == "disconnected"
    status = await pool.connect()
    assert status.state == "up"
    await pool.disconnect()
