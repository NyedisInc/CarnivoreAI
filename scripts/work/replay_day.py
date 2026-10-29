
from __future__ import annotations

import argparse
import sqlite3
import sys
import threading
import time
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.core.work import seq, tables, tx  # noqa: E402

LIVE_ROOT = Path.home() / "Library" / "Application Support"


def busiest_day(path: Path) -> int:
    with sqlite3.connect(path) as conn:
        row = conn.execute(f"SELECT COUNT(*) AS n FROM {tables.WRITE_ACTORS} GROUP BY CAST(at / 86400 AS INTEGER) ORDER BY n DESC LIMIT 1").fetchone()
    return int(row[0]) if row else 0


def _core_writer(path: Path, stop: threading.Event, interval: float, waits: List[float]) -> None:
    """Commit one short core transaction every ``interval`` seconds and record how long BEGIN IMMEDIATE waited. Output: None."""
    conn = sqlite3.connect(path, isolation_level=None, timeout=30.0)
    conn.execute("CREATE TABLE IF NOT EXISTS replay_probe (k TEXT PRIMARY KEY, v INTEGER)")
    while not stop.is_set():
        start = time.perf_counter()
        conn.execute("BEGIN IMMEDIATE")
        waits.append(time.perf_counter() - start)
        conn.execute("INSERT INTO replay_probe VALUES ('n', 1) ON CONFLICT(k) DO UPDATE SET v = v + 1")
        conn.execute("COMMIT")
        time.sleep(interval)
    conn.close()


def _reader(path: Path, stop: threading.Event, reads: List[float]) -> None:
    while not stop.is_set():
        start = time.perf_counter()
        with sqlite3.connect(path, timeout=30.0) as conn:
            conn.execute("SELECT * FROM sessions ORDER BY id DESC LIMIT 200").fetchall()
        reads.append(time.perf_counter() - start)
        time.sleep(0.01)


def _wal(path: Path) -> int:
    wal = Path(f"{path}-wal")
    return wal.stat().st_size if wal.exists() else 0


def _phase(path: Path, seconds: float, writes: int, interval: float, pace: float = 0.0) -> Dict[str, object]:
    stop, waits, reads, work, peak = threading.Event(), [], [], [], [0]
    threads = [threading.Thread(target=_core_writer, args=(path, stop, interval, waits)), threading.Thread(target=_reader, args=(path, stop, reads))]
    for t in threads:
        t.start()
    started = time.perf_counter()

    def connect(write: bool) -> sqlite3.Connection:
        conn = sqlite3.connect(path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        return conn

    for n in range(writes):
        begin = time.perf_counter()
        with tx.write(connect, set(), lambda key: None) as conn:
            number = seq.next_seq(conn)
            conn.execute(f"INSERT INTO {tables.ITEMS} (list_key, text, position, created_by, state, created_at, updated_at, created_seq, seq) "
                         "VALUES ('replay', ?, ?, 'replay', 'open', ?, ?, ?, ?)", (f"replay {n}", n, time.time(), time.time(), number, number))
            conn.execute(f"INSERT INTO {tables.MESSAGES} (item_id, author, kind, text, created_at, seq) VALUES (last_insert_rowid(), 'claude', 'info', 'r', ?, ?)",
                         (time.time(), number))
        work.append(time.perf_counter() - begin)
        peak[0] = max(peak[0], _wal(path))
        if pace:
            time.sleep(pace)
    while time.perf_counter() - started < seconds:
        peak[0] = max(peak[0], _wal(path))
        time.sleep(0.05)
    stop.set()
    for t in threads:
        t.join()

    def ms(values: List[float], q: float) -> float:
        if not values:
            return 0.0
        ordered = sorted(values)
        return round(ordered[min(len(ordered) - 1, max(0, -(-len(ordered) * int(q) // 100) - 1))] * 1000, 2)

    return {"writes": writes, "elapsed_s": round(time.perf_counter() - started, 2), "core_waits": len(waits),
            "core_wait_p50_ms": ms(waits, 50), "core_wait_p99_ms": ms(waits, 99), "core_wait_max_ms": round(max(waits, default=0) * 1000, 2),
            "read_p99_ms": ms(reads, 99), "work_tx_p50_ms": ms(work, 50), "work_tx_p99_ms": ms(work, 99),
            "work_tx_max_ms": round(max(work, default=0) * 1000, 2), "peak_wal_bytes": peak[0]}


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("db", type=Path)
    parser.add_argument("--writes", type=int, default=0, help="work transactions to replay (default: the busiest day's count)")
    parser.add_argument("--core-interval", type=float, default=0.05)
    parser.add_argument("--pace", type=float, default=0.0, help="seconds between replayed writes (0: full speed, the worst case)")
    args = parser.parse_args(argv)
    path = args.db.resolve()
    if LIVE_ROOT in path.parents:
        print(f"refused: {path} is under {LIVE_ROOT}; replay against a copy only")
        return 2
    writes = args.writes or busiest_day(path)
    baseline = _phase(path, 5.0, 0, args.core_interval)
    replay = _phase(path, 5.0, writes, args.core_interval, args.pace)
    print("busiest day writes:", busiest_day(path))
    print("baseline:", baseline)
    print("replay:  ", replay)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
