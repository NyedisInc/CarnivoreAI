
from __future__ import annotations

import sqlite3
import threading
from contextlib import closing

import pytest

from src.core.db import connect
from src.core.db_reuse import datastore_pool
from src.core.lineage import constants as LN
from src.core.pipeline import lineage_edge


def _db(tmp_path):
    path = tmp_path / "carnivore.db"
    conn = connect(path)
    conn.execute(f"CREATE TABLE {LN.EDGES_TABLE} (child_type TEXT, child_id TEXT, parent_type TEXT, parent_id TEXT, "
                 "edge_kind TEXT, detail_json TEXT, created_at TEXT)")
    kind = LN.CONTINUATION_KINDS[0]
    conn.execute(f"INSERT INTO {LN.EDGES_TABLE} VALUES (?,?,?,?,?,?,?)",
                 (LN.NODE_CONVERSATION, "c2", LN.NODE_CONVERSATION, "c1", kind, '{"uuid": "u-9"}', "2026-01-01"))
    conn.close()
    return path, kind


def test_lineage_of_opens_one_connection_per_thread(tmp_path, monkeypatch):
    path, kind = _db(tmp_path)
    datastore_pool._POOL.close_this_thread()
    opens = []
    real = connect
    monkeypatch.setattr(datastore_pool, "connect", lambda *a, **k: (opens.append(1), real(*a, **k))[1])
    for _ in range(50):
        got = lineage_edge.lineage_of(path, "c2")
    assert opens == [1]
    assert (got.parent_conversation_id, got.edge_kind, got.fork_uuid) == ("c1", kind, "u-9")
    assert lineage_edge.lineage_of(path, "nobody") is None
    assert len(opens) == 1
    seen = []
    worker = threading.Thread(target=lambda: seen.append(lineage_edge.lineage_of(path, "c2")))
    worker.start(); worker.join()
    assert len(opens) == 2 and seen[0] is not None
    datastore_pool._POOL.close_this_thread()


def test_lineage_read_is_query_only_and_restored(tmp_path):
    path, _kind = _db(tmp_path)
    datastore_pool._POOL.close_this_thread()
    with closing(datastore_pool.lend(path)) as lent:
        with datastore_pool.read_only(lent) as conn:
            with pytest.raises(sqlite3.OperationalError):
                conn.execute(f"DELETE FROM {LN.EDGES_TABLE}")
        lent.execute(f"DELETE FROM {LN.EDGES_TABLE}")
        lent.rollback()
    datastore_pool._POOL.close_this_thread()
