
from __future__ import annotations

import sys
import uuid
from contextlib import closing

import pytest

from tests.lifecycle_helpers import ROOT, conn  # noqa: F401

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402

from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.db_models import (
    SESSION_FAMILY_SOURCE_LAUNCHED,
    SESSION_FAMILY_SOURCE_NOT_LAUNCHED,
)
from src.core.session_create_persist import persist_creation
from src.core.session_family_backfill import (
    BACKFILL_CONFIG_UNREADABLE,
    BACKFILL_RAN,
    backfill_launched_families,
    configured_wrappers,
    run_backfill,
)
from src.core.session_store import identity_for_instance, identity_for_live_name
from src.core.tmux_listing import TmuxListing

SOCKET = "cloude"

CODEX_WRAPPERS = [
    {"id": "codex-yolo", "family": "codex", "label": "codex (yolo)"},
    {"id": "claude", "family": "claude", "label": "claude", "default": True},
]


def listing_for(name, epoch=7100, sid="$9"):
    return TmuxListing.answered(
        [
            {
                "name": name,
                "created_at_epoch": epoch,
                "session_id": sid,
                "window_count": 1,
            }
        ]
    )


def row_for(conn, name):
    row = conn.execute(
        "SELECT * FROM sessions WHERE tmux_name = ?", (name,)
    ).fetchone()
    assert row is not None, f"no row for {name}"
    return dict(row)




def test_persist_creation_stores_the_family_it_was_handed(conn):
    result = persist_creation(
        conn,
        socket=SOCKET,
        name="cloude_fam_a",
        listing=listing_for("cloude_fam_a"),
        agent_type="codex-yolo",
        agent_family="codex",
        agent_launched=True,
    )

    assert result.recorded, result.detail
    row = row_for(conn, "cloude_fam_a")
    assert row["agent_family"] == "codex", (
        "the launcher resolved this family to build the command and the "
        "row stored nothing, so the source column asserted a measurement "
        "about a NULL"
    )
    assert row["agent_family_source"] == SESSION_FAMILY_SOURCE_LAUNCHED


def test_a_bare_shell_records_no_family_at_all(conn):
    persist_creation(
        conn,
        socket=SOCKET,
        name="cloude_fam_shell",
        listing=listing_for("cloude_fam_shell"),
        agent_type="claude",
        agent_family="claude",
        agent_launched=False,
    )

    row = row_for(conn, "cloude_fam_shell")
    assert row["agent_family"] is None
    assert row["agent_family_source"] == SESSION_FAMILY_SOURCE_NOT_LAUNCHED


def test_a_launch_that_could_not_name_a_family_stores_null(conn):
    persist_creation(
        conn,
        socket=SOCKET,
        name="cloude_fam_none",
        listing=listing_for("cloude_fam_none"),
        agent_type="something-odd",
        agent_family=None,
        agent_launched=True,
    )

    row = row_for(conn, "cloude_fam_none")
    assert row["agent_family"] is None
    assert row["agent_family_source"] == SESSION_FAMILY_SOURCE_LAUNCHED


def test_the_manager_forwards_the_family_to_the_write_site(monkeypatch, tmp_path):
    from src.core import session_manager as sm

    (tmp_path / "logs").mkdir(exist_ok=True)
    seen = {}

    def _spy(conn, **kwargs):
        seen.update(kwargs)
        from src.core.session_create_persist import CreatePersistResult

        return CreatePersistResult(outcome="recorded", epoch=1)

    monkeypatch.setattr(
        "src.core.session_create_persist.persist_creation", _spy
    )
    mgr = object.__new__(sm.SessionManager)
    monkeypatch.setattr(
        mgr, "_writable_datastore_connection", lambda: _NullConn(), raising=False
    )
    monkeypatch.setattr(
        mgr,
        "_probe_instances",
        lambda: (SOCKET, listing_for("cloude_fam_fwd")),
        raising=False,
    )
    monkeypatch.setattr(
        mgr, "tmux_socket_name", lambda: SOCKET, raising=False
    )
    monkeypatch.setattr("src.core.db.transaction", _null_transaction)

    mgr.persist_creation(
        "cloude_fam_fwd", agent_type="codex-yolo", agent_family="codex",
        agent_launched=True,
    )

    assert seen.get("agent_family") == "codex", (
        f"the manager dropped the family on the way down: {sorted(seen)}"
    )


class _NullConn:

    def close(self):
        return None


