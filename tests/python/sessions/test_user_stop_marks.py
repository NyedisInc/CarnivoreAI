from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from src.api import session_attach_routes, session_crud_routes, worktree_routes
from src.core import session_journal_store as store
from src.core import session_journal_task as task
from src.core.session_journal_measure import Measurement
from src.core.session_journal_observe import PaneFacts, observe
from src.core.session_ops import close_intent, close_record

T0 = "2026-09-24T07:00:00Z"
ROW = {"id": 1, "session_uuid": "A", "tmux_name": "cloude_a", "tmux_created_epoch": 11, "title": "a", "lifecycle": "running",
       "lifecycle_source": "create", "last_seen_running_at": T0, "archived_at": None, "claude_session_uuid": "A-c",
       "working_dir": "/w", "agent_type": "claude-skip-permissions"}
PANE = PaneFacts(name="cloude_a", epoch=11, claude_pid=1, argv="claude", observed_flags=[], conversation="A-c",
                 conversation_source="claude_pid_record", cwd="/w")


class Harness:

    def __init__(self, tmp_path, monkeypatch):
        self.dir = tmp_path
        j = observe(store.empty_journal(), listing_ok=True, listing_complete=True, panes=[PANE],
                    rows_by_instance={("cloude_a", 11): ROW}, groups={}, now_iso=T0).journal
        j["boot"] = {"epoch": 1, "source": "sysctl", "recorded_at": T0}
        store.save_journal(tmp_path, j)
        self.rows = [ROW]
        monkeypatch.setattr(task, "measure", self._measure)
        monkeypatch.setattr(task.store, "now_iso", lambda: "2026-09-24T07:05:00Z")

    def _measure(self, *a, **k):
        return Measurement(listing_ok=True, listing_complete=True, listing_reason=None, panes=[], writers=[],
                           rows=self.rows, groups={}, rows_ok=True, writers_ok=True)

    def run_pass(self):
        task.observe_pass(self.dir, None, "cloude", self.dir / "db")
        return store.load_journal(self.dir).journal.get("offer")


@pytest.fixture
def harness(tmp_path, monkeypatch):
    return Harness(tmp_path, monkeypatch)


def _quiet_route(monkeypatch):
    async def no_confirm(**kw):
        return None
    monkeypatch.setattr(session_crud_routes.swarm_leaders, "require_confirm", no_confirm)
    monkeypatch.setattr(session_attach_routes.swarm_leaders, "require_confirm", no_confirm)
    monkeypatch.setattr(session_crud_routes.session_change_notice, "publish", lambda *a, **k: None)
    monkeypatch.setattr(session_crud_routes.save_triggers, "schedule_for_instance", lambda *a, **k: None)


class FakeBackend:
    tmux_session = "cloude_a"
    socket_name = "cloude"

    async def session_created_epoch(self):
        return 11


def _delete_request(manager, backend):
    registry = SimpleNamespace(get_backend=lambda sid: backend, current_backend=lambda: backend)
    state = SimpleNamespace(session_manager=manager, local_servers=SimpleNamespace(clear_session=_noop),
                            services=SimpleNamespace(registry=registry))
    return SimpleNamespace(app=SimpleNamespace(state=state))


async def _noop(*a, **k):
    return None


def test_delete_sessions_holds_the_mark_across_the_kill_and_the_row_write(harness, monkeypatch):
    _quiet_route(monkeypatch)
    seen = {}

    async def destroy_session(session_id=None):
        seen["during_kill"] = harness.run_pass()

    async def row_written(socket, name, epoch, host):
        seen["at_write"] = harness.run_pass()
        return 1

    monkeypatch.setattr(close_record, "mark_closed_in_datastore", row_written)
    manager = SimpleNamespace(destroy_session=destroy_session)
    asyncio.run(session_crud_routes.destroy_session(_delete_request(manager, FakeBackend()), session_id="s1"))
    assert seen == {"during_kill": None, "at_write": None}
    assert harness.run_pass() is None


def test_a_failed_row_write_keeps_the_mark_until_the_journal_records_the_loss(harness, monkeypatch):
    _quiet_route(monkeypatch)

    async def destroy_session(session_id=None):
        return None

    async def write_failed(socket, name, epoch, host):
        return 0

    monkeypatch.setattr(close_record, "mark_closed_in_datastore", write_failed)
    asyncio.run(session_crud_routes.destroy_session(
        _delete_request(SimpleNamespace(destroy_session=destroy_session), FakeBackend()), session_id="s1"))
    assert harness.run_pass() is None, "the loss is the user's even though no row says so"
    assert not close_intent.touched_since(close_intent.stamp()).instances, "recorded once, then released"


