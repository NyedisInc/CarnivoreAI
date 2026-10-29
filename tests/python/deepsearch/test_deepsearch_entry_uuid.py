
from __future__ import annotations

from contextlib import closing

import pytest

from tests.python.deepsearch.helpers import build_world, drain, go_ready, rec, scan, teardown

from src.core.deepsearch import extract, grouped, search
from src.core.deepsearch.cache import db as cache_db


@pytest.fixture()
def world(tmp_path, monkeypatch):
    built = build_world(tmp_path, monkeypatch)
    with open(built["main"], "ab") as handle:
        handle.write(rec(7, "the quokkaentry marker lives in this message"))
    scan(built)
    drain(built)
    go_ready(built)
    yield built
    teardown()


def test_a_grouped_hit_carries_the_uuid_of_the_message_it_found(world):
    with closing(cache_db.reader(world["state"])) as conn:
        groups = grouped.search_grouped(conn, world["state"], "quokkaentry", overrides={})["groups"]
    (hit,) = groups[0]["hits"]
    assert hit["entry_uuid"] == "u-7"


def test_a_flat_hit_carries_it_too(world):
    with closing(cache_db.reader(world["state"])) as conn:
        hits = search.search(conn, world["state"], "quokkaentry", overrides={})["hits"]
    assert [h["entry_uuid"] for h in hits] == ["u-7"]


def test_a_record_with_no_uuid_gives_none_not_a_made_up_one():
    assert extract.record_identity(b'{"timestamp": "2026-10-12T14:03:00Z"}') == ("2026-10-12T14:03:00Z", None)
    assert extract.record_identity(b"not json") == (None, None)
    assert extract.record_identity(b'{"uuid": "a", "timestamp": "t"}') == ("t", "a")