class _null_transaction:  # noqa: N801

    def __init__(self, conn):
        self._conn = conn

    def __enter__(self):
        return self._conn

    def __exit__(self, *exc):
        return False




def test_the_identity_readers_carry_the_stored_family(conn):
    persist_creation(
        conn,
        socket=SOCKET,
        name="cloude_fam_read",
        listing=listing_for("cloude_fam_read", epoch=7200),
        agent_type="codex-yolo",
        agent_family="codex",
        agent_launched=True,
    )

    by_name = identity_for_live_name(conn, socket=SOCKET, name="cloude_fam_read")
    assert by_name["agent_family"] == "codex"
    assert by_name["agent_family_source"] == SESSION_FAMILY_SOURCE_LAUNCHED

    by_epoch = identity_for_instance(
        conn, socket=SOCKET, name="cloude_fam_read", epoch=7200
    )
    assert by_epoch["agent_family"] == "codex"
    assert by_epoch["agent_family_source"] == SESSION_FAMILY_SOURCE_LAUNCHED




class _StubSettings:

    def __init__(self, log_dir):
        self._log_dir = log_dir
        self.port = 5001

    def load_auth_config(self):
        raise FileNotFoundError("no config.json in this stub")

    def get_pinned_themes_path(self):
        return self._log_dir / "pinned_themes.json"

    def get_unread_state_path(self):
        return self._log_dir / "unread_state.json"

    @property
    def log_directory(self):
        return str(self._log_dir)

    def get_session_metadata_path(self):
        return self._log_dir / "session_metadata.json"


class _FakeBackend:
    def __init__(self, tmux_session):
        self.tmux_session = tmux_session

    def is_alive(self):
        return True


def _manager_with_row(monkeypatch, tmp_path, *, identity, memory_agent_type):
    from src.core.session_manager import SessionManager
    from src.models import Session, SessionStatus

    (tmp_path / "logs").mkdir(exist_ok=True)
    monkeypatch.setattr(
        "src.core.session_manager.settings", _StubSettings(tmp_path / "logs")
    )
    mgr = SessionManager()
    sess = Session(
        id="ses_fam",
        working_dir=str(tmp_path),
        status=SessionStatus.RUNNING,
        tmux_session="cloude_ses_fam",
        agent_type=memory_agent_type,
    )
    mgr._registry.sessions["ses_fam"] = sess
    mgr._registry.backends["ses_fam"] = _FakeBackend("cloude_ses_fam")
    mgr._registry.subscribers.setdefault("ses_fam", [])
    monkeypatch.setattr(
        mgr,
        "_build_tmux_status_map",
        lambda: {"cloude_ses_fam": {"status": "idle", "pid": 1}},
    )
    monkeypatch.setattr(mgr, "_identity_for_live_name", lambda _n: identity)
    return mgr


def _row_identity(conn, name, epoch):
    persist_creation(
        conn,
        socket=SOCKET,
        name=name,
        listing=listing_for(name, epoch=epoch),
        agent_type="codex-yolo",
        agent_family="codex",
        agent_launched=True,
    )
    return identity_for_live_name(conn, socket=SOCKET, name=name)


@pytest.mark.asyncio
async def test_a_launched_family_survives_the_deletion_of_its_wrapper(
    conn, monkeypatch, tmp_path
):
    identity = _row_identity(conn, "cloude_fam_live", 7300)
    mgr = _manager_with_row(
        monkeypatch, tmp_path, identity=identity, memory_agent_type="codex-yolo"
    )

    info = await mgr.get_session_info(session_id="ses_fam")

    assert info is not None
    assert info.agent_type == "codex-yolo"
    assert info.agent_family == "codex", (
        "the row recorded the family at launch and the listing threw it "
        "away to re-derive one from a wrapper config no longer carries"
    )
    assert info.agent_family_source == SESSION_FAMILY_SOURCE_LAUNCHED


