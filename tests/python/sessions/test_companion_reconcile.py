
from __future__ import annotations

import asyncio
import shutil
import subprocess
import uuid
from contextlib import closing
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.config import settings
from src.core.attention.evidence import REASON_PANE_DEAD
from src.core.companion_shell import ensure, reconcile
from src.core.companion_shell import index as companion_index
from src.core.db import connect, db_path_for
from src.core.db_models import SESSION_ORIGIN_OBSERVED
from src.core.notifications.sources.died import DEAD_READS, DiedTracker
from src.core.session_identity import record_instance
from src.core.session_manager import SessionManager
from src.core.session_sleep import LIFECYCLE_SOURCE_SLEPT, LIFECYCLE_SOURCE_SLEPT_BY_TIMER, mark_asleep
from src.core.sessions.pane_listing_cache import invalidate_pane_listing
from src.core.tmux_backend import TmuxBackend
from src.models import Session, SessionStatus
from tests.s7_helpers import migrated_connection
from tests.socket_guard import TEST_SOCKET_NAME

requires_tmux = pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux not on PATH")

AGENT_ID, CONSOLE_ID = "ses_f2c_agent", "ses_f2c_console"
RUNNING, STOPPED = "running", "stopped"


@pytest.mark.parametrize("agent, gone, action, reason", [
    (None, False, reconcile.PURGE, "agent_row_gone"),
    ({"lifecycle": RUNNING, "lifecycle_source": None}, False, reconcile.KEEP, "agent_running"),
    ({"lifecycle": RUNNING, "lifecycle_source": None}, True, reconcile.CLOSE, "agent_tmux_gone"),
    ({"lifecycle": STOPPED, "lifecycle_source": LIFECYCLE_SOURCE_SLEPT}, False, reconcile.CLOSE, "agent_asleep_or_closed"),
    ({"lifecycle": STOPPED, "lifecycle_source": LIFECYCLE_SOURCE_SLEPT_BY_TIMER}, False, reconcile.CLOSE, "agent_asleep_or_closed"),
    ({"lifecycle": STOPPED, "lifecycle_source": "closed_by_user"}, False, reconcile.CLOSE, "agent_asleep_or_closed"),
    ({"lifecycle": STOPPED, "lifecycle_source": "tmux_missing"}, False, reconcile.CLOSE, "agent_asleep_or_closed"),
    ({"lifecycle": STOPPED, "lifecycle_source": "tmux_list"}, False, reconcile.CLOSE, "agent_asleep_or_closed"),
    ({"lifecycle": RUNNING, "lifecycle_source": None, "archived_at": "2026-10-11T00:00:00Z"}, False, reconcile.CLOSE, "agent_archived"),
    ({"lifecycle": STOPPED, "lifecycle_source": "pane_dead"}, False, reconcile.KEEP, "agent_pane_dead_husk"),
    ({"lifecycle": STOPPED, "lifecycle_source": None}, False, reconcile.KEEP_UNKNOWN, "agent_stopped_unknown_source"),
    ({"lifecycle": STOPPED, "lifecycle_source": "import"}, False, reconcile.KEEP_UNKNOWN, "agent_stopped_unknown_source"),
    ({"lifecycle": "unknown", "lifecycle_source": "probe_failed"}, False, reconcile.KEEP_UNKNOWN, "agent_lifecycle_unmeasured"),
    ({"lifecycle": None, "lifecycle_source": None}, False, reconcile.KEEP_UNKNOWN, "agent_lifecycle_unmeasured"),
])
def test_the_close_and_keep_table(agent, gone, action, reason):
    verdict = reconcile.decide(agent, measured_gone=gone)
    assert (verdict.action, verdict.reason) == (action, reason)


def _tmux(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["tmux", "-L", TEST_SOCKET_NAME, *args], capture_output=True, text=True, check=False)


def _alive(name: str) -> bool:
    return _tmux("has-session", "-t", f"={name}").returncode == 0


