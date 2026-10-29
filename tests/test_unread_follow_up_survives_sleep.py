
from __future__ import annotations

import os
import sys
import tempfile
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_fu_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_fu_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

pytest.importorskip("fastapi")

# ruff: noqa: E402
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import recreate_routes, session_sleep_routes
from src.api.auth import require_auth
from src.api.session_record_payload import _session_record_payload
from src.core import session_sleep, session_store
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.session_manager import SessionManager
from src.core.session_recreate_presence import TMUX_GONE, TMUX_PRESENT, TmuxPresence
from src.core.session_restart import rebind_instance
from src.core.session_view_clears import clear_view_state
from src.core.unread_store import UnreadStore
from src.models import Session, SessionStatus

NAME = "carnivore_followup"
ROW_UUID = "row-uuid-followup"
CONV_UUID = "11111111-2222-3333-4444-777777777777"
SESSION_ID = "ses_followup"
EPOCH_BEFORE = 1790090835
EPOCH_AFTER = 1790099999




@pytest.fixture()
def store(tmp_path: Path) -> UnreadStore:
    return UnreadStore(tmp_path / "unread_state.json")


def test_the_old_instance_key_loses_the_flag_across_a_wake(store):
    store.set_flag(NAME, "manual", True, epoch=EPOCH_BEFORE)
    assert store.is_unread(NAME, EPOCH_BEFORE)
    store.prune(set())
    assert not store.is_unread(NAME, EPOCH_AFTER, row_id=4)


def test_a_row_keyed_follow_up_survives_the_boot_prune_and_a_new_epoch(store, tmp_path):
    store.set_follow_up(4, NAME, EPOCH_BEFORE)
    store.prune(set())
    reloaded = UnreadStore(tmp_path / "unread_state.json")
    assert reloaded.is_unread(NAME, EPOCH_AFTER, row_id=4)
    assert reloaded.is_followed_up(4)
    assert not reloaded.is_unread(NAME, EPOCH_AFTER, row_id=5)
    assert not reloaded.is_unread(NAME, EPOCH_AFTER)


def test_setting_on_the_row_retires_the_instance_manual_half_only(store):
    store.set_flag(NAME, "auto", True, epoch=EPOCH_BEFORE)
    store.set_flag(NAME, "manual", True, epoch=EPOCH_BEFORE)
    store.set_follow_up(4, NAME, EPOCH_BEFORE)
    inst = store.raw[UnreadStore.compose_key(NAME, EPOCH_BEFORE)]
    assert inst == {"auto": True, "manual": False}, "the auto half never moves"
    assert store.raw["row:4"] == {"auto": False, "manual": True}


def test_adopting_moves_a_legacy_manual_flag_and_leaves_auto_on_the_pane(store):
    store.set_flag(NAME, "manual", True, epoch=EPOCH_BEFORE)
    assert store.adopt_follow_up(4, NAME, EPOCH_BEFORE) is True
    assert store.raw == {"row:4": {"auto": False, "manual": True}}
    assert store.adopt_follow_up(4, NAME, EPOCH_BEFORE) is False
    store.set_flag("other", "auto", True, epoch=1)
    assert store.adopt_follow_up(9, "other", 1) is False
    assert "row:9" not in store.raw


def test_clear_with_the_row_drops_the_row_key(store):
    store.set_follow_up(4, NAME, EPOCH_BEFORE)
    store.clear(NAME, EPOCH_AFTER)
    assert store.is_followed_up(4)
    store.clear(NAME, EPOCH_AFTER, row_id=4)
    assert not store.is_followed_up(4)
    assert store.raw == {}


def test_no_tmux_name_can_collide_with_a_row_key():
    assert UnreadStore.row_key(7) == "row:7"
    assert UnreadStore.row_key(None) is None
    assert UnreadStore.row_key(True) is None
    assert UnreadStore.is_row_key("row:7")
    assert not UnreadStore.is_row_key(UnreadStore.compose_key("rowx", 7))




class _StubSettings:

    def __init__(self, root: Path):
        self._root = root
        self.port = 5001

    def get_pinned_themes_path(self) -> Path:
        return self._root / "pinned_themes.json"

    def get_unread_state_path(self) -> Path:
        return self._root / "unread_state.json"

    @property
    def log_directory(self) -> str:
        return str(self._root / "logs")

    def get_session_metadata_path(self) -> Path:
        return self._root / "logs" / "session_metadata.json"


class _FakeBackend:
    def __init__(self, tmux_session: str):
        self.tmux_session = tmux_session

    def is_alive(self) -> bool:
        return True


@pytest.fixture()
def state_dir(tmp_path, monkeypatch):
    from src.config import settings

    sd = tmp_path / "state"
    sd.mkdir()
    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: sd, raising=True)
    assert ensure_db_migrated(sd).status == "ok"
    row_id = _insert(sd, ROW_UUID, NAME, EPOCH_BEFORE)
    return sd, row_id