@pytest.mark.asyncio
async def test_the_codex_reader_is_dispatched_for_a_stored_codex_family(
    conn, monkeypatch, tmp_path
):
    from datetime import datetime, timezone
    from src.core import attention_reader as reader_module
    from src.core.attention_reader import AttentionEvidenceReader
    from src.core.attention.watcher import WatchTarget

    identity = _row_identity(conn, "cloude_fam_codex", 7400)
    mgr = _manager_with_row(
        monkeypatch, tmp_path, identity=identity, memory_agent_type="codex-yolo"
    )
    monkeypatch.setattr(mgr, "_identity_for_instance", lambda *args: identity)
    monkeypatch.setattr(reader_module, "read_instance_row", lambda *args, **kw: {})
    from src.core.session_status_map import StatusMap
    mgr._registry.backends["ses_fam"].socket_name = "cloude-test"
    monkeypatch.setattr(mgr, "_build_tmux_status_map", lambda: StatusMap(
        {"cloude_ses_fam": {"status": "running", "pid": 1, "created_at_epoch": 7400}},
        complete=True, socket="cloude-test"))
    monkeypatch.setattr(reader_module, "resolve_primary_uuid", lambda *args, **kw: "thread")
    monkeypatch.setattr(AttentionEvidenceReader, "_process_parents", lambda *args: {})
    monkeypatch.setattr(AttentionEvidenceReader, "_capture", staticmethod(lambda *args: None))
    dispatched = []

    def gather(uuid, **kwargs):
        dispatched.append(uuid)
        return None

    monkeypatch.setattr(reader_module, "gather_codex_evidence", gather)
    reader = AttentionEvidenceReader(mgr, lambda sid: ("cloude_ses_fam", 7400))
    evidence = reader(WatchTarget("ses_fam", "instance"), datetime.now(timezone.utc))
    assert evidence.agent_family == "codex"
    assert dispatched == ["thread"]


@pytest.mark.asyncio
async def test_a_row_describing_a_previous_launch_does_not_speak_for_this_one(
    conn, monkeypatch, tmp_path
):
    identity = _row_identity(conn, "cloude_fam_stale", 7500)
    mgr = _manager_with_row(
        monkeypatch,
        tmp_path,
        identity=identity,
        memory_agent_type="claude",
    )

    info = await mgr.get_session_info(session_id="ses_fam")

    assert info.agent_type == "claude"
    assert info.agent_family == "claude", (
        "the row's codex family spoke for a launch it does not describe"
    )
    assert info.agent_family_source != SESSION_FAMILY_SOURCE_LAUNCHED




def _launched_row(conn, name, epoch, agent_type):
    persist_creation(
        conn,
        socket=SOCKET,
        name=name,
        listing=listing_for(name, epoch=epoch),
        agent_type=agent_type,
        agent_family=None,
        agent_launched=True,
    )


def test_the_backfill_resolves_what_it_can_and_leaves_the_rest_null(conn):
    _launched_row(conn, "cloude_bf_wrapper", 7600, "codex-yolo")
    _launched_row(conn, "cloude_bf_reserved", 7601, "claude")
    _launched_row(conn, "cloude_bf_orphan", 7602, "deleted-wrapper")

    result = backfill_launched_families(
        conn, wrappers=[{"id": "claude", "family": "claude", "default": True}]
    )

    assert result.outcome == BACKFILL_RAN
    assert result.resolved == 1
    assert result.left_null == 2
    assert row_for(conn, "cloude_bf_reserved")["agent_family"] == "claude"
    assert row_for(conn, "cloude_bf_wrapper")["agent_family"] is None
    assert row_for(conn, "cloude_bf_orphan")["agent_family"] is None


def test_the_backfill_resolves_a_wrapper_config_still_carries(conn):
    _launched_row(conn, "cloude_bf_live", 7610, "codex-yolo")

    result = backfill_launched_families(conn, wrappers=CODEX_WRAPPERS)

    assert result.resolved == 1
    assert row_for(conn, "cloude_bf_live")["agent_family"] == "codex"


def test_running_the_backfill_twice_changes_nothing(conn):
    _launched_row(conn, "cloude_bf_twice", 7620, "codex-yolo")

    first = backfill_launched_families(conn, wrappers=CODEX_WRAPPERS)
    second = backfill_launched_families(conn, wrappers=CODEX_WRAPPERS)

    assert first.resolved == 1
    assert second.resolved == 0
    assert second.left_null == 0
    assert row_for(conn, "cloude_bf_twice")["agent_family"] == "codex"


def test_the_backfill_never_touches_a_row_that_already_has_a_family(conn):
    persist_creation(
        conn,
        socket=SOCKET,
        name="cloude_bf_kept",
        listing=listing_for("cloude_bf_kept", epoch=7630),
        agent_type="codex-yolo",
        agent_family="codex",
        agent_launched=True,
    )

    backfill_launched_families(
        conn, wrappers=[{"id": "codex-yolo", "family": "claude"}]
    )

    assert row_for(conn, "cloude_bf_kept")["agent_family"] == "codex"


