
from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Iterator
from unittest import mock

import pytest

from src.core.hosts.probe import probe_host
from src.core.hosts.ssh_exec import SSH_BINARY, SshDestination, is_posix_shell
from src.core.hosts.ssh_master import REFUSED, UP
from src.core.hosts.ssh_pool import SshMasterPool

TARGET = os.environ.get("CARNIVORE_TEST_SSH_HOST", "")
PORT = os.environ.get("CARNIVORE_TEST_SSH_PORT")

pytestmark = [
    pytest.mark.real_ssh,
    pytest.mark.skipif(not TARGET, reason="set CARNIVORE_TEST_SSH_HOST to run against a real host"),
]

KEYGEN_TYPES = {
    "ssh-ed25519": ["-t", "ed25519"],
    "ecdsa-sha2-nistp256": ["-t", "ecdsa", "-b", "256"],
    "ecdsa-sha2-nistp384": ["-t", "ecdsa", "-b", "384"],
    "ecdsa-sha2-nistp521": ["-t", "ecdsa", "-b", "521"],
    "ssh-rsa": ["-t", "rsa", "-b", "2048"],
}


@pytest.fixture
def dest() -> SshDestination:
    return SshDestination(TARGET, int(PORT) if PORT else None)


@pytest.fixture
def scratch() -> Iterator[Path]:
    path = Path(tempfile.mkdtemp(prefix="rs"))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def make_pool(dest: SshDestination, scratch: Path, ssh_binary: str = SSH_BINARY,
              **options) -> SshMasterPool:
    return SshMasterPool("rsshost", dest, login_shell="/bin/sh", control_dir=scratch / "cm",
                         instance_tag="0123abcd", ssh_binary=ssh_binary, **options)


def no_master_left(scratch: Path) -> bool:
    cm = scratch / "cm"
    return not cm.exists() or not any(cm.iterdir())


@pytest.mark.asyncio
async def test_probe_a_real_host(dest: SshDestination) -> None:
    result = await probe_host(dest)
    print(f"\nprobe {TARGET}: {result}")
    assert result.verdict == "ok", result.detail
    assert result.tmux_path and result.tmux_path.startswith("/")
    assert result.tmux_version and is_posix_shell(result.login_shell)
    assert result.login_path and result.machine_id
    assert all(path.startswith("/") for path in result.agent_paths.values())
    assert result.remote_carnivore in ("running", "none")


@pytest.mark.asyncio
async def test_a_real_master_carries_commands_and_channels(dest: SshDestination,
                                                           scratch: Path) -> None:
    pool = make_pool(dest, scratch, channel_budget=1)
    try:
        status = await pool.connect()
        assert status.state == UP, status.detail
        words = ["it's", "$(id)", "`id`", "; id", "a b", "=ls", "*", "\n", ""]
        result = await pool.run(["printf", "%s\\0", *words])
        assert result.ok, result.stderr_text
        assert result.stdout.split(b"\0")[:-1] == [w.encode() for w in words]
        first = await pool.spawn(["cat"])
        second = await pool.spawn(["cat"])
        assert pool.usage() == {0: 1, 1: 1}
        second.process.stdin.write(b"echo me\n")
        await second.process.stdin.drain()
        assert await second.process.stdout.readline() == b"echo me\n"
        await first.close()
        await second.close()
    finally:
        await pool.disconnect()
    assert pool.status.state == "disconnected" and no_master_left(scratch)


def _known_hosts_ssh(scratch: Path, known_hosts: Path) -> str:
    wrapper = scratch / "ssh-kh"
    wrapper.write_text(f"#!/bin/sh\nexec {SSH_BINARY} -o UserKnownHostsFile={known_hosts} "
                       '-o GlobalKnownHostsFile=/dev/null "$@"\n')
    wrapper.chmod(0o755)
    return str(wrapper)


def _swap_keys(known_hosts: Path, scratch: Path) -> None:
    lines = []
    for index, line in enumerate(known_hosts.read_text().splitlines()):
        fields = line.split()
        key = scratch / f"bogus{index}"
        subprocess.run(["ssh-keygen", "-q", "-N", "", *KEYGEN_TYPES[fields[1]], "-f", str(key)],
                       check=True, capture_output=True)
        fields[2] = (scratch / f"bogus{index}.pub").read_text().split()[1]
        lines.append(" ".join(fields))
    known_hosts.write_text("\n".join(lines) + "\n")


