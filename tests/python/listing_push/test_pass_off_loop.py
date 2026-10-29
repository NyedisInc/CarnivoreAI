
from __future__ import annotations

import asyncio
import time

import pytest
from types import SimpleNamespace

from src.api import session_records_routes as routes

SLOW_SECONDS = 0.4


def test_slow_keep_does_not_block_the_loop(tmp_path, monkeypatch) -> None:
    db = tmp_path / "carnivore.db"
    db.write_bytes(b"")
    monkeypatch.setattr("src.core.db.db_path_for", lambda _dir: db)
    monkeypatch.setattr(routes, "read_stored_rows", lambda *_a: [{"session_uuid": "u1", "lifecycle": "running", "origin": "created"}])

    async def no_wake(*_a, **_k) -> None:
        return None

    monkeypatch.setattr(routes.asleep_wake_listing, "stamp_next_wake", no_wake)

    def slow_keep(row: dict) -> bool:
        time.sleep(SLOW_SECONDS)
        return True

    async def scenario() -> tuple:
        ticks = 0

        async def ticker() -> None:
            nonlocal ticks
            while True:
                await asyncio.sleep(0.01)
                ticks += 1

        task = asyncio.ensure_future(ticker())
        records = await routes.stored_record_rows(SimpleNamespace(), keep=slow_keep)
        task.cancel()
        return ticks, records

    ticks, records = asyncio.run(scenario())
    assert [r.session_uuid for r in records] == ["u1"]
    assert ticks >= 10


@pytest.mark.parametrize("slow", ["key_of", "model_dump"])
def test_pass_body_keys_diffs_and_dumps_off_the_loop(slow: str) -> None:
    from src.api.session_listing_collections import _dump
    from src.core.listing_push.publisher import Collection, CollectionResult, ListingPublisher

    class Row:
        def model_dump(self, mode: str = "json") -> dict:
            if slow == "model_dump":
                time.sleep(SLOW_SECONDS)
            return {"k": "a"}

    def key_of(row: dict) -> str:
        if slow == "key_of":
            time.sleep(SLOW_SECONDS)
        return row["k"]

    async def build(_context) -> CollectionResult:
        return CollectionResult(rows=await _dump([Row()]))

    publisher = ListingPublisher([Collection("c", build, key_of)], lambda _f: 0, lambda: 0)

    async def scenario() -> tuple:
        ticks = 0

        async def ticker() -> None:
            nonlocal ticks
            while True:
                await asyncio.sleep(0.01)
                ticks += 1

        task = asyncio.ensure_future(ticker())
        frame = await publisher._pass_body()
        task.cancel()
        return ticks, frame

    ticks, frame = asyncio.run(scenario())
    assert frame is not None and frame["changes"]["c"]["upsert"]
    assert ticks >= 20
