
from __future__ import annotations

import threading
from contextlib import closing
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.python.deepsearch.helpers import SUBAGENT_WORDS, build_world, choose_scope, cq, drain, go_ready, rec, scan, teardown
from tests.python.transcript_source.helpers import CONV, FOLDER

from src.api.auth import require_auth  # noqa: E402
from src.core.deepsearch import grouped, index_scope, status  # noqa: E402
from src.core.deepsearch.cache import db as cache_db  # noqa: E402


@pytest.fixture()
def world(tmp_path, monkeypatch):
    built = build_world(tmp_path, monkeypatch)
    yield built
    teardown()


def hits(world, word: str) -> dict:
    go_ready(world)
    with closing(cache_db.reader(world["state"])) as conn:
        return grouped.search_grouped(conn, world["state"], word, overrides={})


def live_paths(world) -> dict:
    return {p: (kind, rows) for p, kind, rows in cq(world, "SELECT path, file_kind, rows FROM session_search_live")}


def cursor_paths(world) -> set:
    return {r[0] for r in cq(world, "SELECT path FROM plugin_cursors")}


def test_deleting_one_copy_of_a_conversation_drops_that_paths_rows_and_keeps_the_other_copys(world):
    copy = world["corpus"] / f"{FOLDER}-copy" / f"{CONV}.jsonl"
    copy.parent.mkdir(parents=True)
    copy.write_bytes(world["main"].read_bytes() + rec(7, "only the copy knows pangolincopy"))
    scan(world)
    drain(world)
    main, other = str(world["main"]), str(copy)
    assert {main, other} <= set(live_paths(world)) and {main, other} <= cursor_paths(world)
    assert hits(world, "pangolincopy")["total_conversations"] == 1
    kept_rows = live_paths(world)[main][1]
    copy.unlink()
    scan(world)
    drain(world)
    paths = live_paths(world)
    assert other not in paths and other not in cursor_paths(world)
    assert paths[main][1] == kept_rows > 0 and main in cursor_paths(world)
    assert hits(world, "pangolincopy")["total_conversations"] == 0
    answer = hits(world, "wombatmain")
    assert answer["total_conversations"] == 1 and answer["stale"] == []
    assert len([p for p in paths if p in {str(s) for s in world["subagents"]}]) == 3


def test_a_gone_main_does_not_take_its_live_subagent_files_with_it(world):
    scan(world)
    drain(world)
    world["main"].unlink()
    scan(world)
    drain(world)
    paths = live_paths(world)
    assert str(world["main"]) not in paths
    assert {str(s) for s in world["subagents"]} <= set(paths)
    assert hits(world, SUBAGENT_WORDS[0])["total_conversations"] == 1


def test_changing_the_scope_indexes_subagent_files_and_changing_it_back_removes_their_rows(world):
    subs = {str(s) for s in world["subagents"]}
    choose_scope(world["state"], "human")
    scan(world)
    drain(world)
    assert not subs & set(live_paths(world)) and not subs & cursor_paths(world)
    assert hits(world, SUBAGENT_WORDS[0])["total_conversations"] == 0
    main_id = cq(world, "SELECT id FROM session_search_live WHERE path = ?", str(world["main"]))
    choose_scope(world["state"], "all")
    drain(world)
    assert subs <= set(live_paths(world)) and subs <= cursor_paths(world)
    for word in SUBAGENT_WORDS:
        assert hits(world, word)["total_conversations"] == 1, word
    assert cq(world, "SELECT id FROM session_search_live WHERE path = ?", str(world["main"])) == main_id
    assert {r[0] for r in cq(world, "SELECT DISTINCT scope FROM session_search_live")} == {"all"}
    choose_scope(world["state"], "human")
    drain(world)
    assert not subs & set(live_paths(world)) and not subs & cursor_paths(world)
    for word in SUBAGENT_WORDS:
        assert hits(world, word)["total_conversations"] == 0, word
    assert hits(world, "wombatmain")["total_conversations"] == 1
    assert cq(world, "SELECT COUNT(*) FROM session_search_rows WHERE live_id NOT IN (SELECT id FROM session_search_live)")[0][0] == 0
    choose_scope(world["state"], "all")
    drain(world)
    assert subs <= set(live_paths(world)) and hits(world, SUBAGENT_WORDS[2])["total_conversations"] == 1


def test_headless_sessions_follow_the_middle_choice_in_both_directions(world):
    headless = world["main"].parent / "99999999-aaaa-bbbb-cccc-1234567890ab.jsonl"
    headless.write_bytes(rec(0, "an agent started this headless session about narwhalword", entrypoint="sdk-cli"))
    other = str(headless)
    choose_scope(world["state"], "human")
    scan(world)
    drain(world)
    assert live_paths(world)[other] == ("conversation", 0)
    assert hits(world, "narwhalword")["total_conversations"] == 0
    choose_scope(world["state"], "human+subsessions")
    drain(world)
    assert live_paths(world)[other][1] == 1 and hits(world, "narwhalword")["total_conversations"] == 1
    choose_scope(world["state"], "human")
    drain(world)
    assert live_paths(world)[other] == ("conversation", 0) and hits(world, "narwhalword")["total_conversations"] == 0
    assert hits(world, "wombatmain")["total_conversations"] == 1


