
from __future__ import annotations

import sqlite3

from src.core.crosstalk import directory, store
from src.core.db_steps import STEPS


def _setup(tmp_path, monkeypatch):
    path = tmp_path / "cloude.db"

    def connect():
        conn = sqlite3.connect(path, isolation_level=None)
        conn.row_factory = sqlite3.Row
        return conn

    with connect() as conn:
        STEPS[56](conn)
        STEPS[89](conn)
        STEPS[93](conn)
    monkeypatch.setattr(store, "_conn", connect)
    monkeypatch.setattr(store, "_notify", lambda: None)
    return connect


def _who(key, ses, epoch):
    return {"key": key, "id": ses, "uuid": key, "epoch": epoch, "name": key, "provider": "claude", "model": None}


def test_repin_moves_identity_and_spares_paused_and_native_receipts(tmp_path, monkeypatch):
    connect = _setup(tmp_path, monkeypatch)
    agent, peer = _who("uuid-a", "ses_old", 10), _who("uuid-p", "ses_p", 20)
    store.grant_contact(peer["key"], agent["key"], 20, 10)
    queued = store.reserve(sender=peer, receiver=agent, text="queued")["id"]
    held = store.reserve(sender=peer, receiver=agent, text="held")["id"]
    native = store.reserve(sender=peer, receiver=agent, text="native")["id"]
    delivered = store.reserve(sender=peer, receiver=agent, text="delivered")["id"]
    with connect() as conn:
        conn.execute("UPDATE crosstalk_contacts SET paused=1, last_owner_input=5")
        conn.execute("UPDATE crosstalk_messages SET status='held' WHERE id=?", (held,))
        conn.execute("UPDATE crosstalk_messages SET status='held', reason='native_receipt_pending:abc' WHERE id=?", (native,))
        conn.execute("UPDATE crosstalk_messages SET status='delivered' WHERE id=?", (delivered,))
    store.watch(watcher_key="uuid-a", watcher_id="ses_old", watcher_epoch=10,
                target_key="uuid-p", target_id="ses_p", target_epoch=20)
    store.watch(watcher_key="uuid-p", watcher_id="ses_p", watcher_epoch=20,
                target_key="uuid-a", target_id="ses_old", target_epoch=10)

    counts = store.repin("uuid-a", "ses_new", 99)
    assert counts == {"contacts": 1, "pending": 2, "delivered": 1, "watches": 2}

    with connect() as conn:
        row = lambda mid: dict(conn.execute("SELECT * FROM crosstalk_messages WHERE id=?", (mid,)).fetchone())
        for mid in (queued, held):
            assert (row(mid)["receiver_id"], row(mid)["receiver_epoch"]) == ("ses_new", 99)
        assert (row(native)["receiver_id"], row(native)["receiver_epoch"]) == ("ses_old", 10)
        assert (row(delivered)["receiver_id"], row(delivered)["receiver_epoch"]) == ("ses_old", 99)
        contact = dict(conn.execute("SELECT * FROM crosstalk_contacts").fetchone())
        assert contact["paused"] == 1 and contact["last_owner_input"] == 5
        assert store.contact("uuid-p", "uuid-a", 20, 99) and not store.contact("uuid-p", "uuid-a", 20, 10)
        w_by = dict(conn.execute("SELECT * FROM crosstalk_watches WHERE watcher_key='uuid-a'").fetchone())
        w_on = dict(conn.execute("SELECT * FROM crosstalk_watches WHERE target_key='uuid-a'").fetchone())
        assert (w_by["watcher_id"], w_by["watcher_epoch"], w_by["target_epoch"]) == ("ses_new", 99, 20)
        assert (w_on["target_id"], w_on["target_epoch"], w_on["watcher_epoch"]) == ("ses_new", 99, 20)


def test_exact_session_uuid_tier_outranks_names():
    cards = [
        {"id": "ses_1", "tmux_name": "t1", "name": "uuid-x", "session_uuid": "u1"},
        {"id": "ses_2", "tmux_name": "t2", "name": "other", "session_uuid": "uuid-x"},
    ]
    res = directory.resolve_handle("uuid-x", cards)
    assert res.tier == "session_uuid" and [c["id"] for c in res.matches] == ["ses_2"] and not res.ambiguous
