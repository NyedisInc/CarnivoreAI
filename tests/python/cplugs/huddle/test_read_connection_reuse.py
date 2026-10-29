
from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path

from src.core.db import connect, db_path_for
from src.core.db_reuse.core_read import lend_pooled_read
from src.cplugs.sdk.storage import CplugStorage, StorageSpec

READS = 100


def count_connects(monkeypatch) -> list:
    opened: list = []
    real = sqlite3.connect

    def counting(*args, **kwargs):
        opened.append(str(args[0]) if args else "")
        return real(*args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", counting)
    return opened


def make_storage(tmp_path: Path) -> CplugStorage:
    storage = CplugStorage(tmp_path / "plug", StorageSpec(db="plug.db", migrations=["CREATE TABLE t (v INTEGER);"]))
    with closing(storage.connect(True)) as conn, conn:
        conn.execute("INSERT INTO t VALUES (0)")
    return storage


def test_a_burst_of_plugin_reads_opens_one_connection_per_thread_and_sees_every_write(tmp_path, monkeypatch):
    storage = make_storage(tmp_path)
    opened = count_connects(monkeypatch)
    started = time.perf_counter()
    for i in range(READS):
        with closing(storage.connect_read()) as conn:
            assert conn.execute("SELECT MAX(v) FROM t").fetchone()[0] == i
        with closing(storage.connect(True)) as writer, writer:
            writer.execute("INSERT INTO t VALUES (?)", (i + 1,))
    reads_ms = (time.perf_counter() - started) * 1000
    reader_opens = [p for p in opened if p.endswith("plug.db")]
    assert len(reader_opens) - READS == 1, f"{len(reader_opens) - READS} reader connections for {READS} reads (the rest are the writers)"
    print(f"\nplugin: {READS} reads + {READS} writes, {len(reader_opens)} connects, {reads_ms:.0f} ms")

    seen: list = []
    thread = threading.Thread(target=lambda: seen.append(storage.connect_read().execute("SELECT COUNT(*) FROM t").fetchone()[0]))
    thread.start()
    thread.join()
    assert seen == [READS + 1]
    assert len([p for p in opened if p.endswith("plug.db")]) - READS == 2, "another thread keeps its own connection"


def test_a_replaced_file_is_reopened_and_a_missing_one_creates_nothing(tmp_path):
    storage = make_storage(tmp_path)
    assert storage.connect_read().execute("SELECT COUNT(*) FROM t").fetchone()[0] == 1
    (tmp_path / "plug" / "plug.db").unlink()
    absent = storage.connect_read()
    assert absent.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 0
    assert not (tmp_path / "plug" / "plug.db").exists()


def test_a_burst_of_datastore_reads_opens_one_connection_and_sees_every_write(tmp_path, monkeypatch):
    path = db_path_for(tmp_path)
    with closing(connect(path)) as writer:
        writer.execute("CREATE TABLE t (v INTEGER)")
    opened = count_connects(monkeypatch)
    for i in range(READS):
        assert lend_pooled_read(path).execute("SELECT COUNT(*) FROM t").fetchone()[0] == i
        with closing(connect(path, create=False)) as writer:
            writer.execute("INSERT INTO t VALUES (1)")
    assert len(opened) - READS == 1, f"{len(opened) - READS} reader connections for {READS} reads"
    assert lend_pooled_read(tmp_path / "absent.db") is None
