
from __future__ import annotations

import time
from pathlib import Path
from typing import List

import pytest

from src.core.db_reuse.change_cache import CACHE
from src.core.work.storage import WorkStorage
from src.cplugs.huddle import rules
from src.cplugs.huddle.store import TaskManagerStore

ITEMS = 500


@pytest.fixture()
def store(tmp_path: Path):
    CACHE.clear()
    s = TaskManagerStore(WorkStorage(tmp_path / "cplugs" / "huddle", tmp_path), notify=lambda key: None)
    for n in range(ITEMS):
        s.add("12", f"item {n}", actor="joe")
    yield s
    CACHE.clear()


def count_numbering(store: TaskManagerStore, monkeypatch) -> List[int]:
    calls: List[int] = []
    real = store._numbers
    monkeypatch.setattr(store, "_numbers", lambda conn, keys: (calls.append(1), real(conn, keys))[1])
    return calls


def test_hundred_reads_number_once_and_a_write_renumbers(store, monkeypatch):
    ids = [i["id"] for i in store.list_items("12")["items"]]
    CACHE.clear()
    calls = count_numbering(store, monkeypatch)
    for _ in range(100):
        assert store.item(ids[10])["number"] == 11
    assert len(calls) == 1
    new = store.add("12", "late", actor="joe")
    assert store.item(new["id"])["number"] == ITEMS + 1 and store.item(ids[10])["number"] == 11
    store.update(ids[0], actor="joe", state=rules.DONE)
    assert store.item(ids[10])["number"] == 10
    order = [ids[-1]] + [i for i in ids if i != ids[-1]] + [new["id"]]
    with store._read_connection() as conn:
        rev = store._list_revision(conn, "12")
    store.reorder("12", order, actor="joe", expected_revision=rev)
    assert store.item(ids[-1])["number"] == 1 and store.numbers(["12"])[ids[10]] == 11


def test_time_per_item_read(store, capsys):
    ids = [i["id"] for i in store.list_items("12")["items"]]
    t = time.perf_counter()
    for _ in range(50):
        with store._read_connection() as conn:
            store._numbers(conn, ["12"])
    uncached = (time.perf_counter() - t) / 50
    store.item(ids[0])
    t = time.perf_counter()
    for _ in range(50):
        store.item(ids[0])
    cached = (time.perf_counter() - t) / 50
    with capsys.disabled():
        print(f"\nnumbering per item() read: before {uncached * 1000:.2f} ms, after (whole item() cached) {cached * 1000:.2f} ms")
    assert cached < uncached