def _row(state: Path, row_id: int) -> dict | None:
    with closing(connect(db_path_for(state), create=False)) as conn:
        found = conn.execute("SELECT * FROM sessions WHERE id = ?", (row_id,)).fetchone()
        return dict(found) if found else None


def _set_agent(state: Path, row_id: int, lifecycle: str, source: str | None) -> None:
    with closing(connect(db_path_for(state), create=False)) as conn:
        conn.execute("UPDATE sessions SET lifecycle = ?, lifecycle_source = ? WHERE id = ?", (lifecycle, source, row_id))
        conn.commit()


def _register(manager: SessionManager, sid: str, name: str, folder: Path) -> None:
    manager._registry.backends[sid] = TmuxBackend(
        session_id=sid, working_dir=folder, on_output=None, socket_name=TEST_SOCKET_NAME, session_name=name)
    manager._registry.register(
        Session(id=sid, status=SessionStatus.RUNNING, working_dir=str(folder), created_at=datetime.utcnow(), tmux_session=name),
        manager._registry.backends[sid])


@pytest.fixture
def world(tmp_path, monkeypatch):
    state, logs, folder = tmp_path / "state", tmp_path / "logs", tmp_path / "folder"
    for d in (state, logs, folder):
        d.mkdir()
    monkeypatch.setattr(settings, "log_directory", str(logs))
    monkeypatch.setattr(settings, "state_dir_override", str(state))
    names = {"agent": f"carnivore_f2c_a_{uuid.uuid4().hex[:6]}", "console": f"carnivore_f2c_c_{uuid.uuid4().hex[:6]}"}
    manager = SessionManager()
    try:
        rows = {}
        for role, name in names.items():
            made = _tmux("new-session", "-d", "-s", name, "-c", str(folder), "-x", "132", "-y", "40")
            assert made.returncode == 0, made.stderr
            epoch = int(_tmux("display-message", "-p", "-t", f"={name}:", "#{session_created}").stdout.strip())
            with closing(migrated_connection(state)) as conn:
                rows[role] = record_instance(conn, socket=TEST_SOCKET_NAME, name=name, epoch=epoch,
                                             origin=SESSION_ORIGIN_OBSERVED, agent_type="claude" if role == "agent" else "shell",
                                             working_dir=str(folder)).session_id
        _register(manager, AGENT_ID, names["agent"], folder)
        _register(manager, CONSOLE_ID, names["console"], folder)
        index = companion_index.install(manager._registry, state)
        app = SimpleNamespace(state=SimpleNamespace(session_manager=manager, companion_index=index))
        request = SimpleNamespace(app=app, scope={}, headers={}, query_params={})
        yield SimpleNamespace(manager=manager, state=state, app=app, request=request, index=index, rows=rows,
                              names=names, folder=folder)
    finally:
        reconcile._active = None
        ensure._LOCKS.clear()
        _tmux("kill-server")


