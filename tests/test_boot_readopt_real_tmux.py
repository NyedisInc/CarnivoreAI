
from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from contextlib import closing
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_brt_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_brt_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.config import settings
from src.core.db import connect, db_path_for
from src.core.db_models import SESSION_ORIGIN_CREATED
from src.core.session_boot_readopt import READOPT_RAN, readopt_surviving_sessions
from src.core.session_identity import record_instance
from src.core.session_manager import SessionManager
from src.core.tmux_backend import TmuxBackend
from tests.s7_helpers import migrated_connection
from tests.socket_guard import TEST_SOCKET_NAME

requires_tmux = pytest.mark.skipif(
    shutil.which("tmux") is None, reason="tmux not on PATH"
)




def _tmux(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["tmux", "-L", TEST_SOCKET_NAME, *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _create_session_like_the_app(name: str, session_id: str, cwd: Path) -> None:
    result = _tmux(
        "new-session", "-d",
        "-s", name,
        "-c", str(cwd),
        "-x", "132", "-y", "40",
        "-e", f"CLOUDECODE_SESSION_ID={session_id}",
        "-e", "TERM=xterm-256color",
    )
    assert result.returncode == 0, f"tmux new-session failed: {result.stderr}"


def _field_by_session(list_cmd: str, field: str) -> dict:
    extra = ["-a"] if list_cmd == "list-panes" else []
    result = _tmux(
        list_cmd, *extra, "-F", "#{session_name}\t" + field
    )
    out = {}
    for line in result.stdout.splitlines():
        if "\t" not in line:
            continue
        session_name, _, value = line.partition("\t")
        out[session_name] = value.strip()
    return out


def _epoch_of(name: str) -> int:
    epochs = _field_by_session("list-sessions", "#{session_created}")
    assert name in epochs, f"tmux does not list {name}: {sorted(epochs)}"
    return int(epochs[name])


def _session_env(name: str) -> dict:
    result = _tmux("show-environment", "-t", name)
    if result.returncode != 0:
        return {}
    env = {}
    for line in result.stdout.splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            env[key] = value
    return env


def _pane_pipe(name: str) -> str:
    return _field_by_session("list-panes", "#{pane_pipe}").get(name, "")




@pytest.fixture
def live_state(tmp_path, monkeypatch):
    log_dir = tmp_path / "logs"
    state = tmp_path / "state"
    log_dir.mkdir()
    state.mkdir()
    monkeypatch.setattr(settings, "log_directory", str(log_dir))
    monkeypatch.setattr(settings, "state_dir_override", str(state))
    with closing(migrated_connection(state)):
        pass
    try:
        yield state
    finally:
        _tmux("kill-server")


def _seed_row(state_dir: Path, manager: SessionManager, *, name: str,
              epoch: int, working_dir: str) -> None:
    with closing(connect(db_path_for(state_dir))) as conn:
        record_instance(
            conn,
            socket=manager.tmux_socket_name(),
            name=name,
            epoch=epoch,
            origin=SESSION_ORIGIN_CREATED,
            working_dir=working_dir,
        )
        conn.commit()


async def _drop_backends(manager: SessionManager) -> None:
    for backend in list(manager._registry.backends.values()):
        task = getattr(backend, "_reader_task", None)
        if task is not None:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass




@requires_tmux
@pytest.mark.asyncio
async def test_owned_backend_can_attach_to_an_existing_pane(live_state):
    name = f"cloude_owned_{uuid.uuid4().hex[:6]}"
    _create_session_like_the_app(name, "ses_owned", Path.home())

    backend = TmuxBackend(
        session_id="ses_owned",
        working_dir=Path.home(),
        on_output=None,
        socket_name=TEST_SOCKET_NAME,
        session_name=name,
    )
    assert backend._is_external is False, (
        "this test is only meaningful against an OWNED backend - an "
        "external one satisfies the guard and cannot reproduce the bug"
    )
    assert backend._running is False

    try:
        await backend.attach_existing(needs_pipe_setup=True)
        assert backend._running is True
        assert _pane_pipe(name) == "1", (
            "attach_existing returned without establishing pipe-pane, so "
            "the websocket tailer would read an empty file forever"
        )
    finally:
        task = getattr(backend, "_reader_task", None)
        if task is not None:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass




@requires_tmux
@pytest.mark.asyncio
async def test_real_readopt_pass_holds_every_live_session_by_stored_id(
    live_state, tmp_path
):
    mgr = SessionManager()
    work = tmp_path / "work"
    work.mkdir()

    names = {
        f"cloude_readopt_a_{uuid.uuid4().hex[:6]}": "ses_real_a",
        f"cloude_readopt_b_{uuid.uuid4().hex[:6]}": "ses_real_b",
    }
    for name, sid in names.items():
        _create_session_like_the_app(name, sid, work)
        _seed_row(
            live_state, mgr,
            name=name, epoch=_epoch_of(name), working_dir=str(work),
        )

    mgr.hook_tokens.tmux_names = {sid: name for name, sid in names.items()}

    try:
        report = await readopt_surviving_sessions(mgr)

        assert report.outcome == READOPT_RAN
        assert report.failed == [], (
            f"every attach must succeed against a real socket: {report.failed}"
        )
        assert sorted(report.held) == sorted(names.values())

        for sid in names.values():
            assert sid in mgr._registry.sessions
            assert not sid.startswith("adopted:")

        assert {
            backend.tmux_session for backend in mgr._registry.backends.values()
        } == set(names)

        for name in names:
            assert _pane_pipe(name) == "1", f"{name} is held but not piped"
        for backend in mgr._registry.backends.values():
            assert backend._running is True

        for name, sid in names.items():
            session_env = _session_env(name)
            for suffix in ("SESSION_ID", "HOOK_TOKEN", "HOOK_URL"):
                legacy_key = f"CLOUDECODE_{suffix}"
                current_key = f"CARNIVORE_{suffix}"
                assert legacy_key in session_env, (
                    f"{legacy_key} missing from {name}'s session "
                    f"environment: {sorted(session_env)}"
                )
                assert current_key in session_env, (
                    f"{current_key} missing from {name}'s session "
                    f"environment: {sorted(session_env)}"
                )
                assert session_env[current_key] == session_env[legacy_key], (
                    f"{current_key} ({session_env[current_key]!r}) does not "
                    f"match {legacy_key} ({session_env[legacy_key]!r}) on {name}"
                )
            assert session_env["CLOUDECODE_SESSION_ID"] == sid
    finally:
        await _drop_backends(mgr)




@requires_tmux
@pytest.mark.asyncio
async def test_readopted_backend_streams_live_output_without_a_reattach(
    live_state,
):
    name = f"cloude_stream_{uuid.uuid4().hex[:6]}"
    _create_session_like_the_app(name, "ses_stream", Path.home())

    seen: list[bytes] = []

    async def _collect(chunk: bytes) -> None:
        seen.append(chunk)

    backend = TmuxBackend(
        session_id="ses_stream",
        working_dir=Path.home(),
        on_output=_collect,
        socket_name=TEST_SOCKET_NAME,
        session_name=name,
    )
    assert backend._is_external is False, (
        "the boot re-adopt builds an OWNED backend; an external one "
        "takes the other branch and cannot reproduce this"
    )

    try:
        await backend.attach_existing()

        marker = f"CLOUDE_STREAM_{uuid.uuid4().hex[:8]}"
        _tmux("send-keys", "-t", name, f"echo {marker}", "Enter")

        deadline = asyncio.get_event_loop().time() + 5.0
        while asyncio.get_event_loop().time() < deadline:
            if marker.encode() in b"".join(seen):
                break
            await asyncio.sleep(0.05)

        assert marker.encode() in b"".join(seen), (
            "output produced AFTER attach_existing never reached "
            "on_output, so the websocket had nothing to forward and the "
            "browser would show a frozen terminal until the next attach "
            f"repainted it. pane_pipe={_pane_pipe(name)!r}, "
            f"bytes_seen={len(b''.join(seen))}"
        )
    finally:
        task = getattr(backend, "_reader_task", None)
        if task is not None:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass


@requires_tmux
@pytest.mark.asyncio
async def test_output_written_before_the_reader_opens_is_still_delivered(
    live_state,
):
    name = f"cloude_offset_{uuid.uuid4().hex[:6]}"
    _create_session_like_the_app(name, "ses_offset", Path.home())

    seen: list[bytes] = []

    async def _collect(chunk: bytes) -> None:
        seen.append(chunk)

    backend = TmuxBackend(
        session_id="ses_offset",
        working_dir=Path.home(),
        on_output=_collect,
        socket_name=TEST_SOCKET_NAME,
        session_name=name,
    )

    try:
        await backend.attach_existing()

        payload = f"CLOUDE_OFFSET_{uuid.uuid4().hex[:8]}\r\n".encode()
        pipe_path = backend._resolve_pipe_path()
        with open(pipe_path, "ab") as handle:
            handle.write(payload)
            handle.flush()

        deadline = asyncio.get_event_loop().time() + 5.0
        while asyncio.get_event_loop().time() < deadline:
            if payload in b"".join(seen):
                break
            await asyncio.sleep(0.05)

        assert payload in b"".join(seen), (
            "bytes appended to the pipe file after attach_existing "
            "returned, but before the tail loop was first scheduled, "
            "never reached on_output. The stream starts wherever the "
            "event loop happened to get round to it rather than where "
            "the attach left off, so a session producing output at "
            "boot loses it silently. "
            f"recorded_offset={backend._adopt_tail_start_offset!r}, "
            f"pane_pipe={_pane_pipe(name)!r}, "
            f"bytes_seen={len(b''.join(seen))}"
        )
    finally:
        task = getattr(backend, "_reader_task", None)
        if task is not None:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass


@requires_tmux
@pytest.mark.asyncio
async def test_attach_to_a_dead_pane_still_succeeds(live_state):
    name = f"cloude_dead_{uuid.uuid4().hex[:6]}"
    _create_session_like_the_app(name, "ses_dead", Path.home())

    _tmux("set-option", "-t", name, "remain-on-exit", "on")
    _tmux("send-keys", "-t", name, "exit", "Enter")

    deadline = asyncio.get_event_loop().time() + 15.0
    while asyncio.get_event_loop().time() < deadline:
        dead = _field_by_session("list-panes", "#{pane_dead}").get(name, "")
        if dead == "1":
            break
        await asyncio.sleep(0.1)
    assert _field_by_session("list-panes", "#{pane_dead}").get(name) == "1", (
        "could not get the pane into the dead state this test is about"
    )

    backend = TmuxBackend(
        session_id="ses_dead",
        working_dir=Path.home(),
        on_output=None,
        socket_name=TEST_SOCKET_NAME,
        session_name=name,
    )

    try:
        await backend.attach_existing()

        assert backend._running is True
        assert backend._resolve_pipe_path().exists(), (
            "the fallback has to leave the tail loop a file to open, "
            "which is what touch() was always for"
        )
    finally:
        task = getattr(backend, "_reader_task", None)
        if task is not None:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
