
from __future__ import annotations

import asyncio
import os
import signal
import stat
import subprocess
from pathlib import Path
from typing import Iterator, List

import pytest

from src.core.hosts.ssh_exec import SshDestination
from src.core.hosts.ssh_master import (
    CONNECTING,
    DISCONNECTED,
    REFUSED,
    RETRYING,
    UP,
    MasterStatus,
    SshMaster,
    SshTransportError,
    backoff_delay,
    control_path_for,
    ensure_control_dir,
    instance_tag_for,
)
from tests.helpers.fake_ssh import FakeSshHost, fake_ssh_host_fixture

DEST = SshDestination("acme@fakehost")
TAG = "5f4cec3f"


@pytest.fixture
def host() -> Iterator[FakeSshHost]:
    yield from fake_ssh_host_fixture()


def make_master(host: FakeSshHost, slot: int = 0, **options) -> SshMaster:
    ensure_control_dir(host.control_dir)
    settings = dict(ssh_binary=host.ssh_binary, connect_timeout=5.0, check_interval=0.2,
                    stable_after=0.5, delay=lambda attempt: 0.05)
    settings.update(options)
    return SshMaster("fakehost", DEST, control_path_for(host.control_dir, "fakehost", TAG, slot),
                     slot=slot, **settings)


async def wait_for(predicate, timeout: float = 5.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        assert loop.time() < deadline, "condition never became true"
        await asyncio.sleep(0.02)


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


@pytest.mark.asyncio
async def test_up_is_measured_by_the_masters_own_pid(host: FakeSshHost) -> None:
    master = make_master(host)
    try:
        status = await master.connect()
        assert status.state == UP and status.failure is None
        assert host.master_pids() == [status.pid]
        assert await master.check()
        assert len(host.calls("master")) == 1
        assert stat.S_IMODE(os.lstat(host.control_dir).st_mode) == 0o700
    finally:
        await master.disconnect()


@pytest.mark.asyncio
async def test_disconnect_ends_the_master_and_frees_its_path(host: FakeSshHost) -> None:
    master = make_master(host)
    pid = (await master.connect()).pid
    await master.disconnect()
    assert master.status.state == DISCONNECTED and master.status.pid is None
    assert not alive(pid)
    assert not os.path.lexists(master.control_path)


@pytest.mark.asyncio
async def test_a_killed_master_is_seen_and_replaced(host: FakeSshHost) -> None:
    master = make_master(host)
    try:
        first = (await master.connect()).pid
        os.kill(first, signal.SIGKILL)
        await wait_for(lambda: master.status.state == UP and master.status.pid not in (None, first))
        assert len(host.calls("master")) == 2
        assert host.master_pids() == [master.status.pid]
    finally:
        await master.disconnect()


@pytest.mark.asyncio
async def test_a_stale_socket_left_by_a_crash_is_cleared_first(host: FakeSshHost) -> None:
    master = make_master(host)
    Path(master.control_path).write_text("999999")
    try:
        status = await master.connect()
        assert status.state == UP, status.detail
        assert host.master_pids() == [status.pid]
    finally:
        await master.disconnect()


@pytest.mark.asyncio
async def test_a_socket_answering_with_another_pid_is_not_up(host: FakeSshHost) -> None:
    host.set("scenario", "foreign_master")
    master = make_master(host, delay=lambda attempt: 30.0)
    try:
        status = await master.connect()
        assert (status.state, status.failure) == (RETRYING, "control_path_busy"), status.detail
        assert str(os.getpid()) in status.detail
    finally:
        await master.disconnect()


@pytest.mark.asyncio
async def test_an_orphan_master_on_the_path_is_exited_first(host: FakeSshHost) -> None:
    master = make_master(host)
    orphan = subprocess.Popen([host.ssh_binary, "-o", "ControlMaster=yes", "-o",
                               f"ControlPath={master.control_path}", "-N", "--", DEST.target],
                              stdin=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        await wait_for(lambda: os.path.lexists(master.control_path))
        status = await master.connect()
        assert status.state == UP and status.pid != orphan.pid
        assert orphan.wait(timeout=5) == 0, "the orphan was not told to exit"
        assert len(host.calls("control_exit")) == 1
    finally:
        await master.disconnect()
        if orphan.poll() is None:
            orphan.kill()


@pytest.mark.asyncio
async def test_a_changed_host_key_parks_and_is_never_retried(host: FakeSshHost) -> None:
    host.set("scenario", "host_key_changed")
    master = make_master(host)
    try:
        status = await master.connect()
        assert (status.state, status.failure) == (REFUSED, "host_key_changed")
        assert status.detail.startswith("the host key changed since it was first trusted")
        await asyncio.sleep(0.5)
        assert len(host.calls("master")) == 1, "a refused host key was retried"
        status = await master.connect()
        assert status.state == REFUSED and len(host.calls("master")) == 2
    finally:
        await master.disconnect()


@pytest.mark.asyncio
async def test_a_refused_login_parks(host: FakeSshHost) -> None:
    host.set("scenario", "auth_failed")
    master = make_master(host)
    try:
        status = await master.connect()
        assert (status.state, status.failure) == (REFUSED, "auth_failed")
        await asyncio.sleep(0.3)
        assert len(host.calls("master")) == 1
    finally:
        await master.disconnect()


@pytest.mark.asyncio
async def test_unreachable_backs_off_then_recovers(host: FakeSshHost) -> None:
    host.set("scenario", "unreachable")
    seen: List[MasterStatus] = []
    master = make_master(host, on_change=seen.append)
    try:
        status = await master.connect()
        assert (status.state, status.failure) == (RETRYING, "unreachable")
        assert status.retry_in is not None
        await wait_for(lambda: len(host.calls("master")) >= 3)
        host.set("scenario", "ok")
        await wait_for(lambda: master.status.state == UP)
        assert [s.state for s in seen][:3] == [CONNECTING, RETRYING, CONNECTING]
        assert seen[-1].state == UP
    finally:
        await master.disconnect()
    assert seen[-1].state == DISCONNECTED


@pytest.mark.asyncio
async def test_a_master_that_never_answers_times_out_and_retries(host: FakeSshHost) -> None:
    host.set("scenario", "hang")
    master = make_master(host, connect_timeout=0.4, delay=lambda attempt: 30.0)
    try:
        status = await master.connect()
        assert (status.state, status.failure) == (RETRYING, "timeout")
    finally:
        await master.disconnect()
    assert master.status.state == DISCONNECTED


@pytest.mark.asyncio
async def test_a_missing_ssh_binary_parks(host: FakeSshHost) -> None:
    master = make_master(host, ssh_binary=str(host.root / "no-ssh"))
    try:
        status = await master.connect()
        assert (status.state, status.failure) == (REFUSED, "ssh_unavailable")
    finally:
        await master.disconnect()


def test_backoff_is_1_2_4_to_60_and_only_shortened_by_jitter() -> None:
    top = [backoff_delay(n, rand=lambda: 0.999999) for n in range(9)]
    assert [round(d) for d in top] == [1, 2, 4, 8, 16, 32, 60, 60, 60]
    assert [backoff_delay(n, rand=lambda: 0.0) for n in (0, 3, 20)] == [0.5, 4.0, 30.0]
    assert max(backoff_delay(n) for n in range(200)) <= 60.0


def test_control_paths_are_ours_alone() -> None:
    cm = Path("/c")
    assert control_path_for(cm, "hosta", TAG, 3) == f"{cm}/hosta-{TAG}-3"
    for key in ("local", "Hosta", "-x", "", "a" * 33, "a/b"):
        with pytest.raises(SshTransportError):
            control_path_for(cm, key, TAG, 0)
    for tag, slot in (("xyz", 0), (TAG, 100), (TAG, -1)):
        with pytest.raises(SshTransportError):
            control_path_for(cm, "hosta", tag, slot)
    assert instance_tag_for("/a") != instance_tag_for("/b")
    assert len(instance_tag_for("/a")) == 8


def test_the_control_dir_is_narrowed_and_a_link_is_refused(tmp_path: Path) -> None:
    wide = tmp_path / "wide"
    wide.mkdir(mode=0o755)
    wide.chmod(0o755)
    ensure_control_dir(wide)
    assert stat.S_IMODE(wide.stat().st_mode) == 0o700
    link = tmp_path / "link"
    link.symlink_to(wide)
    with pytest.raises(SshTransportError):
        ensure_control_dir(link)
    file_path = tmp_path / "file"
    file_path.write_text("")
    with pytest.raises((SshTransportError, FileExistsError)):
        ensure_control_dir(file_path)
