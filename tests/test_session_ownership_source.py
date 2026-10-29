
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_own_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_own_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.core.session_manager import SessionManager
from src.models import Session, SessionInfo, SessionStatus


class _StubSettings:

    def __init__(self, log_dir: Path, port: int = 5001) -> None:
        self._log_dir = log_dir
        self.port = port

    def load_auth_config(self):
        raise FileNotFoundError("no config.json in this stub")

    def get_pinned_themes_path(self) -> Path:
        return self._log_dir / "pinned_themes.json"

    def get_unread_state_path(self) -> Path:
        return self._log_dir / "unread_state.json"

    @property
    def log_directory(self) -> str:
        return str(self._log_dir)

    def get_session_metadata_path(self) -> Path:
        return self._log_dir / "session_metadata.json"


class _FakeBackend:

    def __init__(self, tmux_session: str) -> None:
        self.tmux_session = tmux_session

    def is_alive(self) -> bool:
        return True


def _bare_manager(monkeypatch, tmp_path: Path) -> SessionManager:
    (tmp_path / "logs").mkdir(exist_ok=True)
    stub = _StubSettings(log_dir=tmp_path / "logs")
    monkeypatch.setattr("src.core.session_manager.settings", stub)
    return SessionManager()


def _register(
    mgr: SessionManager, sid: str, tmux_name: str, working_dir: Path
) -> Session:
    sess = Session(
        id=sid,
        pty_pid=None,
        working_dir=str(working_dir),
        status=SessionStatus.RUNNING,
        tmux_session=tmux_name,
    )
    mgr._registry.sessions[sid] = sess
    mgr._registry.backends[sid] = _FakeBackend(tmux_name)
    mgr._registry.subscribers.setdefault(sid, [])
    return sess


def _stub_status(monkeypatch, mgr: SessionManager, *names: str) -> None:
    monkeypatch.setattr(
        mgr,
        "_build_tmux_status_map",
        lambda: {n: {"status": "idle", "pid": 4242} for n in names},
    )




@pytest.mark.asyncio
async def test_created_session_is_reported_owned(monkeypatch, tmp_path):
    mgr = _bare_manager(monkeypatch, tmp_path)
    _register(mgr, "ses_abc", "cloude_ses_abc", tmp_path)
    mgr._owned.names.add("cloude_ses_abc")
    _stub_status(monkeypatch, mgr, "cloude_ses_abc")

    info = await mgr.get_session_info(session_id="ses_abc")
    assert info is not None
    assert info.created_by_cloude is True


@pytest.mark.asyncio
async def test_adopted_session_is_reported_external(monkeypatch, tmp_path):
    mgr = _bare_manager(monkeypatch, tmp_path)
    _register(mgr, "adopted:handmade", "handmade", tmp_path)
    _stub_status(monkeypatch, mgr, "handmade")

    info = await mgr.get_session_info(session_id="adopted:handmade")
    assert info is not None
    assert info.created_by_cloude is False




@pytest.mark.asyncio
async def test_owned_session_with_adopted_id_still_reports_owned(
    monkeypatch, tmp_path
):
    mgr = _bare_manager(monkeypatch, tmp_path)
    _register(mgr, "adopted:cloude_ses_ec5bf2a3", "cloude_ses_ec5bf2a3", tmp_path)
    mgr._owned.names.add("cloude_ses_ec5bf2a3")
    _stub_status(monkeypatch, mgr, "cloude_ses_ec5bf2a3")

    info = await mgr.get_session_info(session_id="adopted:cloude_ses_ec5bf2a3")
    assert info is not None
    assert info.created_by_cloude is True, (
        "an `adopted:` id prefix is not evidence of adoption - it is what a "
        "restart-time re-attach mints for a session we still own"
    )


@pytest.mark.asyncio
async def test_external_session_with_plain_id_still_reports_external(
    monkeypatch, tmp_path
):
    mgr = _bare_manager(monkeypatch, tmp_path)
    _register(mgr, "some-plain-id", "not_ours", tmp_path)
    _stub_status(monkeypatch, mgr, "not_ours")

    info = await mgr.get_session_info(session_id="some-plain-id")
    assert info is not None
    assert info.created_by_cloude is False


@pytest.mark.asyncio
async def test_adopting_an_owned_session_does_not_disown_it(monkeypatch, tmp_path):
    mgr = _bare_manager(monkeypatch, tmp_path)
    mgr._owned.names.add("cloude_ses_abc")

    _register(mgr, "adopted:cloude_ses_abc", "cloude_ses_abc", tmp_path)
    _stub_status(monkeypatch, mgr, "cloude_ses_abc")

    info = await mgr.get_session_info(session_id="adopted:cloude_ses_abc")
    assert info.created_by_cloude is True
    assert "cloude_ses_abc" in mgr._owned.names




def test_owned_set_survives_a_restart(monkeypatch, tmp_path):
    mgr = _bare_manager(monkeypatch, tmp_path)
    _register(mgr, "ses_abc", "cloude_ses_abc", tmp_path)
    mgr._owned.names.update({"cloude_ses_abc", "cloude_test pause"})
    mgr._save_session_metadata()

    on_disk = json.loads(
        (tmp_path / "logs" / "session_metadata.json").read_text()
    )
    assert on_disk["owned_tmux_sessions"] == [
        "cloude_ses_abc",
        "cloude_test pause",
    ]

    reborn = _bare_manager(monkeypatch, tmp_path)
    assert reborn._owned.names == {"cloude_ses_abc", "cloude_test pause"}


@pytest.mark.asyncio
async def test_badge_unchanged_across_a_restart(monkeypatch, tmp_path):
    before = _bare_manager(monkeypatch, tmp_path)
    _register(before, "ses_abc", "cloude_ses_abc", tmp_path)
    before._owned.names.add("cloude_ses_abc")
    _stub_status(monkeypatch, before, "cloude_ses_abc")
    before._save_session_metadata()
    pre = await before.get_session_info(session_id="ses_abc")

    after = _bare_manager(monkeypatch, tmp_path)
    _register(after, "adopted:cloude_ses_abc", "cloude_ses_abc", tmp_path)
    _stub_status(monkeypatch, after, "cloude_ses_abc")
    post = await after.get_session_info(session_id="adopted:cloude_ses_abc")

    assert pre.created_by_cloude is True
    assert post.created_by_cloude == pre.created_by_cloude


@pytest.mark.asyncio
async def test_owned_set_is_pruned_when_a_session_dies(monkeypatch, tmp_path):
    mgr = _bare_manager(monkeypatch, tmp_path)
    _register(mgr, "ses_alive", "cloude_alive", tmp_path)
    mgr._owned.names.update({"cloude_alive", "cloude_dead"})
    mgr._save_session_metadata()

    reborn = _bare_manager(monkeypatch, tmp_path)
    assert reborn._owned.names == {"cloude_alive", "cloude_dead"}

    class _Probe:
        tmux_session = "cloude_alive"

        def discover_existing(self):
            return ["cloude_alive"]

        async def attach_existing(self):
            return None

    monkeypatch.setattr(
        "src.core.session_manager.build_backend",
        lambda *a, **k: _Probe(),
    )
    monkeypatch.setattr(reborn, "_sweep_orphan_uploads", _noop_async)
    await reborn.lifespan_startup()

    assert reborn._owned.names == {"cloude_alive"}


async def _noop_async(*_args, **_kwargs) -> None:
    return None




def test_session_info_defaults_to_not_owned(tmp_path):
    info = SessionInfo(
        session=Session(id="pinned:x", working_dir=str(tmp_path)),
    )
    assert info.created_by_cloude is False
