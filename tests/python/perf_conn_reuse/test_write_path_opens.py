
from __future__ import annotations

import asyncio
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path
from typing import Callable, Iterator

import pytest

import src.config  # noqa: F401
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.db_models import SESSION_LIFECYCLE_RUNNING, SESSION_LIFECYCLE_STOPPED
from src.core.db_reuse.change_cache import HOT_READS
from src.core.tmux_listing import TmuxListing
from tests.lifecycle_helpers import add_row, row_by_uuid
from tests.python.perf_conn_reuse.helpers import count_connects, opens_of
from tests.test_session_lifecycle_wiring import _wired

N = 12




def _reconcile_manager(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, listing: TmuxListing) -> object:
    ensure_db_migrated(tmp_path, 4, "0.8.2")
    with closing(connect(db_path_for(tmp_path))) as c:
        add_row(c, uuid="u-live", name="cloude_a", epoch=1000)
        c.commit()
    return _wired(monkeypatch, tmp_path, listing)


def test_an_idle_lifecycle_sweep_opens_no_connection(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    listing = TmuxListing.answered([{"name": "cloude_a", "created_at_epoch": 1000, "window_count": 1}])
    mgr = _reconcile_manager(monkeypatch, tmp_path, listing)
    mgr.list_attachable_sessions()
    opened = count_connects(monkeypatch)
    for _ in range(N):
        outcome = mgr.reconcile_lifecycle(listing)
        assert outcome.evaluated and outcome.examined == 1 and not outcome.stopped_uuids
    assert opens_of(opened, "carnivore.db") == 0


def test_a_dead_row_is_still_reaped_on_the_threads_shared_connection(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    ensure_db_migrated(tmp_path, 4, "0.8.2")
    with closing(connect(db_path_for(tmp_path))) as c:
        add_row(c, uuid="u-dead", name="cloude_gone", epoch=900)
        add_row(c, uuid="u-live", name="cloude_a", epoch=1000)
        c.commit()
    listing = TmuxListing.answered([{"name": "cloude_a", "created_at_epoch": 1000, "window_count": 1}])
    mgr = _wired(monkeypatch, tmp_path, listing)
    mgr.list_attachable_sessions()
    with closing(connect(db_path_for(tmp_path))) as c:
        add_row(c, uuid="u-dead2", name="cloude_gone2", epoch=901)
        c.commit()
    opened = count_connects(monkeypatch)
    outcome = mgr.reconcile_lifecycle(listing)
    assert outcome.stopped_uuids == ("u-dead2",)
    assert opens_of(opened, "carnivore.db") == 0
    with closing(connect(db_path_for(tmp_path), create=False)) as c:
        assert row_by_uuid(c, "u-dead2")["lifecycle"] == SESSION_LIFECYCLE_STOPPED
        assert row_by_uuid(c, "u-live")["lifecycle"] == SESSION_LIFECYCLE_RUNNING


def test_a_failed_probe_still_opens_nothing_and_changes_nothing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from src.core.tmux_listing import REASON_TIMEOUT

    mgr = _reconcile_manager(monkeypatch, tmp_path, TmuxListing.unavailable(REASON_TIMEOUT))
    mgr.list_attachable_sessions()
    opened = count_connects(monkeypatch)
    assert mgr.reconcile_lifecycle(TmuxListing.unavailable(REASON_TIMEOUT)).evaluated is False
    assert opens_of(opened, "carnivore.db") == 0




def test_lazy_handle_reads_do_not_open_a_writer_and_a_transaction_reads_its_own_writes(tmp_path: Path) -> None:
    from src.core.db import transaction
    from src.core.sessions.lazy_write import DatastoreNotWritable, LazyWriteConnection

    path = tmp_path / "x.db"
    seed = connect(path)
    seed.execute("CREATE TABLE t (v TEXT)")
    reader, opens = connect(path), []

    def open_writer() -> sqlite3.Connection:
        opens.append(1)
        return connect(path)

    lazy = LazyWriteConnection(reader, open_writer)
    assert lazy.execute("  select count(*) from t").fetchone()[0] == 0
    assert lazy.execute("PRAGMA user_version").fetchone()[0] == 0
    assert not opens and not lazy.writer_opened
    for read_form in ("PRAGMA main.schema_version", 'PRAGMA "main".data_version', "PRAGMA table_info(t)", "PRAGMA database_list"):
        lazy.execute(read_form)
    assert not opens
    for setter in ("PRAGMA user_version = 7", "PRAGMA busy_timeout(0)", "PRAGMA foreign_keys(OFF)", "PRAGMA busy_timeout = 1000"):
        lazy.execute(setter)
        assert opens == [1]
        lazy.close()
        opens.clear()
        lazy = LazyWriteConnection(reader, open_writer)
    lazy = LazyWriteConnection(reader, open_writer)
    lazy.execute("WITH x AS (SELECT 1) INSERT INTO t SELECT 'cte' FROM x")
    assert opens == [1]
    lazy.close()
    opens.clear()
    lazy = LazyWriteConnection(reader, open_writer)
    with transaction(lazy):
        lazy.execute("INSERT INTO t VALUES ('a')")
        assert lazy.execute("SELECT count(*) FROM t").fetchone()[0] == 2
    assert opens == [1]
    assert reader.execute("SELECT count(*) FROM t").fetchone()[0] == 2
    lazy.close()
    assert not lazy.writer_opened
    with LazyWriteConnection(reader, open_writer) as ctx:
        ctx.executemany("INSERT INTO t VALUES (?)", [("m1",), ("m2",)])
        ctx.cursor().execute("INSERT INTO t VALUES ('c')")
    assert reader.execute("SELECT count(*) FROM t").fetchone()[0] == 5
    ctx.rollback()
    ctx.executescript("INSERT INTO t VALUES ('s');")
    ctx.close()
    with pytest.raises(DatastoreNotWritable):
        LazyWriteConnection(reader, lambda: None).execute("UPDATE t SET v='b'")




from tests.test_claude_title_sync_apply import (  # noqa: E402,F401
    SYNC_RAN, TITLE_APPLIED, _FakeManager, _isolated_claude_registry, _read, _row, db, sync_claude_title, transcript,
)


def test_an_idle_title_sync_opens_no_writer(db: object, transcript: Callable[..., str]) -> None:
    _row(db, title="Same Name", claude_title="Same Name")
    transcript("Same Name")
    manager = _FakeManager(db)
    for _ in range(N):
        assert sync_claude_title(manager, "ses_test").outcome == SYNC_RAN
    assert manager.connections_opened == 0


def test_a_renamed_title_still_writes_through_one_writer(db: object, transcript: Callable[..., str]) -> None:
    row_id = _row(db, title="Old Name", claude_title="Old Name")
    transcript("New Name")
    manager = _FakeManager(db)
    result = sync_claude_title(manager, "ses_test")
    assert result.action == TITLE_APPLIED and result.broadcast_title == "New Name"
    assert manager.connections_opened == 1
    assert _read(db, row_id) == ("New Name", "New Name")




@pytest.fixture
def bus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    d = tmp_path / "state"
    d.mkdir()
    assert ensure_db_migrated(d, 4, "0.0.0").status == "ok"
    from src.config import settings

    monkeypatch.setattr(settings, "state_dir_override", str(d))
    from src.core.crosstalk import store
    from src.core.db_reuse.core_read import lend_pooled_or_raise

    monkeypatch.setattr(store, "_conn", lambda: lend_pooled_or_raise(db_path_for(settings.get_state_dir())))
    HOT_READS.clear()
    yield d
    HOT_READS.clear()


def _queue(state: Path, receiver_key: str, *, expires_in: float = 3600.0, status: str = "queued") -> str:
    mid = f"m-{receiver_key}-{time.time_ns()}"
    now = time.time()
    with closing(connect(db_path_for(state))) as conn:
        conn.execute(
            "INSERT INTO crosstalk_messages (id,source,thread,sender_key,receiver_key,sender_id,receiver_id,sender_name,"
            "sender_provider,text,status,created_at,expires_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (mid, "crosstalk", "t", "s", receiver_key, "s", "r", "n", "p", "hi", status, now, now + expires_in),
        )
    return mid


def test_idle_claim_and_expiry_timer_open_nothing(bus: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from src.core.crosstalk import store

    assert store.claim_for("agent-a") is None and store.next_expiry() is None
    opened = count_connects(monkeypatch)
    for _ in range(N):
        assert store.claim_for("agent-a") is None
        assert store.next_expiry() is None
    assert opens_of(opened, "carnivore.db") == 0


def test_a_message_queued_after_an_idle_claim_is_claimed_next_call(bus: Path) -> None:
    from src.core.crosstalk import store

    assert store.claim_for("agent-a") is None
    mid = _queue(bus, "agent-a")
    claimed = store.claim_for("agent-a")
    assert claimed is not None and claimed["id"] == mid
    row = store.claim_for("agent-a")
    assert row is None
    assert store.next_expiry() is None


def test_claim_for_another_receiver_leaves_a_waiting_message_alone_and_the_deadline_follows_commits(bus: Path) -> None:
    from src.core.crosstalk import store

    assert store.next_expiry() is None
    mid = _queue(bus, "agent-b", expires_in=100)
    assert store.claim_for("agent-a") is None
    deadline = store.next_expiry()
    assert deadline is not None and deadline == pytest.approx(time.time() + 100, abs=5)
    claimed = store.claim_for("agent-b")
    assert claimed["id"] == mid
    assert store.next_expiry() is None
