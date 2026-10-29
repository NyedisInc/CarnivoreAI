
from __future__ import annotations

import asyncio
import os
import tempfile
from contextlib import closing

import pytest
from fastapi import HTTPException

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_s5b_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_s5b_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

from src.api import recreate_routes  # noqa: E402
from src.core import session_sleep, session_view_clears  # noqa: E402
from src.core.attention_wiring import build_attention_watcher  # noqa: E402
from src.core.hosts import remote_readopt  # noqa: E402
from src.core.hosts.identity import remote_session_id  # noqa: E402
from src.core.hosts.registry import HostRegistry, HostUnavailable  # noqa: E402
from src.core.session_manager import SessionManager  # noqa: E402
from tests.test_hosts_remote_sessions import HOST, SOCKET, TMUX, _wait, rig  # noqa: E402,F401

pytestmark = pytest.mark.skipif(TMUX is None, reason="tmux is not installed")

DIALOG = r"printf 'Bash command\n date\nDo you want to proceed?\n  1. Yes\n  2. No\n'"


async def _twins(rig):
    mgr = rig.mgr
    (rig.fake.root / "home" / "proj").mkdir(exist_ok=True)
    local = await mgr.create_session(session_id="ses_5b10ca11", working_dir=str(rig.state),
                                     auto_start_claude=False, project_name="s5b twin",
                                     label="near")
    remote = await mgr.create_session(session_id="ses_5b4e0071", working_dir="~/proj",
                                      auto_start_claude=False, project_name="s5b twin",
                                      label="far", host_key=HOST)
    assert local.tmux_session == remote.tmux_session
    return local, remote


async def _rows(mgr):
    return {info.session.id: info for info in await mgr.list_session_infos()}


def _row(rig, host_key: str, name: str) -> dict:
    with rig.db() as conn:
        conn.row_factory = __import__("sqlite3").Row
        return dict(conn.execute("SELECT * FROM sessions WHERE host_key = ? AND tmux_name = ?",
                                 (host_key, name)).fetchone())


@pytest.mark.asyncio
async def test_a_same_named_local_and_remote_session_never_leak_into_each_other(rig):
    mgr = rig.mgr
    local, remote = await _twins(rig)
    rows = await _rows(mgr)
    near, far = rows[local.id], rows[remote.id]
    assert (far.host_key, far.host_state, near.host_key) == (HOST, "up", "local")
    assert (near.label, far.label) == ("near", "far")
    assert near.session_row_id != far.session_row_id
    assert far.session_row_id == _row(rig, HOST, remote.tmux_session)["id"]
    assert near.project_id != far.project_id
    assert far.session.pty_pid is None and far.created_by_cloude is True

    far_key = remote_session_id(HOST, remote.tmux_session)
    mgr.set_manual_unread(local.tmux_session, True)
    rows = await _rows(mgr)
    assert (rows[local.id].unread, rows[remote.id].unread) == (True, False)
    mgr.set_manual_unread(far_key, True)
    mgr.set_manual_unread(local.tmux_session, False)
    rows = await _rows(mgr)
    assert (rows[local.id].unread, rows[remote.id].unread) == (False, True)
    mgr.set_manual_unread(local.tmux_session, True)
    session_view_clears.clear_view_state(mgr, session_id=remote.id)
    rows = await _rows(mgr)
    assert (rows[local.id].unread, rows[remote.id].unread) == (True, False)


@pytest.mark.asyncio
async def test_the_watcher_reads_a_dialog_off_the_far_pane_and_never_the_local_twin(rig):
    mgr = rig.mgr
    local, remote = await _twins(rig)
    watcher = build_attention_watcher(mgr, tick_seconds=0.0)

    async def statuses():
        await watcher.tick_once()
        rows = await _rows(mgr)
        return {sid: (rows[sid].activity_status, rows[sid].status_source)
                for sid in (local.id, remote.id)}

    await mgr.send_input(DIALOG + "\r", session_id=remote.id)
    for _ in range(40):
        seen = await statuses()
        if seen[remote.id][0] == "question":
            break
        await asyncio.sleep(0.25)
    assert seen[remote.id] == ("question", "pane")
    assert seen[local.id][0] != "question"

    await mgr.send_input("clear\r", session_id=remote.id)
    await mgr.send_input(DIALOG + "\r", session_id=local.id)
    for _ in range(40):
        seen = await statuses()
        if seen[local.id][0] == "question" and seen[remote.id][0] != "question":
            break
        await asyncio.sleep(0.25)
    assert seen[local.id][0] == "question"
    assert seen[remote.id][0] != "question"


