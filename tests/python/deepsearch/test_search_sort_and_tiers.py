
from __future__ import annotations

from contextlib import closing

import pytest

from src.core.deepsearch import grouped
from src.core.deepsearch.cache import db as cache_db
from src.core.deepsearch.query import phrase_expression
from tests.python.deepsearch.helpers import build_world, drain, go_ready, rec, scan, teardown


def _g(cid: str, best: float, said: float | None = None, matches: int = 1) -> dict:
    return {"conversation_id": cid, "best": best, "best_said": said if said is not None else best, "matches": matches}


def test_the_phrase_expression_is_whole_words_in_order():
    assert phrase_expression('Flux  "Cap') == '"Flux Cap"'
    assert phrase_expression("   ") is None


def test_exact_conversations_come_first_then_the_sort_applies_inside_each_tier():
    groups = [_g("old-exact", -1.0), _g("new-fuzzy", -9.0), _g("new-exact", -2.0), _g("old-fuzzy", -8.0)]
    meta = {"old-exact": {"last_active": "2026-01-01"}, "new-fuzzy": {"last_active": "2026-06-01"},
            "new-exact": {"last_active": "2026-05-01"}, "old-fuzzy": {"last_active": None}}
    exact = {"old-exact", "new-exact"}
    by_rel = [g["conversation_id"] for g in grouped.order_groups(groups, meta, "relevance", exact)]
    by_date = [g["conversation_id"] for g in grouped.order_groups(groups, meta, "date", exact)]
    assert by_rel == ["new-exact", "old-exact", "new-fuzzy", "old-fuzzy"]
    assert by_date == ["new-exact", "old-exact", "new-fuzzy", "old-fuzzy"]
    plain = [g["conversation_id"] for g in grouped.order_groups(groups, meta, "date")]
    assert plain == ["new-fuzzy", "new-exact", "old-exact", "old-fuzzy"]
    assert [g["conversation_id"] for g in grouped.order_groups(groups, meta, "relevance")] == ["new-fuzzy", "old-fuzzy", "new-exact", "old-exact"]


def test_hits_put_phrase_hits_first_and_date_sorts_inside_the_tier():
    hits = [{"at": "2026-01-01", "exact": False}, {"at": "2026-02-01", "exact": True}, {"at": "2026-03-01", "exact": True},
            {"at": "2026-04-01", "exact": False}]
    assert [h["at"] for h in grouped.order_hits(hits, "date")] == ["2026-03-01", "2026-02-01", "2026-04-01", "2026-01-01"]
    assert [h["at"] for h in grouped.order_hits(hits, "relevance")] == ["2026-02-01", "2026-03-01", "2026-01-01", "2026-04-01"]


@pytest.fixture()
def world(tmp_path, monkeypatch):
    built = build_world(tmp_path, monkeypatch)
    with open(built["main"], "ab") as handle:
        handle.write(rec(7, "fluxy capacitors everywhere", timestamp="2026-10-01T10:00:00Z"))
        handle.write(rec(8, "the flux capacitor is humming", timestamp="2026-10-02T10:00:00Z"))
    scan(built)
    drain(built)
    go_ready(built)
    yield built
    teardown()


def _search(world, query: str, **kw) -> dict:
    with closing(cache_db.reader(world["state"])) as conn:
        return grouped.search_grouped(conn, world["state"], query, overrides={}, **kw)


def test_the_phrase_hit_leads_its_group_and_the_fuzzy_hit_follows(world):
    (group,) = _search(world, "Flux Capacitor", exact_first=True)["groups"]
    assert group["exact"] is True
    assert [(h["exact"], h["entry_uuid"]) for h in group["hits"]] == [(True, "u-8"), (False, "u-7")]


def test_date_sort_shows_the_newest_message_first_inside_the_fuzzy_tier(world):
    answer = _search(world, "capacitor", sort="date", exact_first=True)
    assert answer["sort"] == "date"
    (group,) = answer["groups"]
    assert [h["entry_uuid"] for h in group["hits"]] == ["u-8", "u-7"]


def test_a_fuzzy_only_query_is_tier_two_and_no_tiering_adds_no_keys(world):
    (group,) = _search(world, "flux capacit", exact_first=True)["groups"]
    assert group["exact"] is False and all(h["exact"] is False for h in group["hits"])
    (plain,) = _search(world, "flux capacitor")["groups"]
    assert "exact" not in plain and all("exact" not in h for h in plain["hits"])