@requires_tmux
@pytest.mark.asyncio
async def test_keep_rules_then_a_sleeping_agent_closes_the_shell_and_keeps_the_uploads(world):
    shell = await ensure.ensure(world.request, AGENT_ID)
    sname, srow = shell.tmux_session, shell.session_row_id
    uploads = world.folder / ".cloude_uploads"
    uploads.mkdir()
    (uploads / "keep.txt").write_text("mine")

    for lifecycle, source in ((RUNNING, None), (STOPPED, "pane_dead"), (STOPPED, None), ("unknown", "probe_failed")):
        _set_agent(world.state, world.rows["agent"], lifecycle, source)
        assert await reconcile.run_once(world.app) == 0
        assert _alive(sname), (lifecycle, source)
    _set_agent(world.state, world.rows["agent"], RUNNING, None)

    for _ in range(80):
        _tmux("send-keys", "-t", f"={sname}:", "exit", "Enter")
        if (await ensure.read(world.app, AGENT_ID)).pane == "dead":
            break
        await asyncio.sleep(0.25)
    else:
        pytest.fail("the shell's pane never read dead")
    assert await reconcile.run_once(world.app) == 0 and _alive(sname) and _alive(world.names["agent"])
    from src.core.attention_wiring import build_attention_watcher

    emitted: list = []
    tracker = DiedTracker(world.manager, SimpleNamespace(), emit=emitted.append)
    dead = SimpleNamespace(verdict=SimpleNamespace(reason=REASON_PANE_DEAD))
    watcher = build_attention_watcher(world.manager, app_state=None)
    fired = []
    for _ in range(DEAD_READS + 1):
        fired += [t.session_id for t in watcher._list_targets() if tracker.observe(t, dead)]
    assert set(fired) == {AGENT_ID, CONSOLE_ID}
    assert shell.session_id not in fired and shell.session_id not in {t.session_id for t in watcher._list_targets()}

    with closing(connect(db_path_for(world.state), create=False)) as conn:
        epoch = int(_tmux("display-message", "-p", "-t", f"={world.names['agent']}:", "#{session_created}").stdout.strip())
        assert mark_asleep(conn, row_id=world.rows["agent"], tmux_name=world.names["agent"], tmux_created_epoch=epoch,
                           source=LIFECYCLE_SOURCE_SLEPT_BY_TIMER) == 1
        conn.commit()
    assert await reconcile.run_once(world.app) == 1
    assert not _alive(sname)
    assert (uploads / "keep.txt").read_text() == "mine"
    assert _row(world.state, srow)["lifecycle"] == STOPPED and _row(world.state, srow)["lifecycle_source"] == "closed_with_agent"
    assert shell.session_id not in world.manager._registry.sessions
    assert world.index.is_hidden_name(sname)
    assert await reconcile.run_once(world.app) == 0

    rebuilt = companion_index.CompanionIndex()
    with closing(connect(db_path_for(world.state), create=False)) as conn:
        assert rebuilt.load(conn) == 1
    assert rebuilt.is_hidden_name(sname) and rebuilt.shell_row_for(world.rows["agent"]) == srow


@requires_tmux
@pytest.mark.asyncio
async def test_no_frame_no_pass_and_a_session_frame_runs_exactly_one(world):
    await ensure.ensure(world.request, AGENT_ID)
    rec = reconcile.install(world.app, asyncio.get_running_loop())
    await asyncio.sleep(0.3)
    assert rec.runs == 0
    reconcile.on_hub_publish("session.status")
    reconcile.on_hub_publish(None)
    await asyncio.sleep(0.1)
    assert rec.runs == 0
    for _ in range(5):
        reconcile.on_hub_publish("sessions.changed")
    await asyncio.sleep(0.3)
    assert 1 <= rec.runs <= 2
    before = rec.runs
    await asyncio.sleep(0.3)
    assert rec.runs == before


@requires_tmux
@pytest.mark.asyncio
async def test_a_purged_agent_takes_its_already_closed_shell_row_with_it(world):
    shell = await ensure.ensure(world.request, AGENT_ID)
    with closing(connect(db_path_for(world.state), create=False)) as conn:
        epoch = int(_tmux("display-message", "-p", "-t", f"={world.names['agent']}:", "#{session_created}").stdout.strip())
        assert mark_asleep(conn, row_id=world.rows["agent"], tmux_name=world.names["agent"], tmux_created_epoch=epoch,
                           source=LIFECYCLE_SOURCE_SLEPT) == 1
        conn.commit()
    assert await reconcile.run_once(world.app) == 1 and not _alive(shell.tmux_session)
    with closing(connect(db_path_for(world.state), create=False)) as conn:
        conn.execute("DELETE FROM sessions WHERE id = ?", (world.rows["agent"],))
        conn.commit()
    assert await reconcile.run_once(world.app) == 1
    assert _row(world.state, shell.session_row_id) is None
    assert world.index.shell_row_for(world.rows["agent"]) is None and not world.index.is_hidden_name(shell.tmux_session)
    assert await reconcile.run_once(world.app) == 0


