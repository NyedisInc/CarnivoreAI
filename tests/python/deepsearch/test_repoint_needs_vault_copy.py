
from __future__ import annotations

import sqlite3
from typing import List

import pytest
import structlog

from src.core.deepsearch import constants as K
from src.core.deepsearch import fallback_hook as fb
from src.core.deepsearch import pipeline_plugin as dp
from src.core.deepsearch.cache import ddl as cache_ddl
from src.core.deepsearch.live import store
from src.core.pipeline import contract as C

CONV = "aaaaaaaa-1111-2222-3333-444444444444"
PATH = "/home/x/.claude/projects/-p/" + CONV + ".jsonl"


class _Source:

    def __init__(self, held: List[str], broken: bool = False) -> None:
        self.held, self.broken = held, broken

    def files(self, conversation_id: str):
        if self.broken:
            raise OSError("vault volume not mounted")
        return [object()] if conversation_id in self.held else []


@pytest.fixture()
def conn():
    db = sqlite3.connect(":memory:")
    for statement in cache_ddl.statements():
        db.execute(statement)
    live = store.LiveFile(conversation_id=CONV, path=PATH, file_kind="conversation", family="claude", base_offset=0, base_line=0,
                          base_point_id=None, indexed_offset=10, indexed_lines=1, last_serial=None, last_serial_offset=None,
                          rows=1, filter_version="v", in_scope=1, scope="human", created_at="t", indexed_at="t")
    store.save(db, live)
    for source_id in ("a", "b"):
        fb.unregister(source_id)
    dp.vault_lookup.reset()
    yield db
    for source_id in ("a", "b"):
        fb.unregister(source_id)
    db.close()


def _mark(db: sqlite3.Connection):
    row = store.get(db, PATH)
    return "absent" if row is None else row.base_point_id


def _removed() -> C.FileRemoved:
    return C.FileRemoved(conversation_id=CONV, path=PATH, file_kind="conversation")


def _remove(db: sqlite3.Connection) -> None:
    dp.before_removal(CONV, PATH)
    dp._file_removed(db, _removed())


def test_a_conversation_the_vault_holds_is_repointed(conn):
    fb.register("a", _Source([CONV]))
    _remove(conn)
    assert _mark(conn) == K.VAULT_MARK


def test_a_conversation_the_vault_does_not_hold_is_not_repointed_and_says_so(conn):
    fb.register("a", _Source([]))
    with structlog.testing.capture_logs() as logs:
        _remove(conn)
    assert _mark(conn) == "absent"
    assert [e for e in logs if e["event"] == "deepsearch_row_gone_without_vault_copy" and e["log_level"] == "error"]


def test_an_unreadable_vault_is_not_a_no_it_is_left_for_the_lane_to_prove(conn):
    fb.register("a", _Source([], broken=True))
    _remove(conn)
    assert _mark(conn) == K.VAULT_MARK


def test_a_second_source_that_holds_it_is_enough(conn):
    fb.register("a", _Source([]))
    fb.register("b", _Source([CONV]))
    _remove(conn)
    assert _mark(conn) == K.VAULT_MARK


def test_while_booting_the_row_is_still_repointed_for_the_vault_lane_to_prove(conn):
    fb.begin_boot()
    try:
        _remove(conn)
    finally:
        fb.end_boot()
    assert _mark(conn) == K.VAULT_MARK


def test_with_no_vault_at_all_the_rows_go_as_before(conn):
    _remove(conn)
    assert _mark(conn) == "absent"


def test_the_vault_is_asked_outside_the_delivery_transaction(tmp_path):
    from src.core.db import transaction
    from src.core.pipeline import deliver, plugin_db

    seen: List[dict] = []
    lock = plugin_db.lock_for(dp.PLUGIN_ID)

    class _Watching:
        def files(self, conversation_id: str):
            seen.append({"locked": lock.locked(), "in_tx": bool(db.in_transaction)})
            return [object()]

    run = deliver.PluginRun(dp.DEEPSEARCH)
    db = plugin_db.pooled_db(tmp_path, dp.DEEPSEARCH)
    try:
        with transaction(db):
            pass
        store.save(db, store.LiveFile(conversation_id=CONV, path=PATH, file_kind="conversation", family="claude", base_offset=0,
                                      base_line=0, base_point_id=None, indexed_offset=10, indexed_lines=1, last_serial=None,
                                      last_serial_offset=None, rows=1, filter_version="v", in_scope=1, scope="human",
                                      created_at="t", indexed_at="t"))
        plugin_db.save_cursor(db, plugin_db.Cursor(path=PATH, conversation_id=CONV, family="claude", file_kind="conversation"))
        fb.register("a", _Watching())
        delivery = deliver.Delivery(tmp_path, [run], "scan")
        deliver.deliver_file_removed(delivery, deliver.FileTarget(PATH, CONV, "claude", "conversation"))
        assert run.failed is None and run.removed == 1
        assert seen == [{"locked": False, "in_tx": False}]
        assert store.get(db, PATH).base_point_id == K.VAULT_MARK
    finally:
        plugin_db.discard_pooled(tmp_path, dp.DEEPSEARCH)


def test_a_hung_vault_lookup_is_bounded_and_counts_as_not_asked(conn, monkeypatch):
    import threading

    release = threading.Event()

    class _Hung:
        def files(self, conversation_id: str):
            release.wait(5)
            return []

    monkeypatch.setattr(dp.vault_lookup, "LOOKUP_TIMEOUT_SECONDS", 0.05)
    fb.register("a", _Hung())
    try:
        _remove(conn)
    finally:
        release.set()
    assert _mark(conn) == K.VAULT_MARK


def test_the_startup_question_is_asked_while_booting_when_a_source_is_registered(conn):
    fb.register("a", _Source([]))
    fb.begin_boot()
    try:
        _remove(conn)
    finally:
        fb.end_boot()
    assert _mark(conn) == "absent"