def _insert(sd: Path, uuid: str, name: str, epoch: int, conv: str = CONV_UUID) -> int:
    with closing(connect(db_path_for(sd), create=False)) as conn:
        cur = conn.execute(
            "INSERT INTO sessions (session_uuid, tmux_socket, tmux_name, "
            "tmux_created_epoch, working_dir, claude_session_uuid, title, "
            "origin, lifecycle, lifecycle_source, agent_type, created_at, "
            "updated_at) VALUES (?, 'cloude', ?, ?, '/Users/x/proj', ?, "
            "'follow me up', 'created', 'running', 'tmux_list', 'claude', "
            "'2026-09-01T00:00:00Z', '2026-09-01T00:00:00Z')",
            (uuid, name, epoch, conv),
        )
        conn.commit()
        return int(cur.lastrowid)


def _row(sd: Path, uuid: str = ROW_UUID) -> dict:
    with closing(connect(db_path_for(sd), create=False)) as conn:
        return dict(conn.execute(
            "SELECT * FROM sessions WHERE session_uuid = ?", (uuid,)
        ).fetchone())


def _manager(monkeypatch, tmp_path: Path, sd: Path, epoch: int) -> SessionManager:
    (tmp_path / "logs").mkdir(exist_ok=True)
    monkeypatch.setattr("src.core.session_manager.settings", _StubSettings(tmp_path))
    mgr = SessionManager()
    mgr._registry.sessions[SESSION_ID] = Session(
        id=SESSION_ID, pty_pid=None, working_dir=str(tmp_path),
        status=SessionStatus.RUNNING, tmux_session=NAME,
    )
    mgr._registry.backends[SESSION_ID] = _FakeBackend(NAME)
    mgr._registry.subscribers.setdefault(SESSION_ID, [])
    monkeypatch.setattr(mgr, "_build_tmux_status_map",
                        lambda: {NAME: {"status": "idle", "created_at_epoch": epoch}})
    monkeypatch.setattr(mgr, "list_attachable_sessions",
                        lambda: [{"name": NAME, "created_at_epoch": epoch}])

    def _exact(name, ep):
        with closing(connect(db_path_for(sd), create=False)) as conn:
            return session_store.identity_for_instance(conn, socket="cloude", name=name, epoch=ep)

    def _live(name):
        with closing(connect(db_path_for(sd), create=False)) as conn:
            return session_store.identity_for_live_name(conn, socket="cloude", name=name)

    monkeypatch.setattr(mgr, "_identity_for_instance", _exact)
    monkeypatch.setattr(mgr, "_identity_for_live_name", _live)
    return mgr


async def _listed_unread(mgr: SessionManager) -> bool:
    infos = await mgr.list_session_infos()
    assert len(infos) == 1, f"expected one row, got {len(infos)}"
    return bool(infos[0].unread)


class _LocalServers:
    async def clear_session(self, name):
        return None


