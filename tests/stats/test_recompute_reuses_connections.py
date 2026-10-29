from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any, List

import pytest

from src.core.stats import answers, config, pack_scope, queries
from src.core.stats.batch_store import BatchStore
from src.core.stats.plugin import usage_revision
from tests.stats.test_batch_live import _client, _item, _row


@pytest.fixture
def opens(monkeypatch) -> List[str]:
    seen: List[str] = []
    real = sqlite3.connect

    def counting(target: Any, *args: Any, **kwargs: Any) -> sqlite3.Connection:
        if "mode=ro" in str(target):
            seen.append(str(target))
        return real(target, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", counting)
    return seen


def _bump_revision(store) -> None:
    with store.connect() as db:
        db.execute("UPDATE stats_meta SET value=CAST(value AS INTEGER)+1 WHERE key='revision'")
        usage_revision.bump(db)


def _total(got: dict) -> float:
    return got["results"][0]["result"]["summary"]["value"]


def test_recompute_cycles_open_no_new_read_connection(tmp_path, monkeypatch, opens):
    _client_, store = _client(tmp_path)
    monkeypatch.setattr(answers._Ledger, "state", lambda _self: answers.STATE_OK)
    answers._registry.clear()
    _row(store, int(time.time()) // 60 * 60, "c1")
    items = [_item(3600), {**_item(3600), "group_by": "model"}, _item(7200)]
    queries.execute_batch(store, items)
    answers.wait_idle()
    for _ in range(2):
        _bump_revision(store)
        queries.execute_batch(store, items)
        answers.wait_idle()
    opens.clear()
    for _ in range(8):
        _bump_revision(store)
        queries.execute_batch(store, items)
        answers.wait_idle()
    assert opens == []


def test_settings_and_annotation_reads_open_once(tmp_path, opens):
    _client_, store = _client(tmp_path)
    opens.clear()
    for _ in range(20):
        config.get_settings(store)
        config.list_annotations(store, start=0, end=2_000_000_000)
    assert len(opens) <= 1


def test_new_usage_changes_the_answer_through_the_reused_connection(tmp_path, monkeypatch):
    _client_, store = _client(tmp_path)
    monkeypatch.setattr(answers._Ledger, "state", lambda _self: answers.STATE_OK)
    answers._registry.clear()
    now = int(time.time()) // 60 * 60
    _row(store, now, "c1", inp=100, out=50)
    items = [_item(3600)]
    first = _total(queries.execute_batch(store, items))
    answers.wait_idle()
    _row(store, now - 60, "c2", inp=1000, out=0)
    _bump_revision(store)
    stale = queries.execute_batch(store, items)
    assert stale["results"][0]["answer"]["stale"] is True
    answers.wait_idle()
    fresh = queries.execute_batch(store, items)
    assert fresh["results"][0]["answer"]["stale"] is False
    assert _total(fresh) == first + 1000


def test_settings_toggle_is_seen_by_the_next_read(tmp_path):
    _client_, store = _client(tmp_path)
    before = config.get_settings(store)
    assert before["enabled"] is True
    config.update_settings(store, enabled=False, revision=before["revision"])
    assert config.get_settings(store)["enabled"] is False


def test_app_db_arm_reuses_its_connection_and_drops_the_deadline(tmp_path):
    path = Path(tmp_path) / "carnivore.db"
    sqlite3.connect(path).execute("CREATE TABLE t (x)").connection.close()
    arm = pack_scope.Arm(carnivore=path)
    first = arm.connect(None)
    first.set_progress_handler(lambda: 1, 1)
    with pytest.raises(sqlite3.OperationalError):
        first.execute("SELECT 1 FROM t UNION SELECT 2").fetchall()
    first.close()
    second = arm.connect(None)
    assert second._conn is first._conn
    assert second.execute("SELECT count(*) FROM t").fetchone()[0] == 0


class _Boom:

    def execute(self, *_args: Any, **_kwargs: Any) -> Any:
        raise sqlite3.DatabaseError("database disk image is malformed")


def test_a_database_error_drops_the_pooled_stats_connection(tmp_path):
    _client_, store = _client(tmp_path)
    view = BatchStore(store)
    shared = view.connect(readonly=True)
    broken = view._conn
    shared._conn = _Boom()
    with pytest.raises(sqlite3.DatabaseError):
        shared.execute("SELECT 1")
    assert view._conn is None
    sound = store.connect_read()
    assert sound._conn is not broken and sound.execute("SELECT 1").fetchone()[0] == 1


def test_a_database_error_drops_the_pooled_carnivore_connection(tmp_path):
    path = Path(tmp_path) / "carnivore.db"
    sqlite3.connect(path).execute("CREATE TABLE t (x)").connection.close()
    arm = pack_scope.Arm(carnivore=path)
    loan = arm.connect(None)
    broken = loan._conn
    loan._conn = _Boom()
    with pytest.raises(sqlite3.DatabaseError):
        loan.execute("SELECT 1")
    again = arm.connect(None)
    assert again._conn is not broken and again.execute("SELECT count(*) FROM t").fetchone()[0] == 0
