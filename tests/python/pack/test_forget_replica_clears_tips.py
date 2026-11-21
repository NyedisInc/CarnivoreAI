
from __future__ import annotations

from contextlib import closing

from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.pack.identity import replicas
from src.core.pack.transport import bundles

UID, PEER = "uid-3028", "iid-tower"


def test_forget_replica_clears_sender_tips(tmp_path) -> None:
    assert ensure_db_migrated(tmp_path).status == "ok"
    with closing(connect(db_path_for(tmp_path), create=False)) as conn:
        replicas.record_replica(conn, UID, PEER, "/x", "carried")
        bundles.record_tips(conn, UID, PEER, ["a" * 40])
        bundles.record_tips(conn, UID, "iid-other", ["b" * 40])
        conn.commit()
        assert bundles.read_tips(conn, UID, PEER) == ["a" * 40]
        assert replicas.forget_replica(conn, UID, PEER) is True
        assert bundles.read_tips(conn, UID, PEER) == []
        assert bundles.read_tips(conn, UID, "iid-other") == ["b" * 40]