@pytest.mark.asyncio
async def test_trust_on_first_use_pins_and_a_changed_key_is_refused(
        dest: SshDestination, scratch: Path) -> None:
    known_hosts = scratch / "known_hosts"
    known_hosts.write_text("")
    ssh = _known_hosts_ssh(scratch, known_hosts)

    pool = make_pool(dest, scratch, ssh_binary=ssh)
    try:
        assert (await pool.connect()).state == UP, "first use was not trusted"
    finally:
        await pool.disconnect()
    pinned = known_hosts.read_bytes()
    assert pinned.strip(), "accept-new did not pin the key"

    _swap_keys(known_hosts, scratch)
    changed = known_hosts.read_bytes()
    pool = make_pool(dest, scratch, ssh_binary=ssh)
    try:
        status = await pool.connect()
        assert (status.state, status.failure) == (REFUSED, "host_key_changed"), status.detail
    finally:
        await pool.disconnect()
    result = await probe_host(dest, ssh_binary=ssh)
    assert result.verdict == "host_key_changed", result.detail
    assert known_hosts.read_bytes() == changed, "ssh rewrote the pin of a changed key"

    known_hosts.write_bytes(pinned)
    pool = make_pool(dest, scratch, ssh_binary=ssh)
    try:
        assert (await pool.connect()).state == UP
    finally:
        await pool.disconnect()
    assert no_master_left(scratch)


@pytest.mark.asyncio
async def test_a_real_control_channel_round_trips(dest: SshDestination, scratch: Path) -> None:
    import statistics
    import time

    from src.core.hosts.tmux_control import ControlChannelError, TmuxControlChannel
    from src.core.hosts.tmux_quote import literal
    from src.core.tmux_listing import REASON_NO_SERVER, classify_listing_failure
    from src.core.tmux_listing_parse import CONTROL_SESSION_NAME

    probe = await probe_host(dest)
    assert probe.verdict == "ok" and probe.tmux_path, probe.detail
    tmux, socket = probe.tmux_path, "carnivore-remote"
    pool = make_pool(dest, scratch)
    channel = TmuxControlChannel("rsshost", pool.spawn, tmux, socket)

    async def gone() -> bool:
        result = await pool.run([tmux, "-L", socket, "has-session"], timeout=15)
        return result.returncode != 0 and classify_listing_failure(
            result.returncode, result.stderr_text).reason == REASON_NO_SERVER

    hostile = "s3probe q'; new-session -d -s PWNED; ' #(id) $(id)"
    started_server = False
    try:
        assert (await pool.connect()).state == UP
        started_server = await gone()
        assert (await channel.start()).state == "up", channel.status
        replies = await asyncio.gather(*(channel.command("display-message", "-p", f"n{i}")
                                         for i in range(500)))
        assert [r.text for r in replies] == [f"n{i}" for i in range(500)]
        samples = []
        for _ in range(100):
            began = time.perf_counter()
            await channel.command("display-message", "-p", "x")
            samples.append(time.perf_counter() - began)
        p50 = statistics.median(samples) * 1000
        print(f"\ncontrol channel p50 {p50:.1f} ms, p90 "
              f"{sorted(samples)[89] * 1000:.1f} ms to {TARGET} (tmux {probe.tmux_version})")
        assert (await channel.command("new-session", "-d", "-s", literal(hostile))).ok
        names = (await channel.command("list-sessions", "-F", "#{session_name}")).text.split("\n")
        assert hostile in names and not any(n.startswith("PWNED") for n in names)
        assert names.count(CONTROL_SESSION_NAME) == 1
        assert p50 < 10.0, f"p50 {p50:.1f} ms"
    finally:
        if channel.is_up:
            try:
                if started_server:
                    await channel.command("kill-server", timeout=10)
                else:
                    for name in ("=" + hostile, "=" + CONTROL_SESSION_NAME):
                        await channel.command("kill-session", "-t", name, timeout=10)
            except ControlChannelError:
                pass
        await channel.stop()
        if pool.status.state == UP and started_server and not await gone():
            await pool.run([tmux, "-L", socket, "kill-server"], timeout=15)
        server_gone = (not started_server) or (pool.status.state == UP and await gone())
        await pool.disconnect()
    assert server_gone, "the carnivore-remote server this test started is still running"
    assert no_master_left(scratch)


