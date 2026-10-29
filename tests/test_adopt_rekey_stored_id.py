
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
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_ark_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_ark_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
import src.api.routes as routes_mod
from src.config import settings
from src.core.db import connect, db_path_for
from src.core.db_models import SESSION_ORIGIN_CREATED
from src.core.session_identity import record_instance
from src.core.session_manager import SessionManager
from src.api.auth import require_auth
from tests.s7_helpers import migrated_connection
from tests.socket_guard import TEST_SOCKET_NAME

requires_tmux = pytest.mark.skipif(
    shutil.which("tmux") is None, reason="tmux not on PATH"
)

STORED_ID = "ses_rekey01"




def _tmux(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["tmux", "-L", TEST_SOCKET_NAME, *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _start_session(name: str, session_id: str, cwd: Path) -> None:
    result = _tmux(
        "new-session", "-d", "-s", name, "-c", str(cwd),
        "-x", "132", "-y", "40",
        "-e", f"CLOUDECODE_SESSION_ID={session_id}",
    )
    assert result.returncode == 0, f"tmux new-session failed: {result.stderr}"


def _epoch_of(name: str) -> int:
    result = _tmux("list-sessions", "-F", "#{session_name}\t#{session_created}")
    for line in result.stdout.splitlines():
        found, _, value = line.partition("\t")
        if found == name:
            return int(value.strip())
    raise AssertionError(f"tmux does not list {name}: {result.stdout!r}")


async def _drop_backends(manager: SessionManager) -> None:
    for backend in list(manager._registry.backends.values()):
        task = getattr(backend, "_reader_task", None)
        if task is not None:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass




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




@requires_tmux
@pytest.mark.asyncio
async def test_adopting_a_session_with_a_row_uses_the_stored_id(live_state,
                                                                tmp_path):
    mgr = SessionManager()
    work = tmp_path / "work"
    work.mkdir()
    name = f"cloude_rekey_{uuid.uuid4().hex[:6]}"

    _start_session(name, STORED_ID, work)
    _seed_row(live_state, mgr, name=name, epoch=_epoch_of(name),
              working_dir=str(work))
    mgr.hook_tokens.tokens[STORED_ID] = "tok_from_before_the_restart"
    mgr.hook_tokens.tmux_names[STORED_ID] = name

    try:
        result = await mgr.adopt_external_session(name)

        assert result["session"].id == STORED_ID
        assert STORED_ID in mgr._registry.sessions
        assert f"adopted:{name}" not in mgr._registry.sessions, (
            "the session was re-minted alongside its stored id"
        )
        assert result["session"].tmux_session == name
        assert result["session"].tmux_created_epoch == _epoch_of(name)
    finally:
        await _drop_backends(mgr)


@requires_tmux
@pytest.mark.asyncio
async def test_a_rekeyed_adoption_does_not_rotate_the_hook_token(live_state,
                                                                 tmp_path):
    mgr = SessionManager()
    work = tmp_path / "work"
    work.mkdir()
    name = f"cloude_rekey_{uuid.uuid4().hex[:6]}"
    original_token = "tok_the_agent_already_carries"

    _start_session(name, STORED_ID, work)
    _seed_row(live_state, mgr, name=name, epoch=_epoch_of(name),
              working_dir=str(work))
    mgr.hook_tokens.tokens[STORED_ID] = original_token
    mgr.hook_tokens.tmux_names[STORED_ID] = name

    try:
        await mgr.adopt_external_session(name)

        assert STORED_ID in mgr._registry.sessions

        assert mgr.hook_tokens.get(STORED_ID) == original_token, (
            "adoption rotated a credential the running agent cannot be "
            "handed a replacement for"
        )

        assert mgr.hook_tokens.get("ses_not_a_session") is None
        assert mgr.hook_tokens.name_for(STORED_ID) == name
    finally:
        await _drop_backends(mgr)




@requires_tmux
@pytest.mark.asyncio
async def test_adopting_a_session_with_no_row_still_mints_adopted(live_state,
                                                                  tmp_path):
    mgr = SessionManager()
    work = tmp_path / "work"
    work.mkdir()
    name = f"cloude_stranger_{uuid.uuid4().hex[:6]}"

    _start_session(name, "ses_not_ours", work)

    try:
        result = await mgr.adopt_external_session(name)

        assert result["session"].id == f"adopted:{name}"
        assert f"adopted:{name}" in mgr._registry.sessions
        assert mgr.hook_tokens.get(f"adopted:{name}")
    finally:
        await _drop_backends(mgr)




@requires_tmux
@pytest.mark.asyncio
async def test_adopting_a_pane_already_held_under_another_id_holds_it_once(
    live_state, tmp_path
):
    mgr = SessionManager()
    work = tmp_path / "work"
    work.mkdir()
    name = f"cloude_rekey_{uuid.uuid4().hex[:6]}"

    _start_session(name, STORED_ID, work)
    _seed_row(live_state, mgr, name=name, epoch=_epoch_of(name),
              working_dir=str(work))
    mgr.hook_tokens.tokens[STORED_ID] = "tok_the_agent_already_carries"
    mgr.hook_tokens.tmux_names[STORED_ID] = name

    stale_id = f"adopted:{name}"
    await mgr.adopt_external_session(name)
    mgr._registry.backends[stale_id] = mgr._registry.backends[STORED_ID]
    mgr._registry.sessions[stale_id] = mgr._registry.sessions[STORED_ID]
    assert len(mgr._registry.backends) == 2

    try:
        await mgr.adopt_external_session(name)

        assert list(mgr._registry.backends) == [STORED_ID], (
            f"one pane must leave one registration, got {list(mgr._registry.backends)}"
        )
        assert stale_id not in mgr._registry.sessions
    finally:
        await _drop_backends(mgr)


@requires_tmux
@pytest.mark.asyncio
async def test_adopting_the_same_session_twice_holds_it_once(live_state,
                                                             tmp_path):
    mgr = SessionManager()
    work = tmp_path / "work"
    work.mkdir()
    name = f"cloude_rekey_{uuid.uuid4().hex[:6]}"
    original_token = "tok_the_agent_already_carries"

    _start_session(name, STORED_ID, work)
    _seed_row(live_state, mgr, name=name, epoch=_epoch_of(name),
              working_dir=str(work))
    mgr.hook_tokens.tokens[STORED_ID] = original_token
    mgr.hook_tokens.tmux_names[STORED_ID] = name

    try:
        first = await mgr.adopt_external_session(name)
        second = await mgr.adopt_external_session(name)

        assert first["session"].id == second["session"].id == STORED_ID
        assert list(mgr._registry.sessions) == [STORED_ID]
        assert list(mgr._registry.backends) == [STORED_ID]
        assert mgr.hook_tokens.get(STORED_ID) == original_token
    finally:
        await _drop_backends(mgr)
