
from __future__ import annotations

import sqlite3
import threading

import pytest

from src.core.db import connect
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


def test_lineage_of_opens_one_connection_per_thread_and_stays_read_only(tmp_path, monkeypatch):
    path, kind = _db(tmp_path)
    lineage_edge._drop_reader()
    opens = []
    real = connect
    monkeypatch.setattr("src.core.db.connect", lambda *a, **k: (opens.append(1), real(*a, **k))[1])
    for _ in range(50):
        got = lineage_edge.lineage_of(path, "c2")
    assert opens == [1]
    assert (got.parent_conversation_id, got.edge_kind, got.fork_uuid) == ("c1", kind, "u-9")
    assert lineage_edge.lineage_of(path, "nobody") is None
    assert len(opens) == 1
    with pytest.raises(sqlite3.OperationalError):
        lineage_edge._reader(path).execute(f"DELETE FROM {LN.EDGES_TABLE}")
    seen = []
    worker = threading.Thread(target=lambda: seen.append(lineage_edge.lineage_of(path, "c2")))
    worker.start(); worker.join()
    assert len(opens) == 2 and seen[0] is not None
    lineage_edge._drop_reader()