@requires_tmux
@pytest.mark.asyncio
async def test_a_live_shell_whose_agent_row_vanished_is_closed_and_purged(world):
    shell = await ensure.ensure(world.request, AGENT_ID)
    with closing(connect(db_path_for(world.state), create=False)) as conn:
        conn.execute("DELETE FROM sessions WHERE id = ?", (world.rows["agent"],))
        conn.commit()
    assert await reconcile.run_once(world.app) == 1
    assert not _alive(shell.tmux_session) and _row(world.state, shell.session_row_id) is None


@requires_tmux
@pytest.mark.asyncio
async def test_the_boot_pass_measures_a_dead_agent_whose_row_still_reads_running(world):
    shell = await ensure.ensure(world.request, AGENT_ID)
    assert _tmux("kill-session", "-t", f"={world.names['agent']}").returncode == 0
    assert await reconcile.run_once(world.app) == 0 and _alive(shell.tmux_session)
    assert await reconcile.run_once(world.app, measure_agents=True) == 1
    assert not _alive(shell.tmux_session)


@requires_tmux
@pytest.mark.asyncio
async def test_the_ghost_reap_closes_the_shell_of_an_agent_whose_tmux_vanished(world):
    shell = await ensure.ensure(world.request, AGENT_ID)
    reconciler = reconcile.install(world.app, asyncio.get_running_loop())
    assert _tmux("kill-session", "-t", f"={world.names['agent']}").returncode == 0
    invalidate_pane_listing(TEST_SOCKET_NAME)
    assert _alive(shell.tmux_session)
    await world.manager.list_session_infos()
    try:
        for _ in range(100):
            if reconciler.runs and not reconciler._running:
                break
            await asyncio.sleep(0.1)
    finally:
        if reconciler._task is not None and not reconciler._task.done():
            reconciler._task.cancel()
            await asyncio.gather(reconciler._task, return_exceptions=True)
    assert not _alive(shell.tmux_session)
    assert _row(world.state, shell.session_row_id)["lifecycle_source"] == "closed_with_agent"
    assert CONSOLE_ID in world.manager._registry.sessions and _alive(world.names["console"])


@requires_tmux
@pytest.mark.asyncio
async def test_a_failed_close_that_dropped_the_registration_is_retried_by_the_next_pass(world):
    from src.core.session_ghost_reap import drop_registration

    shell = await ensure.ensure(world.request, AGENT_ID)
    for sid in list(world.manager._registry.registered_ids_for_tmux_name(shell.tmux_session)):
        await drop_registration(world.manager, sid, reason="test_failed_close", tmux_name=shell.tmux_session)
    _set_agent(world.state, world.rows["agent"], STOPPED, LIFECYCLE_SOURCE_SLEPT)
    assert _alive(shell.tmux_session)
    assert await reconcile.run_once(world.app) == 1
    assert not _alive(shell.tmux_session)
    assert _row(world.state, shell.session_row_id)["lifecycle_source"] == "closed_with_agent"
    assert await reconcile.run_once(world.app) == 0


def test_the_boot_pass_is_chained_on_the_readopt_task(monkeypatch):
    calls: list = []
    monkeypatch.setattr(reconcile, "request", lambda *a, **k: calls.append(k))
    reconcile.request_when_done(None)
    assert calls == [{"measure_agents": True}]

    async def scenario() -> None:
        task = asyncio.get_running_loop().create_future()
        reconcile.request_when_done(task)
        assert len(calls) == 1
        task.set_result(None)
        await asyncio.sleep(0)
        assert len(calls) == 2 and calls[1] == {"measure_agents": True}

    asyncio.run(scenario())
