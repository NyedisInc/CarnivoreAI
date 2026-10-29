
from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from contextlib import closing
from pathlib import Path
from typing import AsyncIterator, List
from unittest import mock

import pytest
import pytest_asyncio

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_s5a_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_s5a_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

from src.config import settings  # noqa: E402
from src.core.db import connect, db_path_for  # noqa: E402
from src.core.db_migration import ensure_db_migrated  # noqa: E402
from src.core.hosts import remote_backend, store  # noqa: E402
from src.core.hosts.identity import remote_session_id  # noqa: E402
from src.core.hosts.registry import HostRegistry, HostUnavailable  # noqa: E402
from src.core.session_manager import SessionManager  # noqa: E402
from src.api.ws_startup_paint import paint_on_attach  # noqa: E402
from tests.helpers.fake_ssh import FakeSshHost  # noqa: E402

TMUX = shutil.which("tmux")
HOST = "fakehost"
SOCKET = "carnivore-remote"
FAST = lambda attempt: 0.05  # noqa: E731

pytestmark = pytest.mark.skipif(TMUX is None, reason="tmux is not installed")


class Rig:

    def __init__(self, mgr: SessionManager, fake: FakeSshHost, state: Path) -> None:
        self.mgr, self.fake, self.state = mgr, fake, state
        self.local_ids: List[str] = []

    def db(self):
        return closing(connect(db_path_for(self.state), create=False))

    async def far(self, *args: str) -> tuple[int, str]:
        host = await self.mgr.hosts.get(HOST)
        result = await host.exec([str(TMUX), "-L", SOCKET, *args])
        return result.returncode, result.stdout_text


def _add_host(state: Path, fake: FakeSshHost) -> None:
    fake.add_tool("claude", 'echo "fake-claude:$*"; exec /bin/sh\n')
    with closing(connect(db_path_for(state), create=False)) as conn:
        with mock.patch.object(store, "generate_key", return_value=HOST):
            store.create_host(conn, label="fake box", ssh_target="acme@fakehost", socket=SOCKET)
        store.record_probe(conn, HOST, {
            "probe_state": "ok", "probe_detail": None, "login_shell": "/bin/sh",
            "login_path": f"{fake.bin_dir}:/usr/bin:/bin:/usr/sbin:/sbin",
            "tmux_path": str(TMUX), "tmux_version": "tmux 3.7c",
            "agent_paths_json": f'{{"claude": "{fake.bin_dir}/claude"}}',
            "machine_id": None, "remote_carnivore": "none"})


@pytest_asyncio.fixture
async def rig(tmp_path, monkeypatch) -> AsyncIterator[Rig]:
    state, logs, mirrors = tmp_path / "state", tmp_path / "logs", tmp_path / "m"
    for directory in (state, logs, mirrors):
        directory.mkdir()
    monkeypatch.setattr(settings, "log_directory", str(logs))
    monkeypatch.setattr(settings, "state_dir_override", str(state))
    ensure_db_migrated(state, 4, "0.8.2")
    fake = FakeSshHost()
    _add_host(state, fake)
    mgr = SessionManager()
    mgr.hosts = HostRegistry(
        mgr._datastore_connection,
        pool_options=dict(control_dir=fake.control_dir, instance_tag="5f4cec3f",
                          ssh_binary=fake.ssh_binary, connect_timeout=5.0,
                          check_interval=0.5, delay=FAST),
        channel_options=dict(command_timeout=10.0, connect_timeout=10.0, delay=FAST),
        host_options=dict(mirror_dir=mirrors, instance_tag="5f4cec3f", command_timeout=5.0))
    rig = Rig(mgr, fake, state)
    try:
        yield rig
    finally:
        try:
            for sid in list(mgr._registry.backends):
                try:
                    await mgr.destroy_session(sid)
                except (ValueError, OSError, RuntimeError):
                    pass
            host = mgr.hosts._hosts.get(HOST)
            if host is not None:
                await host.channel.stop()
                await host.exec([str(TMUX), "-L", SOCKET, "kill-server"])
                left = await host.exec([str(TMUX), "-L", SOCKET, "has-session"])
                assert left.returncode != 0, "the fake host's tmux server was left running"
        finally:
            await mgr.hosts.close_all()
            fake.cleanup()


async def _wait(check, timeout: float = 15.0, what: str = "") -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not check():
        assert asyncio.get_running_loop().time() < deadline, f"timed out waiting for {what}"
        await asyncio.sleep(0.05)


class _PaintSocket:
    def __init__(self) -> None:
        self.frames: List[bytes] = []

    async def send_bytes(self, data: bytes) -> None:
        self.frames.append(data)


