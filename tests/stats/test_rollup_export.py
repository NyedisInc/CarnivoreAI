from __future__ import annotations

from tests.lifecycle_helpers import add_row  # noqa: F401,E402

import json
import random
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Tuple

import pytest

from src.core import db as core_db
from src.core.computers import direction, store as link_store
from src.core.federation import grants
from src.core.db import db_path_for
from src.core.deepsearch import peer_air_gap
from src.main import app
from src.core.stats import config, project_groups, rollup
from src.core.stats.plugin import revision, schema
from src.core.stats.plugin import rollup as write
from src.core.stats.plugin.extract import project_key
from src.core.stats.store import StatsStore
from tests.python.federation.test_pairing_routes import _client, _pair, _token, macs  # noqa: F401

HOUR = 3600
BASE = 1_760_000_000 // HOUR * HOUR
PROJECTS = [project_key(f"/work/p{i}") for i in range(20)]
GAPPED = PROJECTS[0]
MODELS = ("claude-opus", "claude-sonnet")
CONVERSATIONS = 1900
HOURS = 10


def _fresh(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    schema.migrate(conn, 0)
    return conn


def _source(conn: sqlite3.Connection, conversation: str) -> int:
    conn.execute("INSERT INTO dim_source (path_key, conversation_id, provider, agent_kind) VALUES (?,?,?,?)",
                 (abs(hash(conversation)) % (2 ** 62), conversation, "claude", "session"))
    return conn.execute("SELECT id FROM dim_source WHERE conversation_id = ?", (conversation,)).fetchone()[0]


def _flush(conn: sqlite3.Connection, src: int, project: str, hours: List[int], rng: random.Random) -> None:
    batch = write.Batch(src)
    for hour in hours:
        t = BASE + hour * HOUR + rng.randrange(60, 3000)
        for model in MODELS:
            batch.add_usage(t, model, project, "v1", (rng.randrange(1, 900), rng.randrange(0, 90),
                                                      rng.randrange(0, 5000), rng.randrange(1, 400)),
                            rng.randrange(1, 90_000), 1)
            batch.add_counter(t, model, project, "tool_calls", "Bash", rng.randrange(1, 9))
            batch.add_counter(t, model, project, "tool_calls", "Edit", rng.randrange(1, 9))
            batch.add_counter(t, model, project, "stop_reasons", "end_turn", 1)
    batch.flush(conn, {})


@pytest.fixture(scope="module")
def big(tmp_path_factory) -> Tuple[sqlite3.Connection, Dict[str, int]]:
    conn = _fresh(tmp_path_factory.mktemp("rollup") / "stats.db")
    rng = random.Random(7)
    sources = {}
    for i in range(CONVERSATIONS):
        conversation = f"conv-{i:05d}"
        sources[conversation] = _source(conn, conversation)
        _flush(conn, sources[conversation], PROJECTS[i % len(PROJECTS)], list(range(HOURS)), rng)
    conn.commit()
    return conn, sources


def _pull(conn: sqlite3.Connection, since: int = 0, **kw: Any) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    pages, groups, cursor, until = [], [], None, None
    while True:
        page = rollup.export_rollup(conn, since, until_revision=until, cursor=cursor, **kw)
        assert len(json.dumps(page).encode()) < rollup.MAX_PAGE_BYTES
        pages.append(page)
        groups.extend(page["groups"])
        until, cursor = page["until_revision"], page["next_cursor"]
        if page["complete"]:
            return pages, groups
        assert cursor and page["groups"]


def _source_totals(conn: sqlite3.Connection, skip: FrozenSet[str] = frozenset()) -> Dict[str, int]:
    marks = ",".join("?" for _ in skip) or "''"
    row = conn.execute(
        "SELECT COUNT(*), SUM(u.input), SUM(u.cache_write), SUM(u.cache_read), SUM(u.output), SUM(u.cost_nano), "
        "SUM(u.messages), SUM(u.priced) FROM usage_hour u JOIN dim_project p ON p.id = u.project "
        f"WHERE p.name NOT IN ({marks})", tuple(skip)).fetchone()
    count = conn.execute("SELECT COUNT(*), SUM(c.value) FROM counter_hour c JOIN dim_project p ON p.id = c.project "
                         f"WHERE p.name NOT IN ({marks})", tuple(skip)).fetchone()
    return {"usage_rows": row[0], "input": row[1], "cache_write": row[2], "cache_read": row[3], "output": row[4],
            "cost": row[5], "messages": row[6], "priced": row[7], "counter_rows": count[0], "counter_sum": count[1]}


def _page_totals(groups: List[Dict[str, Any]]) -> Dict[str, int]:
    usage = [u for g in groups for u in g["usage"]]
    counters = [c for g in groups for c in g["counters"]]
    return {"usage_rows": len(usage), "input": sum(u[2] for u in usage), "cache_write": sum(u[3] for u in usage),
            "cache_read": sum(u[4] for u in usage), "output": sum(u[5] for u in usage),
            "cost": sum(u[6] or 0 for u in usage), "messages": sum(u[7] for u in usage),
            "priced": sum(u[8] for u in usage), "counter_rows": len(counters),
            "counter_sum": sum(c[4] for c in counters)}


def test_every_page_is_under_one_mib_and_the_pages_add_up_to_the_source(big):
    conn, _ = big
    want = _source_totals(conn)
    assert want["usage_rows"] + want["counter_rows"] >= 150_000
    pages, groups = _pull(conn)
    assert len(pages) > 3 and all(len(p["groups"]) for p in pages)
    keys = [(g["conversation_id"], g["hour"]) for g in groups]
    assert len(keys) == len(set(keys)) == CONVERSATIONS * HOURS
    assert _page_totals(groups) == want
    assert pages[0]["reset"] is False and pages[-1]["complete"] and pages[-1]["next_cursor"] is None


def test_a_small_page_size_still_returns_everything(big):
    conn, _ = big
    pages, groups = _pull(conn, max_bytes=8192)
    assert len(pages) > 100
    assert _page_totals(groups) == _source_totals(conn)


def test_an_air_gapped_projects_rows_are_never_sent(big):
    conn, _ = big
    excluded = frozenset({GAPPED})
    assert conn.execute("SELECT COUNT(*) FROM usage_hour u JOIN dim_project p ON p.id = u.project WHERE p.name = ?",
                        (GAPPED,)).fetchone()[0] > 0
    pages, groups = _pull(conn, exclude_projects=excluded)
    assert not [u for g in groups for u in g["usage"] if u[1] == GAPPED]
    assert not [c for g in groups for c in g["counters"] if c[1] == GAPPED]
    assert not [g for g in groups if g["conversation_id"] in {f"conv-{i:05d}" for i in range(0, CONVERSATIONS, 20)}]
    assert _page_totals(groups) == _source_totals(conn, excluded)
    assert pages[0]["scope_digest"] != rollup.export_rollup(conn, 0)["scope_digest"]


def test_since_rev_returns_only_changed_hours_and_a_dropped_file_is_reported_gone(big):
    conn, sources = big
    full = rollup.export_rollup(conn, 0, max_bytes=rollup.MAX_PAGE_BYTES)
    seen = full["revision"]
    assert rollup.export_rollup(conn, seen)["groups"] == []
    rng = random.Random(11)
    _flush(conn, sources["conv-00001"], PROJECTS[1], [2, 5], rng)
    new_src = _source(conn, "conv-new")
    _flush(conn, new_src, PROJECTS[3], [4], rng)
    conn.commit()
    _, changed = _pull(conn, seen)
    assert {(g["conversation_id"], g["hour"]) for g in changed} == {
        ("conv-00001", BASE + 2 * HOUR), ("conv-00001", BASE + 5 * HOUR), ("conv-new", BASE + 4 * HOUR)}
    one = next(g for g in changed if g["hour"] == BASE + 5 * HOUR)
    stored = conn.execute("SELECT SUM(u.output) FROM usage_hour u JOIN dim_source s ON s.id = u.src "
                          "WHERE s.conversation_id = 'conv-00001' AND u.t = ?", (BASE + 5 * HOUR,)).fetchone()[0]
    assert sum(u[5] for u in one["usage"]) == stored
    now = rollup.export_rollup(conn, 0)["revision"]
    assert now > seen
    write.drop_source(conn, new_src)
    conn.commit()
    _, gone = _pull(conn, now)
    assert [(g["conversation_id"], g["hour"], g["usage"], g["counters"]) for g in gone] == [
        ("conv-new", BASE + 4 * HOUR, [], [])]
    assert rollup.export_rollup(conn, now + 10_000_000)["reset"] is True
    assert rollup.export_rollup(conn, now + 10_000_000)["groups"]


def test_a_database_written_before_this_slice_backfills_and_the_revision_never_goes_back(tmp_path: Path):
    path = tmp_path / "stats.db"
    conn = _fresh(path)
    rng = random.Random(3)
    _flush(conn, _source(conn, "old-a"), PROJECTS[2], [0, 1], rng)
    conn.commit()
    conn.executescript("DROP TABLE rollup_rev; DROP TABLE rollup_meta;")
    assert rollup.export_rollup(conn, 0)["groups"] == [] and not revision.exists(conn)
    revision.ensure(conn)
    conn.commit()
    first = rollup.export_rollup(conn, 0)
    assert {(g["conversation_id"], g["hour"]) for g in first["groups"]} == {("old-a", BASE), ("old-a", BASE + HOUR)}
    _flush(conn, conn.execute("SELECT id FROM dim_source").fetchone()[0], PROJECTS[2], [3], rng)
    conn.commit()
    conn.close()
    again = rollup.export_rollup(sqlite3.connect(path), 0)
    assert again["revision"] > first["revision"] and len(again["groups"]) == 3


def _registry(state_dir: Path, rows: List[Tuple[str, int]], sessions: List[str]) -> None:
    with sqlite3.connect(db_path_for(state_dir)) as db:
        db.execute("CREATE TABLE projects (id INTEGER PRIMARY KEY, root TEXT, raw_path TEXT, display_name TEXT, "
                   "archived_at TEXT, air_gap INTEGER NOT NULL DEFAULT 0)")
        db.executemany("INSERT INTO projects (root, raw_path, display_name, air_gap) VALUES (?, ?, ?, ?)",
                       [(root, root, root.rsplit("/", 1)[-1], flag) for root, flag in rows])
        db.execute("CREATE TABLE sessions (working_dir TEXT)")
        db.executemany("INSERT INTO sessions VALUES (?)", [(s,) for s in sessions])


def test_the_exclusion_set_covers_the_air_gapped_projects_folders_and_fails_closed(tmp_path: Path):
    store = StatsStore(tmp_path)
    store.initialize()
    config.ensure_schema(store)
    page = dict(since_revision=0, until_revision=None, cursor=None, max_bytes=rollup.PAGE_BYTES)
    assert rollup.serve(store, **page) == {"available": False, "reason": "stats_off"}
    config.update_settings(store, enabled=True, revision=config.get_settings(store)["revision"])
    project_groups.forget()
    rollup.forget_index()
    with pytest.raises(peer_air_gap.AirGapUnreadable):
        rollup.allowed_projects(store)
    assert rollup.serve(store, **page) == {"available": False, "reason": "projects_unreadable"}
    _registry(tmp_path, [("/work/secret", 1), ("/work/open", 0)], ["/work/secret/web", "/work/open/web"])
    project_groups.forget()
    rollup.forget_index()
    assert rollup.allowed_projects(store) == frozenset({project_key("/work/open/web")})
    served = rollup.serve(store, **page)
    assert served["available"] is True and served["groups"] == [] and served["complete"] is True


ROLLUP = "/api/v1/federation/pack/rollup"


@pytest.fixture()
def peer(macs, monkeypatch):  # noqa: F811
    acceptor, initiator = macs
    store = StatsStore(acceptor.root)
    store.initialize()
    config.ensure_schema(store)
    config.update_settings(store, enabled=True, revision=config.get_settings(store)["revision"])
    with store.connect() as conn:
        _flush(conn, _source(conn, "route-conv"), PROJECTS[1], [0, 1], random.Random(1))
    monkeypatch.setattr(app.state, "stats_store", store, raising=False)
    project_groups.forget()
    client = _client()
    answer, _ = _pair(acceptor, initiator, client)
    with closing(acceptor.conn()) as conn:
        granted = grants.live_for_peer(conn, initiator.install_id)
        grants.set_scopes(conn, granted.grant_id, tuple(granted.scopes) + ("machine",))
    token = _token(acceptor, initiator, client, answer["grant_id"]).json()["token"]
    yield acceptor, initiator, client, {"Authorization": f"Bearer {token}"}
    link_store.CACHE.replace([])


def test_the_route_serves_a_paired_computer_and_refuses_a_one_way_one(peer):
    acceptor, initiator, client, bearer = peer
    got = client.get(ROLLUP, headers=bearer)
    assert got.status_code == 200, got.text
    body = got.json()
    assert body["available"] is True and body["complete"] is True
    assert [(g["conversation_id"], g["hour"]) for g in body["groups"]] == [("route-conv", BASE), ("route-conv", BASE + HOUR)]
    again = client.get(ROLLUP, params={"since_rev": body["revision"]}, headers=bearer)
    assert again.status_code == 200 and again.json()["groups"] == []
    assert client.get(ROLLUP, params={"cursor": "not-ours"}, headers=bearer).status_code == 422
    assert client.get(ROLLUP).status_code in (401, 403)
    with closing(acceptor.conn()) as conn:
        link_store.set_direction(conn, initiator.install_id, False)
    refused = client.get(ROLLUP, headers=bearer)
    assert refused.status_code == 403 and "groups" not in refused.text
    assert refused.json()["detail"]["code"] == direction.REFUSAL_CODE
    assert not direction.path_allowed(ROLLUP)


def test_the_registered_stats_plugin_exports_through_the_same_function():
    from src.core.pipeline import registry
    assert registry.find("stats").export_rollup is rollup.export_rollup
