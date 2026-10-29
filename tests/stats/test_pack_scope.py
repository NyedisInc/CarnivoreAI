from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, List, Optional, Tuple

import pytest

from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.federation import peer_hosts
from src.core.pack.rollup_import import store as rollup_store
from src.core.stats import config, pack_scope, project_groups, queries, rollup
from src.core.stats.batch_store import BatchStore
from src.core.stats.plugin import rollup as write
from src.core.stats.plugin import schema, usage_revision
from src.core.stats.plugin.extract import project_key
from src.core.stats.store import StatsStore
from src.models.stats import QueryRequest
from tests.stats import seed

HOUR = 3600
BASE = 1_760_000_000 // HOUR * HOUR
RANGE = {"from": BASE - HOUR, "to": BASE + 12 * HOUR}
STUDIO, MINI = "install-studio", "install-mini"
MOVED_ROOT = "/work/moved"
LOCAL_ONLY = ("conv-local", project_key("/work/local"))


def _iso(ts: int) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(ts, timezone.utc).isoformat().replace("+00:00", "Z")


def _query(metric: str = "total_tokens", scope: str = "pack", **kwargs) -> QueryRequest:
    return QueryRequest.model_validate({
        "metric": metric, "from": _iso(RANGE["from"]), "to": _iso(RANGE["to"]), "operation": "summary",
        "resolution": "hour", "scope": scope, **kwargs})


def _total(store, **kwargs) -> Optional[float]:
    return queries.execute(store, _query(**kwargs))["summary"]["value"]


class Peer:

    def __init__(self, tmp: Path, install_id: str, state: Path) -> None:
        self.install_id, self.state = install_id, state
        self.conn = sqlite3.connect(tmp / f"{install_id}-stats.db")
        self.conn.row_factory = sqlite3.Row
        schema.migrate(self.conn, 0)
        with closing(connect(db_path_for(state))) as app:
            peer_hosts.upsert(app, install_id=install_id, label=install_id.split("-")[1], grant_id="g-" + install_id,
                              fid="f-" + install_id, initiator=False)

    def conversation(self, name: str, project: str, hours: List[int], tokens: int = 10, cost: Optional[int] = 1000) -> None:
        row = self.conn.execute("SELECT id FROM dim_source WHERE conversation_id = ?", (name,)).fetchone()
        if row is None:
            self.conn.execute("INSERT INTO dim_source (path_key, conversation_id, provider, agent_kind) VALUES (?,?,?,?)",
                              (abs(hash((self.install_id, name))) % (2 ** 62), name, "claude", "session"))
            row = self.conn.execute("SELECT id FROM dim_source WHERE conversation_id = ?", (name,)).fetchone()
        batch = write.Batch(row[0])
        for hour in hours:
            t = BASE + hour * HOUR + 120
            batch.add_usage(t, "claude-opus", project, "v1", (tokens, 0, 0, 0), cost, 1)
            batch.add_counter(t, "claude-opus", project, "tool_calls", "Bash", 3)
        batch.flush(self.conn, {})
        self.conn.commit()

    def send(self, now: float = BASE + 20 * HOUR) -> None:
        page = rollup.export_rollup(self.conn, 0)
        with closing(connect(db_path_for(self.state))) as app:
            assert rollup_store.apply_page(app, self.install_id, page["groups"]) == len(page["groups"]) > 0
            assert rollup_store.finish(app, self.install_id, page["revision"], page["scope_digest"], now)


@pytest.fixture
def world(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    store = StatsStore(state)
    store.initialize()
    config.ensure_schema(store)
    assert ensure_db_migrated(state).status == "ok"
    project_groups.forget()
    with store.connect() as db:
        for hour in (1, 2):
            seed.execute(db, "INSERT INTO minute_usage VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (BASE + hour * HOUR + 60, "local", "claude", LOCAL_ONLY[0], LOCAL_ONLY[1], "claude-opus", "session",
                          100, 0, 0, 0, 500, "v1", 1, 1, 0, "ok"))
    yield state, store, tmp_path
    project_groups.forget()