@pytest.mark.asyncio
async def test_a_real_remote_backend_streams_and_takes_input(dest: SshDestination,
                                                            scratch: Path) -> None:
    from src.core.hosts.remote_backend import make_remote_backend
    from src.core.hosts.remote_host import RemoteHost
    from src.core.hosts.tmux_control import ControlChannelError, TmuxControlChannel
    from src.core.tmux_listing import REASON_NO_SERVER, classify_listing_failure

    probe = await probe_host(dest)
    assert probe.verdict == "ok" and probe.tmux_path, probe.detail
    tmux, socket = probe.tmux_path, "carnivore-remote"
    pool = make_pool(dest, scratch)
    channel = TmuxControlChannel("rsshost", pool.spawn, tmux, socket)
    host = RemoteHost("rsshost", pool, channel, tmux_path=tmux, socket=socket,
                      login_path=probe.login_path, instance_tag="0123abcd",
                      mirror_dir=scratch / "mirror")
    (scratch / "mirror").mkdir()
    output = bytearray()
    backend = make_remote_backend(host, "ses_s4real", Path("/tmp"), output.extend,
                                session_name="carnivore_s4real", viewer_probe=lambda: True)

    async def gone() -> bool:
        result = await pool.run([tmux, "-L", socket, "has-session"], timeout=15)
        return result.returncode != 0 and classify_listing_failure(
            result.returncode, result.stderr_text).reason == REASON_NO_SERVER

    started_server = False
    far = None
    cache_new = False
    try:
        assert (await pool.connect()).state == UP
        started_server = await gone()
        cache_new = (await pool.run(script='[ -e "$HOME/.cache/carnivore" ] || echo new',
                                    timeout=15)).stdout_text.strip() == "new"
        assert (await channel.start()).state == "up", channel.status
        await host.prepare()
        far = backend._pipe_write_path()
        await backend.start()
        assert await backend.ensure_streaming()
        await backend.write(b"echo s4-real-$((6*7))\r")
        for _ in range(200):
            if b"s4-real-42" in output:
                break
            await asyncio.sleep(0.05)
        assert b"s4-real-42" in output, bytes(output[-300:])
        assert backend.pid is None
        print(f"\nremote backend on {TARGET}: {len(output)} bytes streamed, "
              f"stream position {backend._lifecycle._stream.position}")
        await backend.stop()
        left = await pool.run(script=f"[ -e '{far}' ] && echo left || echo removed", timeout=15)
        assert left.stdout_text.strip() == "removed"
    finally:
        if backend._lifecycle._stream is not None:
            await backend._lifecycle._stream.stop()
        if backend._reader_task is not None:
            backend._reader_task.cancel()
        await host.close()
        if channel.is_up:
            try:
                if started_server:
                    await channel.command("kill-server", timeout=10)
                else:
                    await channel.command("kill-session", "-t", "=carnivore_s4real", timeout=10)
            except ControlChannelError:
                pass
        await channel.stop()
        if pool.status.state == UP and far is not None:
            await pool.run(script=f"rm -f '{far}'", timeout=15)
        if pool.status.state == UP and cache_new:
            await pool.run(script='rm -rf "$HOME/.cache/carnivore"', timeout=15)
        if pool.status.state == UP and started_server and not await gone():
            await pool.run([tmux, "-L", socket, "kill-server"], timeout=15)
        server_gone = (not started_server) or (pool.status.state == UP and await gone())
        await pool.disconnect()
    assert server_gone, "the carnivore-remote server this test started is still running"
    assert no_master_left(scratch)


