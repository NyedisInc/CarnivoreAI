
import json
import sqlite3
import threading
import time
from pathlib import Path

import pytest

from src.core.work.storage import WorkStorage
from src.core.db_reuse.change_cache import CACHE
from src.cplugs.huddle.store import TaskManagerStore

LISTS = ["all"] + [str(n) for n in range(1, 13)]
ITEMS = 1000
HIT_BUDGET_S = 0.05


@pytest.fixture()
def seeded(tmp_path: Path):
    CACHE.clear()
    storage = WorkStorage(tmp_path / "cplugs" / "huddle", tmp_path)
    store = TaskManagerStore(storage, notify=lambda key: None)
    for n in range(ITEMS):
        item = store.add(LISTS[n % len(LISTS)], f"item {n}", actor="joe")
        if n % 3 == 0:
            store.post(item["id"], f"claude note {n}", actor="claude", kind="info")
    yield store, storage
    CACHE.clear()


def count_connects(storage, monkeypatch) -> list:
    opened: list = []
    real = storage.connect
    monkeypatch.setattr(storage, "connect", lambda write: (opened.append(write), real(write))[1])
    return opened


def test_a_hit_is_identical_bounded_and_rebuilt_after_any_commit(seeded, monkeypatch):
    store, storage = seeded
    first = store.aggregate(hide_swarm=True)
    assert sum(len(g["items"]) for g in first["groups"]) == ITEMS
    assert json.dumps(first, sort_keys=True) == json.dumps(store._build_aggregate(True), sort_keys=True)

    opened = count_connects(storage, monkeypatch)
    started = time.perf_counter()
    again = store.aggregate(hide_swarm=True)
    assert time.perf_counter() - started < HIT_BUDGET_S
    assert opened == []
    assert json.dumps(again, sort_keys=True) == json.dumps(first, sort_keys=True)
    again["groups"][0]["items"][0]["tagged_by"] = "x"
    assert "tagged_by" not in store.aggregate(hide_swarm=True)["groups"][0]["items"][0]

    store.add("all", "fresh", actor="joe")
    assert any(i["text"] == "fresh" for g in store.aggregate(hide_swarm=True)["groups"] for i in g["items"])

    with sqlite3.connect(storage.db_path) as other:
        other.execute("UPDATE work_items SET note = 'raw' WHERE id = 1")
    assert next(i for g in store.aggregate(hide_swarm=True)["groups"] for i in g["items"] if i["id"] == 1)["note"] == "raw"


def test_a_burst_of_callers_builds_once(seeded, monkeypatch):
    store, storage = seeded
    opened = count_connects(storage, monkeypatch)
    results: list = []
    threads = [threading.Thread(target=lambda: results.append(store.aggregate(hide_swarm=True))) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(results) == 8 and all(r["cursor"] == results[0]["cursor"] for r in results)
    built_queries = len(opened)
    assert built_queries <= len(LISTS) * 2 + 4


def test_cache_never_serves_a_full_body_for_live_only_or_the_reverse(seeded):
    store, storage = seeded
    done = store.add("1", "settled", actor="joe")
    store.update(done["id"], actor="joe", approve=True)
    with sqlite3.connect(storage.db_path) as raw:
        raw.execute("UPDATE work_items SET claude_read_seq = joe_seq WHERE id = ?", (done["id"],))
    for first_live in (True, False):
        CACHE.clear()
        order = (True, False) if first_live else (False, True)
        bodies = {flag: store.aggregate(hide_swarm=True, live_only=flag) for flag in order}
        again = {flag: store.aggregate(hide_swarm=True, live_only=flag) for flag in order}
        for flag in order:
            assert json.dumps(again[flag], sort_keys=True) == json.dumps(bodies[flag], sort_keys=True)
        assert all("done_count" in g for g in bodies[True]["groups"])
        assert not any("done_count" in g for g in bodies[False]["groups"])
        full_ids = {i["id"] for g in bodies[False]["groups"] for i in g["items"]}
        live_ids = {i["id"] for g in bodies[True]["groups"] for i in g["items"]}
        assert done["id"] in full_ids and done["id"] not in live_ids