def _place_project(state: Path, root: str, pack_state: str, home: Optional[str] = None, moved_to: Optional[str] = None) -> None:
    with closing(connect(db_path_for(state))) as app:
        app.execute("INSERT INTO projects (root, raw_path, display_name, source, created_at, updated_at, pack_state, "
                    "home_install_id, moved_to_install_id) VALUES (?,?,?,'test','2026-01-01','2026-01-01',?,?,?)",
                    (root, root, "moved", pack_state, home, moved_to))
    project_groups.forget()


def test_pack_adds_the_peers_and_local_scope_does_not(world):
    state, store, tmp = world
    studio = Peer(tmp, STUDIO, state)
    studio.conversation("conv-studio", project_key("/work/studio"), [1, 2, 3], tokens=40)
    studio.send()
    assert _total(store, scope="local") == 200
    assert _total(store) == 200 + 3 * 40
    assert queries.execute(store, _query())["scope"] == "pack"
    assert queries.execute(store, _query(scope="local"))["scope"] == "local"


def test_the_computer_filter_returns_only_that_computers_rows(world):
    state, store, tmp = world
    studio, mini = Peer(tmp, STUDIO, state), Peer(tmp, MINI, state)
    studio.conversation("conv-studio", project_key("/work/studio"), [1, 2, 3], tokens=40)
    mini.conversation("conv-mini", project_key("/work/mini"), [4], tokens=7)
    studio.send()
    mini.send()
    assert _total(store, filters={"host": "local"}) == 200
    assert _total(store, filters={"host": STUDIO}) == 120
    assert _total(store, filters={"host": MINI}) == 7
    assert _total(store) == 200 + 120 + 7
    ranked = queries.execute(store, _query(operation="ranking", group_by="host", top_n=5))["ranking"]
    assert {row["key"]: row["value"] for row in ranked} == {"local": 200, STUDIO: 120, MINI: 7}


def test_a_moved_conversation_counts_once_under_its_owner(world):
    state, store, tmp = world
    with store.connect() as db:
        for hour in (1, 2):
            seed.execute(db, "INSERT INTO minute_usage VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (BASE + hour * HOUR + 60, "local", "claude", "conv-moved", project_key(MOVED_ROOT), "claude-opus",
                          "session", 10, 0, 0, 0, 500, "v1", 1, 1, 0, "ok"))
    studio = Peer(tmp, STUDIO, state)
    studio.conversation("conv-moved", project_key(MOVED_ROOT), [1, 2, 3], tokens=10)
    studio.send()
    assert _total(store) == 200 + 20 + 10
    assert _total(store, filters={"host": STUDIO}) == 10
    assert _total(store, filters={"host": "local"}) == 220
    _place_project(state, MOVED_ROOT, "moved_away", moved_to=STUDIO)
    assert _total(store) == 200 + 30
    assert _total(store, filters={"host": STUDIO}) == 30
    assert _total(store, filters={"host": "local"}) == 200
    assert queries.execute(store, _query())["summary"]["contributing_conversations"] == 2


def test_a_fully_unpriced_hour_is_kept_and_reads_unknown_not_free(world):
    state, store, tmp = world
    studio = Peer(tmp, STUDIO, state)
    studio.conversation("conv-free", project_key("/work/studio"), [5], tokens=9, cost=None)
    studio.send()
    assert _total(store, filters={"host": STUDIO}) == 9
    cost = queries.execute(store, _query("estimated_cost_nano_usd", filters={"host": STUDIO}))
    assert cost["summary"]["value"] is None
    assert cost["coverage"]["unpriced_usage_count"] == 1


def test_counters_and_non_pack_metrics(world):
    state, store, tmp = world
    studio = Peer(tmp, STUDIO, state)
    studio.conversation("conv-studio", project_key("/work/studio"), [1, 2], tokens=5)
    studio.send()
    assert queries.execute(store, _query("tool_calls", filters={"host": STUDIO}))["summary"]["value"] == 6
    working = queries.execute(store, _query("working_seconds"))
    assert working["scope"] == "local"


def test_no_peer_rollups_answers_local(world):
    _state, store, _tmp = world
    assert queries.execute(store, _query())["scope"] == "local"
    assert _total(store) == 200