@pytest.mark.asyncio
async def test_a_real_manager_creates_attaches_and_destroys_on_the_host(
        dest: SshDestination, scratch: Path, tmp_path: Path, monkeypatch) -> None:
    from contextlib import closing

    from src.config import settings
    from src.core.db import connect, db_path_for
    from src.core.db_migration import ensure_db_migrated
    from src.core.hosts import store
    from src.core.hosts.registry import HostRegistry
    from src.core.session_manager import SessionManager

    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setattr(settings, "log_directory", str(tmp_path))
    monkeypatch.setattr(settings, "state_dir_override", str(state))
    ensure_db_migrated(state, 4, "0.8.2")
    probe = await probe_host(dest)
    assert probe.verdict == "ok" and probe.tmux_path, probe.detail
    with closing(connect(db_path_for(state), create=False)) as conn:
        with mock.patch.object(store, "generate_key", return_value="rsshost"):
            store.create_host(conn, label="real host", ssh_target=dest.target,
                              ssh_port=dest.port, socket="carnivore-remote")
        store.record_probe(conn, "rsshost", probe.host_columns())
    mgr = SessionManager()
    mgr.hosts = HostRegistry(mgr._datastore_connection,
                             pool_options=dict(control_dir=scratch / "cm", instance_tag="0123abcd"),
                             host_options=dict(mirror_dir=tmp_path, instance_tag="0123abcd"))
    tmux, socket = probe.tmux_path, "carnivore-remote"
    pre = make_pool(dest, scratch)
    assert (await pre.connect()).state == UP
    before = await pre.run(script='[ -e "$HOME/.cache/carnivore" ] && echo kept || echo new',
                           timeout=15)
    server_before = (await pre.run([tmux, "-L", socket, "has-session"], timeout=15)).returncode == 0
    await pre.disconnect()
    session = None
    try:
        session = await mgr.create_session(session_id="ses_s5areal", auto_start_claude=False,
                                           project_name="s5a real", host_key="rsshost")
        assert session.id == "ses_s5areal" and session.tmux_session == "carnivore_s5a real"
        backend = mgr._registry.backends[session.id]
        viewer = mgr._registry.subscribe(session.id)
        assert await backend.ensure_streaming()
        await mgr.send_input("echo s5a-real-$((6*7))\r", session_id=session.id)
        for _ in range(200):
            if b"s5a-real-42" in backend._resolve_pipe_path().read_bytes():
                break
            await asyncio.sleep(0.05)
        assert b"s5a-real-42" in backend._resolve_pipe_path().read_bytes()
        infos = {i.session.id: i for i in await mgr.list_session_infos()}
        assert (infos[session.id].host_key, infos[session.id].host_label) == ("rsshost", "real host")
        mgr._registry.unsubscribe(viewer, session.id)
        await mgr.destroy_session(session.id)
        host = mgr.hosts._hosts["rsshost"]
        gone = await host.exec([tmux, "-L", socket, "has-session", "-t", "=carnivore_s5a real"])
        assert gone.returncode != 0, "the remote session survived its destroy"
        print(f"\nmanager on {TARGET}: created, streamed and destroyed carnivore_s5a real")
    finally:
        host = mgr.hosts._hosts.get("rsshost")
        if host is not None:
            await host.channel.stop()
            if session is not None:
                await host.exec([tmux, "-L", socket, "kill-session", "-t", "=carnivore_s5a real"])
            if not server_before:
                await host.exec([tmux, "-L", socket, "kill-server"])
            if before.stdout_text.strip() == "new":
                await host.exec(script='rm -rf "$HOME/.cache/carnivore"')
            left = await host.exec(script='[ -e "$HOME/.cache/carnivore" ] && echo kept || echo gone')
            server_left = (await host.exec([tmux, "-L", socket, "has-session"])).returncode == 0
        await mgr.hosts.close_all()
    assert host is None or server_left == server_before, "the far server was left running"
    assert host is None or left.stdout_text.strip() == ("kept" if before.stdout_text.strip() == "kept"
                                                        else "gone")
    assert no_master_left(scratch)


