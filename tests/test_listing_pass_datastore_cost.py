
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from contextlib import closing
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_lpd_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_lpd_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.config import settings
from src.core.session_manager import SessionManager
from src.core.tmux_backend import TmuxBackend
from src.models import Session, SessionStatus
from tests.s7_helpers import migrated_connection
from tests.socket_guard import TEST_SOCKET_NAME

requires_tmux = pytest.mark.skipif(
    shutil.which("tmux") is None, reason="tmux not on PATH"
)

LIVE_SESSIONS = 4

MAX_DATASTORE_OPENS_PER_LISTING = 3


def _tmux(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["tmux", "-L", TEST_SOCKET_NAME, *args],
        capture_output=True,
        text=True,
        check=False,
    )


class _DatastoreOpenCounter:

    def __init__(self) -> None:
        self.count = 0
        self.by_caller: dict = {}

    def install(self, monkeypatch) -> None:
        import traceback

        from src.core import db as db_module

        original = db_module.connect
        counter = self

        def counting(*args, **kwargs):
            counter.count += 1
            stack = traceback.extract_stack()[:-1]
            named = [
                frame.name
                for frame in stack
                if "session_manager" in frame.filename
                or "seed" in frame.filename
            ]
            caller = named[-2] if len(named) >= 2 else (named[-1] if named else "?")
            counter.by_caller[caller] = counter.by_caller.get(caller, 0) + 1
            return original(*args, **kwargs)

        monkeypatch.setattr(db_module, "connect", counting)

    def snapshot(self) -> dict:
        taken = {"total": self.count, "by_caller": dict(self.by_caller)}
        self.count = 0
        self.by_caller = {}
        return taken


@pytest.fixture
def live_manager(tmp_path, monkeypatch):
    log_dir = tmp_path / "logs"
    state = tmp_path / "state"
    log_dir.mkdir()
    state.mkdir()
    monkeypatch.setattr(settings, "log_directory", str(log_dir))
    monkeypatch.setattr(settings, "state_dir_override", str(state))
    with closing(migrated_connection(state)):
        pass

    manager = SessionManager()
    names: list[str] = []
    try:
        for index in range(LIVE_SESSIONS):
            name = f"cloude_passcost_{index}_{uuid.uuid4().hex[:6]}"
            created = _tmux(
                "new-session", "-d",
                "-s", name,
                "-c", str(tmp_path),
                "-x", "132", "-y", "40",
                "sleep 600",
            )
            assert created.returncode == 0, created.stderr
            names.append(name)

            session_id = f"ses_passcost_{index}"
            backend = TmuxBackend(
                session_id=session_id,
                working_dir=tmp_path,
                on_output=None,
                socket_name=TEST_SOCKET_NAME,
                session_name=name,
            )
            manager._registry.backends[session_id] = backend
            manager._registry.sessions[session_id] = Session(
                id=session_id,
                status=SessionStatus.RUNNING,
                working_dir=str(tmp_path),
                created_at=datetime.utcnow(),
            )
        yield manager, names
    finally:
        _tmux("kill-server")


@requires_tmux
@pytest.mark.asyncio
async def test_the_listing_pass_opens_a_constant_number_of_connections(
    live_manager,
    monkeypatch,
):
    manager, names = live_manager
    counter = _DatastoreOpenCounter()
    counter.install(monkeypatch)

    infos = await manager.list_session_infos()
    assert len(infos) == LIVE_SESSIONS, (
        "the pass must still return every live session - a cheaper pass "
        f"that loses rows is not the fix. got {len(infos)}"
    )
    assert counter.count <= MAX_DATASTORE_OPENS_PER_LISTING, (
        f"one /sessions/list pass opened the datastore {counter.count} "
        f"times for {LIVE_SESSIONS} sessions, over the "
        f"{MAX_DATASTORE_OPENS_PER_LISTING} it is allowed. By caller: "
        f"{counter.by_caller}. Most of these run in a worker thread and "
        "cost the event loop nothing, so this is disk and SQLite "
        "contention with the writers rather than terminal lag - but a "
        "reader that is ALSO on the loop is felt as lag in the TERMINAL "
        "rather than as a slow list. Put the read in the bulk index "
        "instead of raising this bound."
    )


@requires_tmux
@pytest.mark.asyncio
async def test_the_seed_takes_no_connection_of_its_own_on_this_pass(
    live_manager,
    monkeypatch,
):
    manager, _names = live_manager

    counter = _DatastoreOpenCounter()
    counter.install(monkeypatch)
    await manager.list_session_infos()
    shipped = counter.snapshot()

    assert shipped["by_caller"].get("read_instance_row", 0) == 0, (
        "the status seed opened its own connection per session despite "
        f"the pass having taken a bulk index. By caller: {shipped}"
    )
    assert shipped["total"] <= 1, (
        "the gather must open at most one connection (its thread's reused one), "
        f"not one per reader or per pass. By caller: {shipped}"
    )
    assert shipped["by_caller"].get("_writable_datastore_connection", 0) == 0, (
        f"a name-keyed read opened a writable connection. By caller: {shipped}"
    )
    assert shipped["by_caller"].get("_instance_index_for_listing", 0) == 0, (
        f"the bulk index opened a connection of its own. By caller: {shipped}"
    )

    for session_id in list(manager._registry.sessions.keys()):
        manager._session_info_for(session_id)
    per_row = counter.snapshot()

    opened = per_row["by_caller"].get("read_instance_row", 0) - shipped[
        "by_caller"
    ].get("read_instance_row", 0)
    assert opened == 0, (
        "single-session listing independently gathered attention evidence: "
        f"{per_row}"
    )
