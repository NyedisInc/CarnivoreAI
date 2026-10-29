
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.cplugs.huddle import board_port
from src.cplugs.huddle.store import TaskManagerStore
from src.cplugs.reviewboard import service, state
from src.cplugs.sdk import CplugSchemaError, ports
from tests.python.cplugs.reviewboard.boards import SIDECAR, make_board
from tests.python.cplugs.reviewboard.harness import BASE, Env, task_manager_on, task_manager_store, make_env

HTML = "<!doctype html><title>bar</title><p>hi</p>"


@pytest.fixture
def env(tmp_path: Path, monkeypatch) -> Env:
    made = make_env(tmp_path)
    task_manager_on(made, monkeypatch)
    yield made
    board_port.unregister()


@pytest.fixture
def client(env: Env):
    env.app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    with TestClient(env.app) as test_client:
        yield test_client


def create(client, item_id: int, name: str) -> str:
    r = client.post(f"{BASE}/boards", json={"slug_name": name, "title": f"board {name}", "task": {"item_id": item_id},
                                             "summary": "first pass", "html": HTML, "viewport": 320})
    assert r.status_code == 200, r.text
    return r.json()["slug"]


def flat_board(env: Env, slug: str, item_id: Optional[int], revised_at: str) -> str:
    raw = copy.deepcopy(SIDECAR)
    raw["board"]["slug"] = slug
    raw["revisions"][0]["created_at"] = revised_at
    raw["rounds"] = []
    raw["task"] = None if item_id is None else {**raw["task"], "item_id": item_id, "computer": None, "list": None}
    make_board(env.root, raw)
    return slug


def listed(client, **query: Any) -> Dict[str, Any]:
    r = client.get(f"{BASE}/boards", params=query)
    assert r.status_code == 200, r.text
    return r.json()


def tick(env: Env, item_id: int) -> None:
    task_manager_store(env).update(item_id, actor="joe", state="done")


def test_a_board_whose_task_is_done_lists_as_closed_with_its_project_and_reopens_with_the_task(env: Env, client):
    store = task_manager_store(env)
    item = store.add("12", "redo the bar", actor="claude", title="bottom bar task")["id"]
    slug = create(client, item, "bar")
    assert listed(client)["boards"][0]["state"] != state.CLOSED and listed(client, state="closed")["boards"] == []

    tick(env, item)
    rows = listed(client, state="closed")["boards"]
    assert [r["slug"] for r in rows] == [slug]
    row = rows[0]
    assert row["state"] == "closed" and row["project"] == "12" and row["task_title"] == "bottom bar task"
    assert row["closed_at"] and row["closed_at"] == row["last_activity"]

    store.update(item, actor="joe", state="open")
    assert listed(client, state="closed")["boards"] == []
    again = listed(client)["boards"][0]
    assert again["state"] != state.CLOSED and "closed_at" not in again and again["project"] == "12"


def test_project_filters_and_every_row_names_its_project(env: Env, client):
    store = task_manager_store(env)
    ours = store.add("12", "ours", actor="claude", title="ours")["id"]
    theirs = store.add("13", "theirs", actor="claude", title="theirs")["id"]
    mine, other = create(client, ours, "ours"), create(client, theirs, "theirs")
    tick(env, ours)
    tick(env, theirs)
    assert {r["slug"]: r["project"] for r in listed(client)["boards"]} == {mine: "12", other: "13"}
    assert [r["slug"] for r in listed(client, state="closed", project="13")["boards"]] == [other]
    assert [r["slug"] for r in listed(client, project="12")["boards"]] == [mine]
    assert listed(client, state="closed", project="99")["boards"] == []


def test_a_flat_board_takes_its_project_from_the_task_list_and_closed_runs_newest_closed_first(env: Env, client):
    store = task_manager_store(env)
    first, second = (store.add("12", f"task {n}", actor="claude", title=f"task {n}")["id"] for n in (1, 2))
    older = flat_board(env, "20261001-older", first, "2026-10-01T10:00:00Z")
    newer = flat_board(env, "20261002-newer", second, "2026-10-05T10:00:00Z")
    tick(env, first)
    tick(env, second)
    rows = listed(client, state="closed", project="12")["boards"]
    assert [(r["slug"], r["closed_at"]) for r in rows] == [(newer, "2026-10-05T10:00:00Z"), (older, "2026-10-01T10:00:00Z")]


def test_an_unlinked_board_or_a_gone_task_is_never_closed(env: Env, client):
    store = task_manager_store(env)
    gone = store.add("12", "will go", actor="claude", title="will go")["id"]
    tick(env, gone)
    store.delete(gone, actor="joe")
    flat_board(env, "20261003-unlinked", None, "2026-10-03T10:00:00Z")
    flat_board(env, "20261004-gone-task", gone, "2026-10-04T10:00:00Z")
    rows = {r["slug"]: r for r in listed(client)["boards"]}
    assert rows["20261003-unlinked"]["state"] == state.YOUR_TURN and rows["20261003-unlinked"]["project"] is None
    assert rows["20261004-gone-task"]["state"] == state.YOUR_TURN
    assert listed(client, state="closed")["boards"] == []


