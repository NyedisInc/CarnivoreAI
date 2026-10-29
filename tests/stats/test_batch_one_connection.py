from __future__ import annotations

import time

from src.core.stats import answers, queries
from src.core.stats.store import StatsStore
from src.models.stats import QueryRequest
from tests.stats.test_batch_live import _client, _item, _row


def test_batch_shares_one_connection_and_matches_separate_queries(tmp_path, monkeypatch):
    _client_, store = _client(tmp_path)
    now = int(time.time()) // 60 * 60
    _row(store, now - 120, "c1")
    _row(store, now - 60, "c2", model="m2", inp=7)
    items = [_item(3600), _item(7200), {**_item(3600), "group_by": "model"}]
    want = [queries.execute(store, QueryRequest.model_validate(i)) for i in items]

    opened = []
    raw_reads = []
    real_connect = StatsStore.connect
    monkeypatch.setattr(StatsStore, "connect",
                        lambda self, **kw: (raw_reads.append(kw) if kw.get("readonly") else None, real_connect(self, **kw))[1])
    real = StatsStore.connect_read
    monkeypatch.setattr(StatsStore, "connect_read", lambda self: (opened.append({"readonly": True}), real(self))[1])
    got = queries.execute_batch(store, items)

    assert [r["result"] for r in got["results"]] == want
    answers.wait_idle()
    assert [kw for kw in raw_reads if kw.get("readonly")] == []
    assert opened == [{"readonly": True}]
    assert got["revision"] == store.revision()