def test_the_backfill_leaves_an_adopted_row_alone(conn):
    _launched_row(conn, "cloude_bf_guess", 7640, "claude")
    conn.execute(
        "UPDATE sessions SET agent_family_source = 'fingerprint' "
        "WHERE tmux_name = 'cloude_bf_guess'"
    )

    result = backfill_launched_families(conn, wrappers=CODEX_WRAPPERS)

    assert result.resolved == 0
    assert row_for(conn, "cloude_bf_guess")["agent_family"] is None


def test_a_config_that_could_not_be_read_writes_nothing(conn):
    _launched_row(conn, "cloude_bf_noconf", 7650, "claude")

    result = backfill_launched_families(conn, wrappers=None)

    assert result.outcome == BACKFILL_CONFIG_UNREADABLE
    assert result.resolved == 0
    assert row_for(conn, "cloude_bf_noconf")["agent_family"] is None


def test_an_unreadable_config_file_reads_as_could_not_determine(tmp_path):
    missing = tmp_path / "nope.json"
    assert configured_wrappers(missing) is None

    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert configured_wrappers(broken) is None

    empty = tmp_path / "empty.json"
    empty.write_text("{}", encoding="utf-8")
    assert configured_wrappers(empty) == [], (
        "a file that was read and configures no wrappers is a different "
        "answer from a file that could not be read"
    )


def test_the_backfill_is_registered_as_a_migration_step(tmp_path, monkeypatch):
    from src.core.db import set_meta
    from src.core.db_models import META_SCHEMA_VERSION
    from src.config import settings

    backfill_from = 28

    config = tmp_path / "config.json"
    config.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(settings, "auth_config_file", str(config))

    ensure_db_migrated(tmp_path, 4, "0.8.2")
    with closing(connect(db_path_for(tmp_path))) as handle:
        _launched_row(handle, "cloude_bf_step", 7660, "claude")
        set_meta(handle, META_SCHEMA_VERSION, str(backfill_from))
        handle.commit()

    ensure_db_migrated(tmp_path, 4, "0.8.2")

    with closing(connect(db_path_for(tmp_path))) as handle:
        assert row_for(handle, "cloude_bf_step")["agent_family"] == "claude"


def test_the_step_is_a_no_op_on_a_database_with_nothing_to_repair(tmp_path):
    ensure_db_migrated(tmp_path, 4, "0.8.2")
    with closing(connect(db_path_for(tmp_path))) as handle:
        result = run_backfill(handle, config_path=tmp_path / "absent.json")

    assert result.outcome == BACKFILL_RAN
    assert result.resolved == 0




@pytest.mark.asyncio
async def test_create_session_records_the_family_it_launched(
    tmp_path, monkeypatch, tmux_test_socket
):
    from src.config import settings
    from src.core.session_manager import SessionManager

    log_dir = tmp_path / "logs"
    state_dir = tmp_path / "state"
    work = tmp_path / "wd"
    for d in (log_dir, state_dir, work):
        d.mkdir()
    monkeypatch.setattr(settings, "log_directory", str(log_dir))
    monkeypatch.setattr(settings, "state_dir_override", str(state_dir))
    monkeypatch.setattr(
        type(settings), "get_agent_command", lambda self, *a, **k: "sleep 45"
    )
    monkeypatch.setattr(
        "src.core.sessions.wrapper_source.configured_wrappers", lambda **_kw: []
    )
    ensure_db_migrated(state_dir, 4, "0.8.2")

    token = uuid.uuid4().hex[:8]
    mgr = SessionManager()
    session = None
    try:
        session = await mgr.create_session(
            session_id=f"ses_{token}",
            working_dir=str(work),
            auto_start_claude=True,
            agent_type="codex",
            project_name=f"fam{token}",
        )
        with closing(connect(db_path_for(state_dir))) as handle:
            row = handle.execute(
                "SELECT agent_type, agent_family, agent_family_source "
                "FROM sessions WHERE tmux_name = ?",
                (session.tmux_session,),
            ).fetchone()
        assert row is not None, "the create path recorded no row"
        assert row["agent_type"] == "codex"
        assert row["agent_family_source"] == SESSION_FAMILY_SOURCE_LAUNCHED
        assert row["agent_family"] == "codex", (
            "the launcher resolved this family to build the command and "
            "then dropped it, leaving the row's source column asserting "
            "a measurement nobody stored"
        )
    finally:
        if session is not None:
            await mgr.destroy_session(session.id)