@pytest.mark.asyncio
async def test_a_real_host_is_watched_listed_and_readopted(
        dest: SshDestination, scratch: Path, tmp_path: Path, monkeypatch) -> None:
    from contextlib import closing

    from src.config import settings
    from src.core.attention_wiring import build_attention_watcher
    from src.core.db import connect, db_path_for
    from src.core.db_migration import ensure_db_migrated
    from src.core.hosts import remote_readopt, store
    from src.core.hosts.registry import HostRegistry
    from src.core.session_manager import SessionManager

    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setattr(settings, "log_directory", str(tmp_path))
    monkeypatch.setattr(settings, "state_dir_override", str(state))
    ensure_db_migrated(state, 4, "0.8.2")
    probe = await probe_host(dest)
    assert probe.verdict == "ok" and probe.tmux_path, probe.detail
    with closing(connect(db_path_for(state), create=False)) as conn:
        with mock.patch.object(store, "generate_key", return_value="rsshost"):
            store.create_host(conn, label="real host", ssh_target=dest.target,
                              ssh_port=dest.port, socket="carnivore-remote")
        store.record_probe(conn, "rsshost", probe.host_columns())

    def manager() -> SessionManager:
        mgr = SessionManager()
        mgr.hosts = HostRegistry(
            mgr._datastore_connection,
            pool_options=dict(control_dir=scratch / "cm", instance_tag="0123abcd"),
            host_options=dict(mirror_dir=tmp_path, instance_tag="0123abcd"))
        return mgr

    tmux, socket, name = probe.tmux_path, "carnivore-remote", "carnivore_s5b real"
    pre = make_pool(dest, scratch)
    assert (await pre.connect()).state == UP
    before = await pre.run(script='[ -e "$HOME/.cache/carnivore" ] && echo kept || echo new',
                           timeout=15)
    server_before = (await pre.run([tmux, "-L", socket, "has-session"], timeout=15)).returncode == 0
    await pre.disconnect()
    mgr = manager()
    try:
        session = await mgr.create_session(session_id="ses_5b0ea100", auto_start_claude=False,
                                           project_name="s5b real", host_key="rsshost")
        assert session.tmux_session == name
        await mgr.send_input("printf 'Bash command\\n date\\nDo you want to proceed?\\n"
                             "  1. Yes\\n  2. No\\n'\r", session_id=session.id)
        watcher = build_attention_watcher(mgr, tick_seconds=0.0)
        seen = None
        for _ in range(40):
            await watcher.tick_once()
            info = {i.session.id: i for i in await mgr.list_session_infos()}[session.id]
            seen = (info.activity_status, info.status_source, info.host_state)
            if seen[0] == "question":
                break
            await asyncio.sleep(0.25)
        assert seen == ("question", "pane", "up")

        for backend in list(mgr._registry.backends.values()):
            if backend._lifecycle._stream is not None:
                await backend._lifecycle._stream.stop()
            if backend._reader_task is not None:
                backend._reader_task.cancel()
        await mgr.hosts.close_all()
        mgr = manager()
        report = (await remote_readopt.readopt_remote_hosts(mgr))["rsshost"]
        assert report["held"] == [("ses_5b0ea100", remote_readopt.ID_SOURCE_PANE_ENV)]
        info = {i.session.id: i for i in await mgr.list_session_infos()}["ses_5b0ea100"]
        assert (info.host_key, info.tmux_session) == ("rsshost", name)
        await mgr.destroy_session("ses_5b0ea100")
        print(f"\nS5b on {TARGET}: question read off the far pane; re-adopted as ses_5b0ea100")
    finally:
        try:
            host = await mgr.hosts.get("rsshost")
        except Exception:  # noqa: BLE001
            host = None
        if host is not None:
            await host.channel.stop()
            await host.exec([tmux, "-L", socket, "kill-session", "-t", f"={name}"])
            if not server_before:
                await host.exec([tmux, "-L", socket, "kill-server"])
            if before.stdout_text.strip() == "new":
                await host.exec(script='rm -rf "$HOME/.cache/carnivore"')
            left = await host.exec(script='[ -e "$HOME/.cache/carnivore" ] && echo kept || echo gone')
            server_left = (await host.exec([tmux, "-L", socket, "has-session"])).returncode == 0
        await mgr.hosts.close_all()
    assert host is not None, "cleanup could not reach the host"
    assert server_left == server_before, "the far server was left running"
    assert left.stdout_text.strip() == ("kept" if before.stdout_text.strip() == "kept" else "gone")
    assert no_master_left(scratch)


