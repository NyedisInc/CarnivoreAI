
from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import List, Tuple

from src.core.deepsearch import pipeline_plugin as dp
from src.core.deepsearch.cache import db as cache_db
from src.core.deepsearch.live import range_rows, store
from src.core.pipeline import deliver
from src.core.pipeline import engine as engine_mod
from tests.pipeline.test_deepsearch_plugin import (Driver, hits, line, live_rows, old_index, world)  # noqa: F401

CAP = 1500
LINES = 50


def _file_text(count: int) -> bytes:
    pad = "padding " * 14
    return b"".join(line(i, f"{pad} gapword{i}", "assistant" if i % 2 else "user") for i in range(count))


def test_a_gap_bigger_than_the_run_budget_is_delivered_across_runs_with_no_write_lock_held(world, monkeypatch):
    f = world.files
    f.b.write_bytes(_file_text(LINES))
    spec = world.specs[1]
    driver = Driver(world.new)
    driver.deliver([spec])
    assert len(hits(world.new, "gapword7")) == 1
    index_end = f.b.stat().st_size
    with closing(cache_db.open_cache(world.new)) as conn:
        store.delete_file(conn, int(store.get(conn, str(f.b)).id))
    assert hits(world.new, "gapword7") == []
    with open(f.b, "ab") as handle:
        handle.write(line(LINES, "the newest message gapword%d" % LINES, "assistant"))
    assert f.b.stat().st_size - index_end < CAP < index_end

    reads: List[Tuple[int, int, bool]] = []
    real_reader = range_rows.RangeReader

    class Probed(real_reader):

        def __iter__(self):
            probe = sqlite3.connect(str(world.new / "deepsearch.db"), timeout=0.2, isolation_level=None)
            try:
                probe.execute("BEGIN IMMEDIATE")
                probe.execute("ROLLBACK")
                writable = True
            except sqlite3.OperationalError:
                writable = False
            finally:
                probe.close()
            reads.append((self.start, self.end, writable))
            yield from super().__iter__()

    monkeypatch.setattr(range_rows, "RangeReader", Probed)
    real_delivery = engine_mod.Delivery
    runs: List[int] = []

    def small_budget(*args, **kwargs):
        runs.append(1)
        return real_delivery(*args, **kwargs, budget=deliver.Budget(CAP))

    monkeypatch.setattr(engine_mod, "Delivery", small_budget)
    driver.deliver([spec])

    gap = [r for r in reads if r[1] <= index_end]
    assert len(gap) >= 2, reads
    assert all(end - start <= CAP for start, end, _ in gap), gap
    assert gap[0][0] == 0 and all(a[1] <= b[0] + CAP and b[0] > a[0] for a, b in zip(gap, gap[1:])), gap
    assert all(writable for _, _, writable in reads), reads
    assert len(runs) >= 3
    old_index(world.old, [spec])
    total = 0
    for word in ("gapword0", "gapword7", "gapword%d" % (LINES - 1), "gapword%d" % LINES):
        assert hits(world.new, word) == hits(world.old, word) and len(hits(world.new, word)) == 1, word
        total += 1
    assert total == 4
    assert live_rows(world.new) == live_rows(world.old) == {str(f.b): (f.b.stat().st_size, LINES + 1, LINES + 1, 1)}
