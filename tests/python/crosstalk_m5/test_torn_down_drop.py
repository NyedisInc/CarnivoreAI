
from __future__ import annotations

import sqlite3
import time

import pytest

from src.core.crosstalk import ddl, gone, store
from src.core.swarm import stream_sources


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "x.db"
    with sqlite3.connect(path) as c:
        c.execute(ddl.DDL_V57[0])
        now = time.time()
        for mid, sender, receiver in (("m-1", "uuid-boss", "uuid-gone"), ("m-2", "uuid-boss", "uuid-gone"),
                                      ("m-3", "owner", "uuid-gone"), ("m-4", "uuid-boss", "uuid-other")):
            c.execute("INSERT INTO crosstalk_messages (id,thread,sender_key,receiver_key,sender_id,receiver_id,sender_name,"
                      "sender_provider,text,status,created_at,expires_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                      (mid, "t", sender, receiver, sender, "ses_gone", "boss", "claude", "hi", "queued", now, now + 86400))

    def conn():
        c = sqlite3.connect(path)
        c.row_factory = sqlite3.Row
        return c

    monkeypatch.setattr(store, "_conn", conn)
    return conn


def test_teardown_drops_waiting_messages_and_notifies_each_sender_once(db):
    assert gone.drop_for_torn_down("uuid-gone") == 3
    with db() as c:
        rows = {r["id"]: dict(r) for r in c.execute("SELECT * FROM crosstalk_messages")}
    assert all(rows[m]["status"] == "failed" and rows[m]["reason"] == gone.RECEIVER_TORN_DOWN for m in ("m-1", "m-2", "m-3"))
    assert rows["m-4"]["status"] == "queued"
    notices = [r for r in rows.values() if r["source"] == "system"]
    assert sorted((n["receiver_key"], n["status"]) for n in notices) == [("owner", "delivered"), ("uuid-boss", "queued")]
    assert all(stream_sources.is_expiry_notice(n) for n in notices)
    assert gone.drop_for_torn_down("uuid-gone") == 0