def _asleep_client(mgr: SessionManager) -> TestClient:
    from src.api import session_records_routes

    app = FastAPI()
    app.include_router(session_sleep_routes.router, prefix="/api/v1")
    app.include_router(session_records_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    app.state.session_manager = mgr
    return TestClient(app)


async def _sleep(mgr: SessionManager, monkeypatch) -> None:
    async def _close(manager, *, name, socket):
        return {"closed_registrations": 1, "direct_kill_rc": None}

    outcomes = [TMUX_PRESENT, TMUX_GONE]
    monkeypatch.setattr(session_sleep, "close_for_sleep", _close, raising=True)
    monkeypatch.setattr(recreate_routes, "_socket_name", lambda: "cloude", raising=True)
    monkeypatch.setattr(
        recreate_routes, "_measure_presence",
        lambda name, socket: TmuxPresence(outcome=outcomes.pop(0) if len(outcomes) > 1 else outcomes[0],
                                          detail="test"),
        raising=True,
    )
    app_state = SimpleNamespace(session_manager=mgr, local_servers=_LocalServers())
    result = await session_sleep_routes.sleep_by_uuid(app_state, ROW_UUID)
    assert result.status == "asleep", result


def _wake(sd: Path, row_id: int) -> None:
    with closing(connect(db_path_for(sd), create=False)) as conn:
        assert rebind_instance(conn, row_id=row_id, socket="cloude", name=NAME,
                               epoch=EPOCH_AFTER, lifecycle_source="tmux_list").rebound
        conn.commit()


@pytest.mark.asyncio
async def test_a_marked_session_stays_flagged_through_sleep_restart_and_wake(
    monkeypatch, tmp_path, state_dir,
):
    sd, row_id = state_dir
    mgr = _manager(monkeypatch, tmp_path, sd, EPOCH_BEFORE)
    mgr.set_manual_unread(NAME, True)
    assert await _listed_unread(mgr)
    assert mgr._unread_store.is_followed_up(row_id), "the mark lands on the row"

    await _sleep(mgr, monkeypatch)
    assert session_sleep.is_asleep(_row(sd))
    asleep = _asleep_client(mgr).get("/api/v1/sessions/asleep").json()
    assert [(a["session_uuid"], a["unread"]) for a in asleep] == [(ROW_UUID, True)]
    records = _asleep_client(mgr).get("/api/v1/sessions/records").json()
    assert [x["unread"] for x in records if x["session_uuid"] == ROW_UUID] == [True]

    mgr2 = _manager(monkeypatch, tmp_path, sd, EPOCH_AFTER)
    mgr2._unread_store.prune(set())

    _wake(sd, row_id)
    assert await _listed_unread(mgr2), "the reminder survives the wake"


@pytest.mark.asyncio
async def test_a_view_after_the_wake_clears_the_row_flag(monkeypatch, tmp_path, state_dir):
    sd, row_id = state_dir
    mgr = _manager(monkeypatch, tmp_path, sd, EPOCH_BEFORE)
    mgr.set_manual_unread(NAME, True)
    await _sleep(mgr, monkeypatch)
    _wake(sd, row_id)
    mgr2 = _manager(monkeypatch, tmp_path, sd, EPOCH_AFTER)
    assert await _listed_unread(mgr2)
    assert clear_view_state(mgr2, tmux_name=NAME) is True
    assert not await _listed_unread(mgr2)
    assert mgr2._unread_store.raw == {}


@pytest.mark.asyncio
async def test_a_legacy_instance_flag_is_carried_into_the_sleep(monkeypatch, tmp_path, state_dir):
    sd, row_id = state_dir
    mgr = _manager(monkeypatch, tmp_path, sd, EPOCH_BEFORE)
    mgr._unread_store.set_flag(NAME, "manual", True, epoch=EPOCH_BEFORE)
    await _sleep(mgr, monkeypatch)
    assert mgr._unread_store.is_followed_up(row_id)
    _wake(sd, row_id)
    mgr2 = _manager(monkeypatch, tmp_path, sd, EPOCH_AFTER)
    mgr2._unread_store.prune(set())
    assert await _listed_unread(mgr2)


@pytest.mark.asyncio
async def test_the_automatic_flag_is_carried_onto_the_row_by_the_sleep(
    monkeypatch, tmp_path, state_dir
):
    sd, row_id = state_dir
    mgr = _manager(monkeypatch, tmp_path, sd, EPOCH_BEFORE)
    mgr._unread_store.set_flag(NAME, "auto", True, epoch=mgr._unread_epoch(NAME))
    assert await _listed_unread(mgr)
    assert not mgr._unread_store.is_followed_up(row_id), "auto is not a follow-up while the pane lives"

    await _sleep(mgr, monkeypatch)
    asleep = _asleep_client(mgr).get("/api/v1/sessions/asleep").json()
    assert [a["unread"] for a in asleep] == [True], "the moon keeps the unread mark"
    _wake(sd, row_id)
    mgr2 = _manager(monkeypatch, tmp_path, sd, EPOCH_AFTER)
    assert await _listed_unread(mgr2), "the woken session is still unread"


@pytest.mark.asyncio
async def test_a_new_session_reusing_the_name_does_not_inherit_the_flag(
    monkeypatch, tmp_path, state_dir,
):
    sd, row_id = state_dir
    mgr = _manager(monkeypatch, tmp_path, sd, EPOCH_BEFORE)
    mgr.set_manual_unread(NAME, True)
    with closing(connect(db_path_for(sd), create=False)) as conn:
        conn.execute("UPDATE sessions SET lifecycle='stopped', lifecycle_source="
                     "'closed_by_user' WHERE id = ?", (row_id,))
        conn.commit()
    _insert(sd, "row-uuid-other", NAME, EPOCH_AFTER,
            conv="99999999-2222-3333-4444-777777777777")
    mgr2 = _manager(monkeypatch, tmp_path, sd, EPOCH_AFTER)
    mgr2._unread_store.prune({NAME})
    assert not await _listed_unread(mgr2)


def test_only_an_asleep_record_carries_the_flag(store):
    store.set_follow_up(4, NAME, EPOCH_BEFORE)
    base = {"id": 4, "session_uuid": "u", "origin": "created", "tmux_name": NAME,
            "tmux_created_epoch": EPOCH_BEFORE, "project_attribution": "x",
            "archived_at": None}
    asleep = {**base, "lifecycle": "stopped", "lifecycle_source": "slept_by_user"}
    running = {**base, "lifecycle": "running", "lifecycle_source": "tmux_list"}
    assert _session_record_payload(asleep, store).unread is True
    assert _session_record_payload(running, store).unread is None
    assert _session_record_payload(asleep).unread is None, "no store: not measured"
    assert _session_record_payload({**asleep, "id": 5}, store).unread is False
