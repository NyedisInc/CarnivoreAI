
from __future__ import annotations

import asyncio
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

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_lsc_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_lsc_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.config import settings
from src.core.session_manager import SessionManager
from src.core.session_startup_gate import STARTUP_TAIL_RECHECK_SECONDS
from src.core.tmux_backend import TmuxBackend
from src.models import Session, SessionStatus
from tests.s7_helpers import migrated_connection
from tests.socket_guard import TEST_SOCKET_NAME

requires_tmux = pytest.mark.skipif(
    shutil.which("tmux") is None, reason="tmux not on PATH"
)

MAX_DATASTORE_OPENS_PER_LISTING = 4

LIVE_SESSIONS = 4


def _tmux(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["tmux", "-L", TEST_SOCKET_NAME, *args],
        capture_output=True,
        text=True,
        check=False,
    )


class _TmuxCallCounter:

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.argvs: list[tuple] = []

    def install(self, monkeypatch) -> None:
        original = TmuxBackend._run_tmux_sync
        calls = self.calls
        argvs = self.argvs

        def counting(self_backend, *args, **kwargs):
            if args:
                calls.append(str(args[0]))
            argvs.append(args)
            return original(self_backend, *args, **kwargs)

        monkeypatch.setattr(TmuxBackend, "_run_tmux_sync", counting)

    def count_of(self, subcommand: str) -> int:
        return sum(1 for c in self.calls if c == subcommand)

    def reset(self) -> None:
        self.calls.clear()


def _shorten_the_grace_window(monkeypatch) -> None:
    from src.core import session_startup_gate as gate

    for func in (gate.should_capture_tail, gate.resolve_startup_gate):
        patched = dict(func.__kwdefaults__)
        patched["grace_seconds"] = 0
        monkeypatch.setattr(func, "__kwdefaults__", patched)


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
    _shorten_the_grace_window(monkeypatch)

    manager = SessionManager()
    names: list[str] = []
    try:
        for index in range(LIVE_SESSIONS):
            name = f"cloude_cost_{index}_{uuid.uuid4().hex[:6]}"
            created = _tmux(
                "new-session", "-d",
                "-s", name,
                "-c", str(tmp_path),
                "-x", "132", "-y", "40",
            )
            assert created.returncode == 0, created.stderr
            names.append(name)

            session_id = f"ses_cost_{index}"
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
async def test_listing_tmux_subprocesses_do_not_grow_with_session_count(
    live_manager,
    monkeypatch,
):
    manager, names = live_manager
    counter = _TmuxCallCounter()
    counter.install(monkeypatch)

    infos = await manager.list_session_infos()
    assert len(infos) == LIVE_SESSIONS, (
        "the pass must still return every live session - a cheaper pass "
        f"that loses rows is not the fix. got {len(infos)}"
    )

    has_session = counter.count_of("has-session")
    assert has_session == 0, (
        f"the pass spawned {has_session} 'tmux has-session' calls for "
        f"{LIVE_SESSIONS} sessions. Existence is already in the bulk "
        "'list-panes -a' row this same pass fetched; asking tmux again, "
        "once per session, is what put 377 ms of blocking subprocess on "
        "the event loop and turned a listing cost into keystroke lag."
    )
    assert len(counter.calls) < 2 * LIVE_SESSIONS, (
        f"one listing pass spawned {len(counter.calls)} tmux "
        f"subprocesses for {LIVE_SESSIONS} sessions: {counter.calls}. "
        "The cost of a pass must not grow with the number of sessions."
    )


@requires_tmux
@pytest.mark.asyncio
async def test_a_second_listing_pass_re_reads_no_pane_tails(
    live_manager,
    monkeypatch,
):
    manager, names = live_manager
    counter = _TmuxCallCounter()
    counter.install(monkeypatch)

    await manager.list_session_infos()
    first_pass_captures = counter.count_of("capture-pane")
    assert first_pass_captures == LIVE_SESSIONS, (
        "the FIRST look at a hookless, long-lived pane must still happen "
        "or the startup gate has been deleted rather than throttled. "
        f"expected {LIVE_SESSIONS} captures, got {first_pass_captures}"
    )

    counter.reset()
    await manager.list_session_infos()
    assert counter.count_of("capture-pane") == 0, (
        f"a second listing pass re-read {counter.count_of('capture-pane')} "
        "pane tails inside the "
        f"{STARTUP_TAIL_RECHECK_SECONDS}s recheck window. The verdict "
        "from the first read is on the ledger and still stands; paying "
        "for it again every poll is 349 ms of blocked event loop per "
        "pass on a box with 13 sessions."
    )