def test_a_board_on_another_computer_never_reads_this_computers_item(env: Env, client, monkeypatch):
    item = task_manager_store(env).add("12", "same id here", actor="claude", title="local")["id"]
    tick(env, item)
    raw = copy.deepcopy(SIDECAR)
    raw["board"]["slug"] = "20261005-elsewhere"
    raw["task"] = {**raw["task"], "item_id": item, "computer": "another-mac"}
    make_board(env.root, raw)
    monkeypatch.setattr(service, "local_computer", lambda: "this-mac")
    assert listed(client, state="closed")["boards"] == []


def test_the_list_reads_every_task_in_one_port_call(env: Env, client, monkeypatch):
    store = task_manager_store(env)
    items = [store.add("12", f"t{n}", actor="claude", title=f"t{n}")["id"] for n in range(3)]
    for n, item in enumerate(items):
        create(client, item, f"b{n}")
        tick(env, item)
    port = ports.get(board_port.NAME)
    calls: List[List[int]] = []
    real = port.items_info

    async def counted(ids):
        calls.append(list(ids))
        return await real(ids)

    async def one_by_one(item_id):
        raise AssertionError("the list must not read tasks one at a time")

    monkeypatch.setattr(port, "items_info", counted)
    monkeypatch.setattr(port, "item_info", one_by_one)
    assert len(listed(client, state="closed")["boards"]) == 3
    assert calls == [sorted(items)]


def test_a_store_that_cannot_be_read_is_a_warning_not_a_silent_open_list(env: Env, client, monkeypatch):
    item = task_manager_store(env).add("12", "t", actor="claude", title="t")["id"]
    create(client, item, "bar")
    tick(env, item)

    async def unread(ids):
        return None

    monkeypatch.setattr(ports.get(board_port.NAME), "items_info", unread)
    answer = listed(client, state="closed")
    assert answer["boards"] == [] and [p["code"] for p in answer["problems"]] == ["tasks_unread"] and answer["clean"] is True


def test_a_bad_state_filter_is_refused(client):
    assert client.get(f"{BASE}/boards", params={"state": "bogus"}).status_code == 422


def test_the_tool_takes_the_same_filters(env: Env, client):
    item = task_manager_store(env).add("12", "t", actor="claude", title="tool task")["id"]
    slug = create(client, item, "bar")
    tick(env, item)
    ok, answer = env.call("task_manager_boards_list", {"state": "closed", "project": "12"})
    assert ok, answer
    assert [(r["slug"], r["task_title"]) for r in answer["boards"]] == [(slug, "tool task")]
    ok, answer = env.call("task_manager_boards_list", {"state": "closed", "project": "13"})
    assert ok and answer["boards"] == []
    ok, text = env.call("task_manager_boards_list", {"state": "bogus"})
    assert not ok and "state" in text


def test_a_task_moved_to_another_project_takes_its_board_along(env: Env, client):
    store = task_manager_store(env)
    item = store.add("12", "redo the bar", actor="claude", title="moved task")["id"]
    slug = create(client, item, "bar")
    store.move(item, "34", actor="joe")
    tick(env, item)
    assert listed(client, state="closed", project="12")["boards"] == []
    assert [(r["slug"], r["project"]) for r in listed(client, state="closed", project="34")["boards"]] == [(slug, "34")]


def test_the_batch_read_is_one_store_query_not_one_item_read_per_task(env: Env, client, monkeypatch):
    store = task_manager_store(env)
    items = [store.add("12", f"t{n}", actor="claude", title=f"t{n}")["id"] for n in range(3)]
    for n, item in enumerate(items):
        create(client, item, f"b{n}")
        tick(env, item)

    def per_item(self, item_id):
        raise AssertionError("items_info must not read each task with its thread and numbers")

    monkeypatch.setattr(TaskManagerStore, "item", per_item)
    rows = listed(client, state="closed")["boards"]
    assert sorted(r["task_title"] for r in rows) == ["t0", "t1", "t2"]


def test_a_task_manager_schema_newer_than_this_build_is_a_warning_not_a_failed_list(env: Env, client, monkeypatch):
    item = task_manager_store(env).add("12", "t", actor="claude", title="t")["id"]
    slug = create(client, item, "bar")
    tick(env, item)

    def newer(self, item_ids):
        raise CplugSchemaError("huddle.db is from a newer build")

    monkeypatch.setattr(TaskManagerStore, "items_by_id", newer)
    answer = listed(client)
    assert [r["slug"] for r in answer["boards"]] == [slug] and answer["boards"][0]["state"] != state.CLOSED
    assert [p["code"] for p in answer["problems"]] == ["tasks_unread"]
