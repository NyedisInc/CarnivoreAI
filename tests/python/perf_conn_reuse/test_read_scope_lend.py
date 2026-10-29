
from __future__ import annotations

from contextlib import closing

from src.cplugs.sdk.storage import CplugStorage, StorageSpec
from tests.python.perf_conn_reuse.helpers import count_connects, opens_of

N = 40


def test_scopes_reuse_the_threads_connection_and_see_a_write_made_inside(tmp_path, monkeypatch):
    storage = CplugStorage(tmp_path / "plug", StorageSpec(db="plug.db", migrations=["CREATE TABLE t (v INTEGER);"]))
    with closing(storage.connect(True)) as conn, conn:
        conn.execute("INSERT INTO t VALUES (0)")
    with closing(storage.connect_read()) as conn:
        conn.execute("SELECT 1").fetchall()
    opened = count_connects(monkeypatch)
    for i in range(N):
        with storage.read_scope():
            with closing(storage.connect(False)) as conn:
                assert conn.execute("SELECT MAX(v) FROM t").fetchone()[0] == i
            with closing(storage.connect(True)) as writer, writer:
                writer.execute("INSERT INTO t VALUES (?)", (i + 1,))
            with closing(storage.connect(False)) as conn:
                assert conn.execute("SELECT MAX(v) FROM t").fetchone()[0] == i + 1
    scopes = opens_of(opened, "plug.db")
    print(f"\nread_scope: {N} scopes, {scopes} connects (writers {N}; before: {2 * N})")
    assert scopes == N
