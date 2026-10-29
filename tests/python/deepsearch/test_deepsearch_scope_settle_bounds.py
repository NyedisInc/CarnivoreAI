
from __future__ import annotations

from contextlib import closing
from pathlib import Path

import pytest

from tests.python.deepsearch.helpers import build_world, cq, drain, rec, scan, teardown
from tests.python.deepsearch.helpers import choose_scope
from tests.python.deepsearch.test_deepsearch_scope_and_mirror import live_paths

from src.core.deepsearch import index_scope, scope_reconcile
from src.core.deepsearch.cache import db as cache_db
from src.core.pipeline import contract as C


@pytest.fixture()
def world(tmp_path, monkeypatch):
    built = build_world(tmp_path, monkeypatch)
    scan(built)
    drain(built)
    yield built
    teardown()


def settle(world, **kw) -> int:
    kw.setdefault("sleep", lambda _s: None)
    with closing(cache_db.open_cache(world["state"])) as conn:
        return scope_reconcile.settle(conn, **kw)


def stamps(world) -> set:
    return {r[0] for r in cq(world, "SELECT DISTINCT scope FROM session_search_live")}


def test_a_batch_ends_by_rows_removed_and_the_pass_rests_between_batches(world, monkeypatch):
    monkeypatch.setattr(scope_reconcile, "BATCH_ROWS", 2)
    choose_scope(world["state"], "human")
    rests = []
    assert settle(world, sleep=rests.append) == 4
    assert len(rests) >= 2 and all(r >= 0 for r in rests)
    assert not {str(s) for s in world["subagents"]} & set(live_paths(world))
    assert stamps(world) == {"human"}


def test_the_rest_is_a_share_of_the_batch_time_and_never_longer_than_the_cap(world):
    choose_scope(world["state"], "human")
    ticks = iter(range(0, 10_000, 100))
    rests = []
    settle(world, sleep=rests.append, clock=lambda: float(next(ticks)))
    assert rests and set(rests) == {C.BULK_REST_MAX_SECONDS}


def test_a_second_change_of_the_setting_during_a_batch_is_followed_not_settled_against_the_old_value(world, monkeypatch):
    subs = {str(s) for s in world["subagents"]}
    choose_scope(world["state"], "human")
    real = scope_reconcile._wanted
    state = {"changed": False}

    def wanted_then_the_owner_changes_their_mind(scope, row):
        if not state["changed"]:
            state["changed"] = True
            choose_scope(world["state"], "all")
        return real(scope, row)

    monkeypatch.setattr(scope_reconcile, "_wanted", wanted_then_the_owner_changes_their_mind)
    settle(world)
    assert subs <= set(live_paths(world)) and stamps(world) == {"all"}


def test_a_file_that_is_an_icloud_placeholder_is_not_opened_and_keeps_its_stamp_until_it_is_whole(world, monkeypatch):
    headless = world["main"].parent / "99999999-aaaa-bbbb-cccc-1234567890ab.jsonl"
    headless.write_bytes(rec(0, "an agent started this headless session about narwhalword", entrypoint="sdk-cli"))
    scan(world)
    drain(world)
    other = str(headless)
    assert live_paths(world)[other][1] == 1
    choose_scope(world["state"], "human+subsessions")
    settle(world)
    choose_scope(world["state"], "human")
    opened = []
    real_open = scope_reconcile.in_scope
    monkeypatch.setattr(scope_reconcile, "is_dataless_file", lambda path: Path(path) == headless)
    monkeypatch.setattr(scope_reconcile, "in_scope", lambda scope, spec: opened.append(spec.path) or real_open(scope, spec))
    settle(world)
    assert other not in opened
    assert cq(world, "SELECT scope, rows FROM session_search_live WHERE path = ?", other) == [("human+subsessions", 1)]
    monkeypatch.setattr(scope_reconcile, "is_dataless_file", lambda path: False)
    settle(world)
    assert cq(world, "SELECT scope, rows FROM session_search_live WHERE path = ?", other) == [("human", 0)]


def unreadable_reader():
    raise OSError("config.json cannot be read")


def test_an_unreadable_setting_settles_nothing_and_the_scope_in_force_does_not_widen(world):
    choose_scope(world["state"], "human")
    assert index_scope.read() == "human"
    assert settle(world) == 4
    index_scope.install(unreadable_reader)
    assert index_scope.read() is None
    assert index_scope.current() == "human"
    assert index_scope.file_kinds() == {"conversation"}
    index_scope.install(lambda: {"values": {}})
    assert index_scope.read() == "all"


def test_nothing_is_rewritten_while_the_setting_is_unreadable(world):
    choose_scope(world["state"], "human")
    index_scope.install(unreadable_reader)
    before = cq(world, "SELECT path, scope, rows FROM session_search_live ORDER BY path")
    assert settle(world) == 0
    assert cq(world, "SELECT path, scope, rows FROM session_search_live ORDER BY path") == before
    assert cq(world, "SELECT COUNT(*) FROM plugin_cursors WHERE file_kind = 'subagent'") == [(3,)]