def test_the_ledger_fingerprint_follows_a_peers_revision(world):
    state, store, tmp = world
    studio = Peer(tmp, STUDIO, state)
    studio.conversation("conv-studio", project_key("/work/studio"), [1], tokens=5)
    studio.send()
    request = _query()

    def fingerprint() -> str:
        view = BatchStore(store)
        try:
            return queries._item_fingerprint(view, request)
        finally:
            view.release()

    first = fingerprint()
    studio.conversation("conv-studio", project_key("/work/studio"), [2], tokens=5)
    studio.send()
    assert fingerprint() != first
    local = _query(scope="local")
    view = BatchStore(store)
    try:
        assert queries._item_fingerprint(view, local) == queries._item_fingerprint(view, local)
    finally:
        view.release()


def test_an_offline_computer_is_labeled_through_its_newest_hour_and_the_stored_answer_is_not_touched(world):
    state, store, tmp = world
    studio = Peer(tmp, STUDIO, state)
    studio.conversation("conv-studio", project_key("/work/studio"), [1, 2, 3], tokens=5)
    studio.send(now=BASE + 30 * HOUR)
    online = pack_scope.computers(store, "mac", {STUDIO: True})
    assert [c["id"] for c in online] == ["local", STUDIO] and all(c["through"] is None for c in online)
    offline = pack_scope.computers(store, "mac", {STUDIO: False})
    assert offline[1]["through"] == _iso(BASE + 4 * HOUR) and offline[1]["label"] == "studio"
    stored = {"ok": True, "result": queries.execute(store, _query())}
    shown = pack_scope.annotate(store, [stored], {STUDIO: False}, "mac")
    assert shown[0]["result"]["pack"]["offline"] == [{"id": STUDIO, "label": "studio", "through": _iso(BASE + 4 * HOUR)}]
    assert "pack" not in stored["result"]
    assert pack_scope.annotate(store, [stored], {STUDIO: True}, "mac")[0]["result"]["pack"]["offline"] == []
    dim = pack_scope.host_dimension(store, "mac", {STUDIO: True})
    assert [(i["filter_value"], i["label"]) for i in dim["items"]] == [("local", "mac"), (STUDIO, "studio")]


def test_ownership_is_kept_across_a_live_activity_tick_and_redone_on_new_usage(world, monkeypatch):
    state, store, tmp = world
    studio = Peer(tmp, STUDIO, state)
    studio.conversation("conv-studio", project_key("/work/studio"), [1, 2], tokens=40)
    studio.send()
    pack_scope._cache.clear()
    runs: List[int] = []
    real = pack_scope._owners
    monkeypatch.setattr(pack_scope, "_owners", lambda *a, **k: (runs.append(1), real(*a, **k))[1])

    def look() -> None:
        view = BatchStore(store)
        try:
            assert pack_scope.ownership(store, view) is not None
        finally:
            view.release()

    look()
    with store.connect() as db:
        db.execute("UPDATE stats_meta SET value=CAST(value AS INTEGER)+1 WHERE key='revision'")
    look()
    assert len(runs) == 1
    with store.connect() as db:
        usage_revision.bump(db)
    look()
    assert len(runs) == 2


def test_a_project_group_change_redoes_the_ownership_while_homes_exist(world, monkeypatch):
    state, store, tmp = world
    studio = Peer(tmp, STUDIO, state)
    studio.conversation("conv-studio", project_key("/work/studio"), [1, 2], tokens=40)
    studio.send()
    _place_project(state, "/work/moved", "moved_away", moved_to=STUDIO)
    pack_scope._cache.clear()
    runs: List[int] = []
    real = pack_scope._owners
    monkeypatch.setattr(pack_scope, "_owners", lambda *a, **k: (runs.append(1), real(*a, **k))[1])

    def look() -> str:
        view = BatchStore(store)
        try:
            return pack_scope.ownership(store, view).signature
        finally:
            view.release()

    first = look()
    assert look() == first and len(runs) == 1
    groups = project_groups.groups_for(store)
    monkeypatch.setattr(project_groups, "groups_for",
                        lambda _store, **_kw: SimpleNamespace(group={**groups.group, "folder-new": "g-new"},
                                                              group_of=groups.group_of))
    assert look() != first and len(runs) == 2