_FIND_CONVERSATION = (
    'for f in $(ls -t "$HOME"/.claude/projects/*/*.jsonl 2>/dev/null); do '
    'h=$(head -c 20000 "$f"); '
    'printf "%s" "$h" | grep -q \'"entrypoint":"cli"\' || continue; '
    'c=$(printf "%s" "$h" | grep -o \'"cwd":"[^"]*"\' | head -1 | cut -d\'"\' -f4); '
    'u=${f##*/}; u=${u%.jsonl}; '
    'grep -l "$u" "$HOME"/.claude/sessions/*.json >/dev/null 2>&1 && continue; '
    '[ -n "$c" ] && [ "$c" != "$HOME" ] && [ -d "$c" ] && { printf "%s|%s\\n" "$u" "$c"; exit 0; }; '
    'done; exit 1')


@pytest.mark.asyncio
async def test_a_real_host_registry_lights_the_row_and_restart_resumes(
        dest: SshDestination, scratch: Path, tmp_path: Path, monkeypatch) -> None:
    from contextlib import closing

    from src.config import settings
    from src.core.attention_wiring import build_attention_watcher
    from src.core.db import connect, db_path_for
    from src.core.db_migration import ensure_db_migrated
    from src.core.hosts import store
    from src.core.hosts.identity import remote_session_id
    from src.core.hosts.registry import HostRegistry
    from src.core.session_manager import SessionManager

    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setattr(settings, "log_directory", str(tmp_path))
    monkeypatch.setattr(settings, "state_dir_override", str(state))
    ensure_db_migrated(state, 4, "0.8.2")
    probe = await probe_host(dest)
    assert probe.verdict == "ok" and probe.agent_paths.get("claude"), probe.detail
    with closing(connect(db_path_for(state), create=False)) as conn:
        with mock.patch.object(store, "generate_key", return_value="rsshost"):
            store.create_host(conn, label="real host", ssh_target=dest.target,
                              ssh_port=dest.port, socket="carnivore-remote")
        store.record_probe(conn, "rsshost", probe.host_columns())
    mgr = SessionManager()
    mgr.hosts = HostRegistry(mgr._datastore_connection,
                             pool_options=dict(control_dir=scratch / "cm", instance_tag="0123abcd"),
                             host_options=dict(mirror_dir=tmp_path, instance_tag="0123abcd"))
    tmux, socket, name = probe.tmux_path, "carnivore-remote", "carnivore_s7 real"
    pre = make_pool(dest, scratch)
    assert (await pre.connect()).state == UP
    before = await pre.run(script='[ -e "$HOME/.cache/carnivore" ] && echo kept || echo new',
                           timeout=15)
    server_before = (await pre.run([tmux, "-L", socket, "has-session"], timeout=15)).returncode == 0
    found = await pre.run(script=_FIND_CONVERSATION, timeout=30)
    await pre.disconnect()
    assert found.returncode == 0, "the far box holds no conversation whose folder still exists"
    uuid, cwd = found.stdout_text.strip().split("|", 1)
    try:
        session = await mgr.create_session(session_id="ses_57ea1001", working_dir=cwd,
                                           auto_start_claude=False, project_name="s7 real",
                                           host_key="rsshost")
        assert session.tmux_session == name
        with closing(connect(db_path_for(state), create=False)) as conn:
            conn.execute("UPDATE sessions SET claude_session_uuid = ? WHERE host_key = 'rsshost'",
                         (uuid,))
            conn.commit()
        result = await mgr.respawn_session(remote_session_id("rsshost", name), agent_type="claude",
                                           live_restart_confirmed=True)
        assert (result["ok"], result["conversation"]) == (True, "resumed"), result
        assert f"'--resume' '{uuid}'" in result["command"]
        started = await mgr.hosts._hosts["rsshost"].command(
            "list-panes", "-t", f"={name}", "-F", "#{pane_dead} #{pane_start_command}")
        assert f"--resume' '{uuid}'" in b"".join(started.lines).decode(), started
        watcher = build_attention_watcher(mgr, tick_seconds=0.0)
        evidence = None
        for _ in range(40):
            await watcher.tick_once()
            observation = watcher.observation_for(session.id)
            evidence = observation.evidence if observation else None
            if evidence is not None and evidence.transcript.verdict != "unreadable":
                break
            await asyncio.sleep(0.5)
        assert evidence is not None and evidence.transcript.verdict != "unreadable", evidence
        assert evidence.registry.verdict in ("ok", "absent", "shape_unrecognized"), \
            evidence.registry
        if evidence.registry.known:
            assert evidence.registry.session_uuid == uuid
        info = {i.session.id: i for i in await mgr.list_session_infos()}[session.id]
        print(f"\nS7 on {TARGET}: resumed {uuid[:8]} as claude; far registry "
              f"{evidence.registry.verdict}, far transcript {evidence.transcript.verdict}; "
              f"row {info.activity_status} from {info.status_source}")
        await mgr.destroy_session(session.id)
    finally:
        for backend in list(mgr._registry.backends.values()):
            await backend.stop()
        host = mgr.hosts._hosts.get("rsshost")
        if host is not None:
            await host.channel.stop()
            await host.exec([tmux, "-L", socket, "kill-session", "-t", f"={name}"])
            if not server_before:
                await host.exec([tmux, "-L", socket, "kill-server"])
            await asyncio.sleep(1.0)
            stray = await host.exec(script=f"ps -axo pid=,command= | grep -F -- '--resume {uuid}' "
                                           "| grep -v grep | awk '{print $1}'")
            for pid in stray.stdout_text.split():
                await host.exec(script=f"kill {int(pid)} 2>/dev/null; exit 0")
            alive = await host.exec(script=f"ps -axo command= | grep -F -- '--resume {uuid}' "
                                           "| grep -v grep | head -1")
            if before.stdout_text.strip() == "new":
                await host.exec(script='rm -rf "$HOME/.cache/carnivore"')
            left = await host.exec(script='[ -e "$HOME/.cache/carnivore" ] && echo kept || echo gone')
            server_left = (await host.exec([tmux, "-L", socket, "has-session"])).returncode == 0
        await mgr.hosts.close_all()
    assert host is not None, "cleanup could not reach the host"
    assert not alive.stdout_text.strip(), "the far claude was left running"
    assert server_left == server_before, "the far server was left running"
    assert left.stdout_text.strip() == ("kept" if before.stdout_text.strip() == "kept" else "gone")
    assert no_master_left(scratch)


