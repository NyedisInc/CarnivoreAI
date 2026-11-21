
from __future__ import annotations

import asyncio
import os
import shlex
from pathlib import Path
from types import SimpleNamespace
from typing import Iterator

import pytest

from src.core.hosts.ssh_exec import SshDestination
from src.core.hosts.ssh_pool import SshMasterPool
from tests.helpers.fake_ssh import FakeSshHost, fake_ssh_host_fixture
from src.core.pack.jobs.ssh.conn import SshConn, pin_key
from tests.python.pack.jobs.test_pack_ssh_conn import FAKE_HOST_ID, make_key

MARKER = "CVJ_H5_MARKER_VALUE"


@pytest.fixture
def fake() -> Iterator[FakeSshHost]:
    yield from fake_ssh_host_fixture()


def dumper(fake: FakeSshHost, out: Path) -> str:
    wrapper = fake.root / "local" / "dump_ssh"
    wrapper.write_text(f"#!/bin/sh\nenv >> {shlex.quote(str(out))}\nexec {shlex.quote(fake.ssh_binary)} \"$@\"\n", encoding="utf-8")
    os.chmod(wrapper, 0o755)
    return str(wrapper)


def test_a_jobs_connection_master_has_no_marker_and_the_default_pool_does(fake: FakeSshHost, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CVJ_H5_MARKER", MARKER)
    jobs_out, default_out = tmp_path / "jobs.env", tmp_path / "default.env"
    state = tmp_path / "state"
    state.mkdir()

    async def jobs_side() -> None:
        key, fp = make_key()
        pin_key(FAKE_HOST_ID, fp, key, state)
        host = SimpleNamespace(key=FAKE_HOST_ID, ssh_target="alex@fakehost", ssh_port=2222, login_shell="/bin/sh")
        conn = SshConn(host, state, pinned_fp=fp, ssh_binary=dumper(fake, jobs_out), control_dir=fake.control_dir,
                       connect_timeout=5.0, check_interval=0.5, delay=lambda attempt: 0.05)
        try:
            await conn.call(b"true\n", 10)
        finally:
            await conn.close()

    async def default_side() -> None:
        pool = SshMasterPool("fakehost000002", SshDestination("alex@fakehost", 2222), login_shell="/bin/sh", control_dir=fake.control_dir,
                             ssh_binary=dumper(fake, default_out), max_slots=1, connect_timeout=5.0, check_interval=0.5, delay=lambda attempt: 0.05)
        try:
            await pool.connect()
        finally:
            await pool.disconnect()

    asyncio.run(jobs_side())
    asyncio.run(default_side())
    jobs_env, default_env = jobs_out.read_text(), default_out.read_text()
    assert jobs_env and "CVJ_H5_MARKER" not in jobs_env and MARKER not in jobs_env
    assert "HOME=" in jobs_env, "the minimal environment keeps HOME"
    assert f"CVJ_H5_MARKER={MARKER}" in default_env, "the default pool still inherits the process environment (the control)"