@requires_tmux
@pytest.mark.asyncio
async def test_the_throttled_pass_still_answers_the_startup_gate(
    live_manager,
    monkeypatch,
):
    manager, names = live_manager
    counter = _TmuxCallCounter()
    counter.install(monkeypatch)

    first = {i.tmux_session: i.startup_gate for i in await manager.list_session_infos()}
    counter.reset()
    second = {i.tmux_session: i.startup_gate for i in await manager.list_session_infos()}

    assert counter.count_of("capture-pane") == 0, "the second pass should be throttled"
    assert first == second, (
        "the startup gate changed between two polls with nothing else "
        f"changing: {first} then {second}. A throttled read must reuse "
        "the verdict it already measured, not fall back to 'unknown'."
    )




class _DatastoreOpenCounter:

    def __init__(self) -> None:
        self.count = 0

    def install(self, monkeypatch) -> None:
        from src.core import db as db_module

        original = db_module.connect
        counter = self

        def counting(*args, **kwargs):
            counter.count += 1
            return original(*args, **kwargs)

        monkeypatch.setattr(db_module, "connect", counting)

    def reset(self) -> None:
        self.count = 0


@requires_tmux
@pytest.mark.asyncio
async def test_attachable_listing_opens_one_datastore_connection(
    live_manager,
    monkeypatch,
):
    manager, names = live_manager
    counter = _DatastoreOpenCounter()
    counter.install(monkeypatch)

    listing = manager.list_attachable_sessions()
    assert len(listing.sessions) >= LIVE_SESSIONS, (
        "the pass must still return every attachable session - a cheaper "
        f"pass that loses rows is not the fix. got {len(listing.sessions)}"
    )
    assert counter.count <= MAX_DATASTORE_OPENS_PER_LISTING, (
        f"one attachable listing opened the datastore {counter.count} "
        f"times for {len(listing.sessions)} rows, over the "
        f"{MAX_DATASTORE_OPENS_PER_LISTING} a pass is allowed. The title, "
        "the row identity and the recorded launch are three columns of "
        "ONE row under ONE key; fetching them with three connections per "
        "row is what put 33 ms of blocking SQLite on the event loop."
    )


@requires_tmux
@pytest.mark.asyncio
async def test_attachable_listing_still_decorates_every_row(
    live_manager,
    monkeypatch,
):
    manager, names = live_manager

    listing = manager.list_attachable_sessions()
    rows = {r["name"]: r for r in listing.sessions if r.get("name")}
    for name in names:
        assert name in rows, f"{name} vanished from the attachable listing"
        row = rows[name]
        for key in (
            "label", "session_row_id", "parent_session_id",
            "agent_type", "agent_family", "agent_family_source",
            "agent_wrapper_label", "pinned_theme", "status", "unread",
        ):
            assert key in row, (
                f"row {name} lost its {key!r} decoration - reading the "
                "stored row once must change how many times it is "
                "fetched, never what the listing says"
            )


@requires_tmux
def test_attachable_listing_reads_tmux_in_one_spawn(live_manager, monkeypatch):
    manager, names = live_manager
    counter = _TmuxCallCounter()
    counter.install(monkeypatch)

    listing = manager.list_attachable_sessions()

    assert listing.ok and {r["name"] for r in listing.sessions} >= set(names)
    spawns = [argv for argv in counter.argvs if "list-sessions" in argv or "list-panes" in argv]
    assert len(spawns) == 1, f"the attachable pass spawned {len(spawns)} listing processes: {spawns}"
    assert "list-sessions" in spawns[0] and "list-panes" in spawns[0]
