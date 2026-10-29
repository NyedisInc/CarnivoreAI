
import asyncio
import sqlite3
from pathlib import Path

from src.core.federation import peer_hosts, peer_listing
from src.core.listing_prefetch import build_listing_prefetch


def test_prefetch_uses_the_batched_reader_once_for_all_names() -> None:
    calls = []

    def batch(names):
        calls.append(list(names))
        return {n: (f"label-{n}", {"id": 1}) for n in names}

    def boom(_n):
        raise AssertionError("per-name reader used although the batch answered")

    pre = build_listing_prefetch(
        names=["a", None, "b", "a"],
        label_for_name=boom,
        identity_for_live_name=boom,
        label_identity_for_names=batch,
    )
    assert calls == [["a", "b"]]
    assert pre.label_for("b") == "label-b" and pre.identity_for("a") == {"id": 1}


def test_prefetch_falls_back_per_name_for_a_name_the_batch_omitted() -> None:
    pre = build_listing_prefetch(
        names=["a", "b"],
        label_for_name=lambda n: f"solo-{n}",
        identity_for_live_name=lambda n: None,
        label_identity_for_names=lambda names: {"a": ("batched", None)},
    )
    assert pre.label_for("a") == "batched" and pre.label_for("b") == "solo-b"


def test_peer_list_is_read_once_until_the_database_is_written(tmp_path: Path) -> None:
    db = tmp_path / "t.db"
    opened = []

    def open_db() -> sqlite3.Connection:
        opened.append(1)
        conn = sqlite3.connect(db)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE IF NOT EXISTS hosts (k TEXT)")
        return conn

    keeper = open_db()
    opened.clear()
    listed = []
    real = peer_hosts.list_peers
    peer_hosts.list_peers = lambda conn: listed.append(1) or []
    peer_listing._PEERS_CACHE = None
    try:
        for _ in range(5):
            assert peer_listing.read_peers(open_db) == []
        assert len(opened) == 1, "an unchanged database must not be reopened"
        with sqlite3.connect(db) as conn:
            conn.execute("INSERT INTO hosts VALUES ('x')")
        peer_listing.read_peers(open_db)
        assert len(opened) == 2, "a write must invalidate the cached peer list"
    finally:
        peer_hosts.list_peers = real
        keeper.close()
        peer_listing._PEERS_CACHE = None