@pytest.mark.asyncio
async def test_create_attach_stream_and_destroy_on_a_host_never_touch_the_local_twin(rig):
    mgr = rig.mgr
    far_home = rig.fake.root / "home"
    (far_home / "proj").mkdir()
    local = await mgr.create_session(session_id="ses_s5aloc1", working_dir=str(rig.state),
                                     auto_start_claude=False, project_name="s5a twin")
    remote = await mgr.create_session(session_id="ses_s5arem1", working_dir="~/proj",
                                      auto_start_claude=True, project_name="s5a twin",
                                      label="twin", host_key=HOST)
    assert local.tmux_session == remote.tmux_session == "carnivore_s5a twin"
    assert remote.id.startswith("ses_") and not remote.id.startswith("adopted:")
    assert remote.working_dir == str(far_home.resolve() / "proj")
    backend = mgr._registry.backends[remote.id]
    assert backend.pid is None and backend.host_key == HOST

    with rig.db() as conn:
        row = conn.execute("SELECT s.host_key, s.tmux_socket, s.origin, s.agent_family, "
                           "p.root, p.host_key FROM sessions s JOIN projects p "
                           "ON p.id = s.project_id WHERE s.tmux_name = ? AND s.host_key = ?",
                           (remote.tmux_session, HOST)).fetchone()
    assert tuple(row) == (HOST, SOCKET, "created", "claude",
                          f"ssh://{HOST}{remote.working_dir}", HOST)

    infos = {info.session.id: info for info in await mgr.list_session_infos()}
    assert (infos[remote.id].host_key, infos[remote.id].host_label) == (HOST, "fake box")
    assert infos[local.id].host_key == "local"
    assert not [sid for sid in infos if sid.startswith("adopted:")]

    viewer = mgr._registry.subscribe(remote.id)
    sock = _PaintSocket()
    assert await paint_on_attach(sock, backend) == "screen"
    assert b"fake-claude:--name twin" in sock.frames[0]
    await mgr.send_input("echo s5a-$((6*7))\r", session_id=remote.id)
    await _wait(lambda: b"s5a-42" in backend._resolve_pipe_path().read_bytes(),
                what="the far echo")

    mgr._registry.unsubscribe(viewer, remote.id)
    await mgr.destroy_session(remote.id)
    code, _ = await rig.far("has-session", "-t", f"={remote.tmux_session}")
    assert code != 0, "the remote session survived its destroy"
    assert await mgr._registry.backends[local.id].is_alive_async(), "the local twin was killed"

    code, _ = await rig.far("new-session", "-d", "-s", local.tmux_session)
    assert code == 0
    result = await mgr.destroy_external_session(remote_session_id(HOST, local.tmux_session))
    assert result["killed"] is True
    code, _ = await rig.far("has-session", "-t", f"={local.tmux_session}")
    assert code != 0
    assert await mgr._registry.backends[local.id].is_alive_async(), "the local twin was killed"


@pytest.mark.asyncio
async def test_a_host_that_cannot_carry_a_session_is_refused_by_name(rig):
    with rig.db() as conn:
        store.update_host(conn, HOST, enabled=False)
    with pytest.raises(HostUnavailable) as refused:
        await rig.mgr.create_session(session_id="ses_s5aoff1", host_key=HOST)
    assert (refused.value.code, refused.value.status) == ("host_disabled", 409)
    with pytest.raises(HostUnavailable) as missing:
        await rig.mgr.create_session(session_id="ses_s5aoff2", host_key="nobox")
    assert missing.value.code == "host_not_found"
    assert not rig.mgr._registry.backends


@pytest.mark.asyncio
@pytest.mark.parametrize("bypass", [False, True], ids=["literal", "negative_control_bypassed"])
async def test_a_hostile_project_name_never_runs_on_the_far_box(rig, monkeypatch, bypass):
    marker = rig.fake.root / "pwned"
    create = rig.mgr.create_session(session_id="ses_s5ahst1", auto_start_claude=False,
                                    host_key=HOST, project_name=f"x#(touch {marker})")
    if not bypass:
        session = await create
        await asyncio.sleep(1.5)
        assert not marker.exists()
        assert session.tmux_session == f"carnivore_x#(touch {marker})"
        return
    monkeypatch.setattr(remote_backend, "escape_expanded", lambda verb, args: list(args))
    try:
        await create
    except (RuntimeError, ValueError):
        pass
    await _wait(marker.exists, timeout=10, what="the unescaped #() to run")
