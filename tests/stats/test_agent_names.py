from __future__ import annotations

import sqlite3
import time

import pytest

from src.core.db import db_path_for
from src.core.stats import agent_names, config, live_view, queries
from src.core.stats.store import StatsStore
from src.models.stats import QueryRequest
from tests.stats import seed

NOW = 1_800_000_000 // 60 * 60


@pytest.fixture
def store(tmp_path):
    value = StatsStore(tmp_path)
    value.initialize()
    config.ensure_schema(value)
    app = sqlite3.connect(db_path_for(tmp_path))
    app.execute("CREATE TABLE sessions (id INTEGER PRIMARY KEY, claude_session_uuid TEXT, title TEXT, tmux_name TEXT)")
    app.executemany("INSERT INTO sessions (claude_session_uuid, title, tmux_name) VALUES (?,?,?)", [
        ("aaa", "api work", "carnivore_x1"), ("bbb", None, "carnivore_docs"), ("ccc", "  ", "cloude_old")])
    app.commit()
    app.close()
    agent_names.forget()
    with value.connect() as db:
        rows = [(NOW - 60 * m, "local", "claude", conv, "/p", "opus", kind, 10, 0, 0, 0, None, None, 1, 0, 1, "ok")
                for m in range(0, 3) for conv, kind in (("aaa", "session"), ("aaa:agent-1", "subagent"), ("bbb", "session"), ("ccc", "session"), ("zzz", "session"))]
        seed.executemany(db, "INSERT INTO minute_usage VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    return value


def _timeline(top_n: int):
    return QueryRequest.model_validate({
        "metric": "total_tokens", "operation": "timeline", "group_by": "conversation_id", "top_n": top_n,
        "from": "2027-01-15T07:00:00Z", "to": "2027-01-15T09:00:00Z", "resolution": "hour"})


def test_lines_are_named_subagents_fold_and_the_rest_is_other(store):
    full = queries.execute(store, _timeline(10))
    labels = {s["label"]: sum(p["value"] or 0 for p in s["points"]) for s in full["series"]}
    assert labels == {"api work": 60, "docs": 30, "old": 30, "unnamed agent": 30}
    assert not any(s["label"] in ("aaa", "bbb", "ccc", "zzz") for s in full["series"])
    capped = queries.execute(store, _timeline(2))
    assert [s["label"] for s in capped["series"]] == ["api work", "docs", "Other"]
    assert sum(p["value"] or 0 for p in capped["series"][2]["points"]) == 60


def test_live_list_is_five_minute_rate_by_name_highest_first(store):
    answer = live_view.live_v2(store, now=NOW + 5)
    assert answer["agents_5m"][0] == {"conversation_id": "aaa", "name": "api work", "tokens": 60, "tokens_per_minute": 12.0}
    assert [a["name"] for a in answer["agents_5m"]] == ["api work", "docs", "old", "unnamed agent"]
    quiet = live_view.live_v2(store, now=NOW + 30 * 60)
    assert quiet["agents_5m"] == []