@pytest.mark.asyncio
async def test_a_real_host_renames_and_restarts_a_stopped_row_resuming(
        dest: SshDestination, scratch: Path, tmp_path: Path, monkeypatch) -> None:
    from contextlib import closing

    import httpx
    from fastapi import FastAPI

    from src.api import routes as routes_mod
    from src.api.auth import require_auth
    from src.config import settings
    from src.core.composition import build_services
    from src.core.db import connect, db_path_for
    from src.core.db_migration import ensure_db_migrated
    from src.core.hosts import store
    from src.core.hosts.registry import HostRegistry
    from src.core.session_manager import SessionManager

    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setattr(settings, "log_directory", str(tmp_path))
    monkeypatch.setattr(settings, "state_dir_override", str(state))
    ensure_db_migrated(state, 4, "0.8.2")
    probe = await probe_host(dest)
    assert probe.verdict == "ok" and probe.agent_paths.get("claude"), probe.detail
    with closing(connect(db_path_for(state), create=False)) as conn:
        with mock.patch.object(store, "generate_key", return_value="rsshost"):
            store.create_host(conn, label="real host", ssh_target=dest.target,
                              ssh_port=dest.port, socket="carnivore-remote")
        store.record_probe(conn, "rsshost", probe.host_columns())
    mgr = SessionManager()
    mgr.hosts = HostRegistry(mgr._datastore_connection,
                             pool_options=dict(control_dir=scratch / "cm", instance_tag="0123abcd"),
                             host_options=dict(mirror_dir=tmp_path, instance_tag="0123abcd"))
    app = FastAPI()
    app.state.session_manager = mgr
    app.state.services = build_services(session_manager=mgr)
    app.include_router(routes_mod.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: True
    tmux, socket, name = probe.tmux_path, "carnivore-remote", "carnivore_p2 real"

    def row() -> dict:
        with closing(connect(db_path_for(state), create=False)) as conn:
            conn.row_factory = __import__("sqlite3").Row
            return dict(conn.execute("SELECT * FROM sessions WHERE host_key = 'rsshost' "
                                     "ORDER BY id DESC LIMIT 1").fetchone())

    pre = make_pool(dest, scratch)
    assert (await pre.connect()).state == UP
    before = await pre.run(script='[ -e "$HOME/.cache/carnivore" ] && echo kept || echo new',
                           timeout=15)
    server_before = (await pre.run([tmux, "-L", socket, "has-session"], timeout=15)).returncode == 0
    found = await pre.run(script=_FIND_CONVERSATION, timeout=30)
    await pre.disconnect()
    assert found.returncode == 0, "the far box holds no conversation whose folder still exists"
    uuid, cwd = found.stdout_text.strip().split("|", 1)
    try:
        session = await mgr.create_session(session_id="ses_1048a001", working_dir=cwd,
                                           auto_start_claude=False, project_name="p2 real",
                                           host_key="rsshost")
        assert session.tmux_session == name
        with closing(connect(db_path_for(state), create=False)) as conn:
            conn.execute("UPDATE sessions SET claude_session_uuid = ?, agent_type = 'claude' "
                         "WHERE host_key = 'rsshost'", (uuid,))
            conn.commit()
        host = mgr.hosts._hosts["rsshost"]
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t/api/v1") as client:
            renamed = await client.patch(f"/sessions/{session.id}/name",
                                         json={"new_name": "far p2 real"})
            assert renamed.status_code == 200, renamed.text
            assert row()["title"] == "far p2 real"
            killed = await host.command("kill-session", "-t", f"={name}")
            assert killed.ok
            await mgr.list_session_infos()
            stopped = row()
            assert stopped["lifecycle"] == "stopped", stopped["lifecycle"]
            resp = await client.post(f"/sessions/{stopped['session_uuid']}/restart")
            assert resp.status_code == 201, resp.text
            body = resp.json()
        assert (body["conversation"], body["row_reused"], body["session"]["tmux_session"]) == (
            "resumed", True, name), body
        after = row()
        assert (after["id"], after["lifecycle"], after["title"]) == (
            stopped["id"], "running", "far p2 real")
        started = await host.command("list-panes", "-t", f"={name}", "-F",
                                     "#{pane_dead} #{pane_start_command}")
        text = b"".join(started.lines).decode()
        assert f"'--resume' '{uuid}'" in text, text
        print(f"\n#1048 on {TARGET}: renamed, stopped outside, restarted {uuid[:8]} on the host "
              f"onto row {after['id']}: {text.strip()[:120]}")
        for sid in list(mgr._registry.backends):
            await mgr.destroy_session(sid)
    finally:
        for backend in list(mgr._registry.backends.values()):
            await backend.stop()
        host = mgr.hosts._hosts.get("rsshost")
        if host is not None:
            await host.channel.stop()
            await host.exec([tmux, "-L", socket, "kill-session", "-t", f"={name}"])
            if not server_before:
                await host.exec([tmux, "-L", socket, "kill-server"])
            await asyncio.sleep(1.0)
            stray = await host.exec(script=f"ps -axo pid=,command= | grep -F -- '--resume {uuid}' "
                                           "| grep -v grep | awk '{print $1}'")
            for pid in stray.stdout_text.split():
                await host.exec(script=f"kill {int(pid)} 2>/dev/null; exit 0")
            alive = await host.exec(script=f"ps -axo command= | grep -F -- '--resume {uuid}' "
                                           "| grep -v grep | head -1")
            if before.stdout_text.strip() == "new":
                await host.exec(script='rm -rf "$HOME/.cache/carnivore"')
            left = await host.exec(script='[ -e "$HOME/.cache/carnivore" ] && echo kept || echo gone')
            server_left = (await host.exec([tmux, "-L", socket, "has-session"])).returncode == 0
        await mgr.hosts.close_all()
    assert host is not None, "cleanup could not reach the host"
    assert not alive.stdout_text.strip(), "the far claude was left running"
    assert server_left == server_before, "the far server was left running"
    assert left.stdout_text.strip() == ("kept" if before.stdout_text.strip() == "kept" else "gone")
    assert no_master_left(scratch)