def test_the_status_names_the_scope_instead_of_a_bare_zero_for_subagents(world):
    scan(world)
    choose_scope(world["state"], "human")
    drain(world)
    narrowed = status.index_status(world["state"])
    assert narrowed["scope"] == "human" and narrowed["coverage"]["subagent"] == {"files": None, "indexed": None}
    choose_scope(world["state"], "all")
    drain(world)
    widened = status.index_status(world["state"])
    assert widened["scope"] == "all" and widened["coverage"]["subagent"] == {"files": 3, "indexed": 3}


def test_an_unusable_stored_scope_reads_as_the_default(world, monkeypatch):
    choose_scope(world["state"], "everything and then some")
    assert index_scope.current() == "all"
    assert index_scope.file_kinds() == {"conversation", "subagent"}


@pytest.fixture()
def api(tmp_path, monkeypatch):
    from src.api import deepsearch_routes
    from src.core.ui_preferences_store import UiPreferencesStore

    config = tmp_path / "config.json"
    config.write_text("{}")
    store = UiPreferencesStore(lambda: config)
    index_scope.install(store.read)
    app = FastAPI()
    app.state.ui_preferences_store = store
    app.include_router(deepsearch_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    yield app, store
    index_scope.uninstall()


def test_the_index_scope_setting_round_trips_through_its_route_and_wakes_the_pipeline(api, monkeypatch):
    from src.core.pipeline import runtime as pipeline_runtime

    app, store = api
    rescans = []
    monkeypatch.setattr(pipeline_runtime, "current", lambda: SimpleNamespace(rescan=lambda: rescans.append(1)))
    with TestClient(app) as client:
        first = client.get("/api/v1/deepsearch/settings").json()
        assert first == {"indexScope": "all", "scopes": ["human", "human+subsessions", "all"]}
        saved = client.put("/api/v1/deepsearch/settings", json={"indexScope": "human"})
        assert saved.status_code == 200 and saved.json()["indexScope"] == "human"
        assert client.get("/api/v1/deepsearch/settings").json()["indexScope"] == "human"
        assert store.read()["values"]["deepsearch_index_scope"] == "human"
        assert index_scope.current() == "human" and index_scope.file_kinds() == {"conversation"}
        assert rescans == [1]
        for refused in ("nonsense", "ALL", 3, None):
            bad = client.put("/api/v1/deepsearch/settings", json={"indexScope": refused})
            assert bad.status_code == 422, refused
        assert client.put("/api/v1/deepsearch/settings", json={"indexScope": "human", "extra": 1}).status_code == 422
        assert index_scope.current() == "human" and rescans == [1]
        assert client.put("/api/v1/deepsearch/settings", json={"indexScope": "human"}).status_code == 200
        assert rescans == [1]
        for value in ("human+subsessions", "all"):
            ok = client.put("/api/v1/deepsearch/settings", json={"indexScope": value})
            assert ok.status_code == 200 and index_scope.current() == value
    assert len(rescans) == 3


def test_a_failing_pipeline_wake_never_undoes_the_save(api, monkeypatch):
    from src.core.pipeline import runtime as pipeline_runtime

    def broken():
        raise RuntimeError("engine gone")

    app, _store = api
    monkeypatch.setattr(pipeline_runtime, "current", lambda: SimpleNamespace(rescan=broken))
    with TestClient(app) as client:
        saved = client.put("/api/v1/deepsearch/settings", json={"indexScope": "human"})
        assert saved.status_code == 200 and index_scope.current() == "human"


def test_an_unwritable_config_answers_500_and_changes_nothing(api, tmp_path):
    app, _store = api
    (tmp_path / "config.json").rename(tmp_path / "gone.json")
    with TestClient(app) as client:
        refused = client.put("/api/v1/deepsearch/settings", json={"indexScope": "human"})
        assert refused.status_code == 500 and refused.json()["detail"]["code"] == "deepsearch_settings_unwritable"
        assert client.get("/api/v1/deepsearch/settings").json()["indexScope"] == "all"


def test_a_rescan_marks_the_files_a_widened_scope_now_takes(world):
    from src.core.pipeline.engine import Engine
    from src.core.pipeline.registry import plugins as pipeline_plugins
    from src.core.deepsearch.pipeline_plugin import DEEPSEARCH

    scan(world)
    choose_scope(world["state"], "human")
    drain(world)
    choose_scope(world["state"], "all")
    engine = Engine(world["state"], db_path=world["db"], plugins=pipeline_plugins([DEEPSEARCH]))
    assert engine.dirty.size() == 0
    engine.rescan()
    for thread in [t for t in threading.enumerate() if t.name == "pipeline-rescan"]:
        thread.join(10)
    assert engine.dirty.size() == 3