@pytest.mark.asyncio
async def test_a_far_session_measured_gone_is_dropped_and_the_twin_survives(rig):
    mgr = rig.mgr
    local, remote = await _twins(rig)
    code, _ = await rig.far("kill-session", "-t", f"={remote.tmux_session}")
    assert code == 0
    rows = await _rows(mgr)
    assert remote.id not in rows and remote.id not in mgr._registry.backends
    assert local.id in rows and await mgr._registry.backends[local.id].is_alive_async()


@pytest.mark.asyncio
async def test_an_unreachable_host_degrades_to_unknown_and_nothing_acts_on_it(rig):
    mgr = rig.mgr
    _local, remote = await _twins(rig)
    watcher = build_attention_watcher(mgr, tick_seconds=0.0)
    await watcher.tick_once()
    assert watcher.observation_for(remote.id) is not None
    host = await mgr.hosts.get(HOST)

    rig.fake.set("scenario", "unreachable")
    await host.channel.stop()
    try:
        for _ in range(4):
            await watcher.tick_once()
        rows = await _rows(mgr)
        far = rows[remote.id]
        assert (far.host_state, far.activity_status) == ("down", "unknown")
        assert remote.id in mgr._registry.backends, "an unreachable host's session was reaped"
        row = _row(rig, HOST, remote.tmux_session)
        assert row["lifecycle"] == "running"
        assert session_sleep.sleep_refusal(row).code == session_sleep.REFUSED_REMOTE_HOST
        with pytest.raises(HTTPException) as refused:
            recreate_routes._resolved({"row": row, "row_read_ok": True}, row["session_uuid"])
        assert (refused.value.status_code, refused.value.detail["code"]) == (409, "remote_host")
    finally:
        rig.fake.set("scenario", "ok")
        await host.channel.start()
    await _wait(lambda: host.is_up, what="the host to come back")
    rows = await _rows(mgr)
    assert rows[remote.id].host_state == "up"


def _fresh_manager(rig) -> SessionManager:
    old = rig.mgr.hosts
    mgr = SessionManager()
    mgr.hosts = HostRegistry(mgr._datastore_connection, pool_options=old._pool_options,
                             channel_options=old._channel_options,
                             host_options=old._host_options)
    return mgr


async def _shut_down(mgr: SessionManager) -> None:
    for backend in list(mgr._registry.backends.values()):
        stream = getattr(backend, "_stream", None)
        if stream is not None:
            await stream.stop()
        task = getattr(backend, "_reader_task", None)
        if task is not None:
            task.cancel()
    await mgr.hosts.close_all()


@pytest.mark.asyncio
async def test_the_boot_readopt_holds_a_surviving_far_session_on_its_id_and_row(rig):
    old = rig.mgr
    (rig.fake.root / "home" / "proj").mkdir(exist_ok=True)
    remote = await old.create_session(session_id="ses_5b4ead01", working_dir="~/proj",
                                      auto_start_claude=False, project_name="s5b boot",
                                      label="kept", host_key=HOST)
    row_before = _row(rig, HOST, remote.tmux_session)
    code, _ = await rig.far("new-session", "-d", "-s", "stranger")
    assert code == 0
    await _shut_down(old)

    mgr = _fresh_manager(rig)
    try:
        await _readopt_and_check(rig, mgr, remote, row_before)
    finally:
        await _clean_up(rig, mgr)


async def _readopt_and_check(rig, mgr, remote, row_before) -> None:
    rig.fake.set("scenario", "unreachable")
    attempts = []

    def delay(attempt: int) -> float:
        attempts.append(attempt)
        rig.fake.set("scenario", "ok")
        return 0.05

    reports = await remote_readopt.readopt_remote_hosts(mgr, delay=delay)
    assert attempts, "an unreachable host was not retried"
    report = reports[HOST]
    assert report["outcome"] == "ran"
    assert report["held"] == [(remote.id, remote_readopt.ID_SOURCE_PANE_ENV)]
    assert "stranger" not in [b.tmux_session for b in mgr._registry.backends.values()]

    info = (await _rows(mgr))[remote.id]
    assert (info.host_key, info.label, info.session_row_id) == (HOST, "kept", row_before["id"])
    await mgr.send_input("echo s5b-$((6*7))\r", session_id=remote.id)
    backend = mgr._registry.backends[remote.id]
    await backend.ensure_streaming()
    await mgr.send_input("echo s5b-$((6*8))\r", session_id=remote.id)
    await _wait(lambda: b"s5b-48" in backend._resolve_pipe_path().read_bytes(),
                what="output from the re-adopted far pane")
    again = await remote_readopt.readopt_remote_hosts(mgr, delay=delay)
    assert again[HOST]["held"] == [], "a second pass held a session twice"


async def _clean_up(rig, mgr: SessionManager) -> None:
    rig.fake.set("scenario", "ok")
    try:
        try:
            await mgr.hosts.get(HOST)
        except HostUnavailable:
            pass
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