def test_a_kill_that_raises_parks_the_mark_and_the_error_still_reaches_the_caller(harness, monkeypatch):
    _quiet_route(monkeypatch)

    async def destroy_session(session_id=None):
        raise RuntimeError("tmux hung up")

    with pytest.raises(Exception) as caught:
        asyncio.run(session_crud_routes.destroy_session(
            _delete_request(SimpleNamespace(destroy_session=destroy_session), FakeBackend()), session_id="s1"))
    assert "session_destroy_failed" in str(caught.value.detail) or caught.value.status_code == 500
    assert harness.run_pass() is None


def test_the_external_delete_route_marks_and_writes_closed_by_user(harness, monkeypatch):
    _quiet_route(monkeypatch)
    calls = {}

    async def epoch(name, socket):
        calls["epoch"] = (name, socket)
        return 11

    async def destroy_external_session(name):
        calls["during_kill"] = harness.run_pass()
        return {"name": name, "killed": True, "already_gone": False}

    async def row_written(socket, name, epoch_, host):
        calls["write"] = (socket, name, epoch_)
        return 1

    monkeypatch.setattr(close_record, "read_external_epoch", epoch)
    monkeypatch.setattr(close_record, "mark_closed_in_datastore", row_written)
    manager = SimpleNamespace(destroy_external_session=destroy_external_session, tmux_socket_name=lambda: "cloude")
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(session_manager=manager)))
    out = asyncio.run(session_attach_routes.destroy_external_session(request, "cloude_a"))
    assert "destroyed" in out.message
    assert calls == {"epoch": ("cloude_a", "cloude"), "during_kill": None, "write": ("cloude", "cloude_a", 11)}
    assert harness.run_pass() is None


def test_worktree_cleanup_stop_marks_and_writes_closed_by_user(harness, monkeypatch, tmp_path):
    seen = {}

    async def destroy_session(session_id=None):
        seen["during_kill"] = harness.run_pass()

    async def row_written(socket, name, epoch, host):
        seen["write"] = (socket, name, epoch)
        return 1

    async def apply(store, paths, fingerprint, *, stop, archive, delete_unmerged, remove_dirty):
        await stop("/wt/one")
        return {"removed": paths}

    monkeypatch.setattr(close_record, "mark_closed_in_datastore", row_written)
    monkeypatch.setattr(worktree_routes.cleanup, "apply", apply)
    monkeypatch.setattr(worktree_routes, "default_store", lambda: object())
    session = SimpleNamespace(working_dir="/wt/one")
    manager = SimpleNamespace(_registry=SimpleNamespace(sessions={"s1": session}, backends={"s1": FakeBackend()}),
                              is_session_live=lambda sid: True, destroy_session=destroy_session)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(session_manager=manager)))
    body = worktree_routes.CleanupRequest(paths=["/wt/one"], apply=True, fingerprint="f")
    out = asyncio.run(worktree_routes.cleanup_worktrees(body, request, _user={}))
    assert out == {"removed": ["/wt/one"]}
    assert seen == {"during_kill": None, "write": ("cloude", "cloude_a", 11)}


def test_the_swarm_minted_body_close_is_marked_and_recorded(harness, monkeypatch):
    from src.core import session_sleep
    from src.core.swarm import body

    seen = {}

    async def close_for_sleep(manager, *, name, socket):
        seen["during_kill"] = harness.run_pass()

    async def row_written(socket, name, epoch, host):
        seen["write"] = (socket, name, epoch)
        return 1

    monkeypatch.setattr(session_sleep, "close_for_sleep", close_for_sleep)
    monkeypatch.setattr(close_record, "mark_closed_in_datastore", row_written)
    info = SimpleNamespace(tmux_session="cloude_a", session=SimpleNamespace(tmux_created_epoch=11))
    app_state = SimpleNamespace(session_manager=SimpleNamespace(tmux_socket_name=lambda: "cloude"))
    asyncio.run(body._kill_minted(app_state, info))
    assert seen == {"during_kill": None, "write": ("cloude", "cloude_a", 11)}
