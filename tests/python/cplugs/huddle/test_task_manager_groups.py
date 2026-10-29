
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from src.core.mcp import tools
from src.cplugs.huddle import service
from src.cplugs.huddle.store import TaskManagerStore
from src.core.work.ladder import MIGRATIONS, SCHEMA_VERSION
from src.core.work.storage import WorkStorage
from tests.python.cplugs.huddle.test_task_manager_focus import add, call, client, setup  # noqa: F401
from tests.python.cplugs.huddle.test_task_manager_sections import set_view

BASE = "/api/v1/cplugs/huddle"


def body(client, key: str = "all") -> dict:
    return client.get(f"{BASE}/lists/{key}").json()


def group(client, key: str, name: str) -> int:
    answer = client.post(f"{BASE}/lists/{key}/groups", json={"name": name})
    assert answer.status_code == 200, answer.text
    return answer.json()["id"]


def screen(client, key: str = "all") -> list[tuple]:
    return [(i["text"], i["group"], i["number"]) for i in body(client, key)["items"]]


def test_a_rung_six_file_gains_groups_and_keeps_its_items_ungrouped(tmp_path: Path):
    path = tmp_path / "huddle.db"
    with sqlite3.connect(path) as conn:
        for step in MIGRATIONS[:6]:
            conn.executescript(step)
        conn.execute("INSERT INTO items (list_key, text, position, created_by, state, created_at, updated_at, created_seq, seq) "
                     "VALUES ('all', 'old row', 0, 'joe', 'open', 1, 1, 1, 1)")
        conn.execute("PRAGMA user_version = 6")
    store = TaskManagerStore(WorkStorage(path.parent), notify=lambda t: None)
    read = store.list_items("all")
    assert read["groups"] == [] and [(i["text"], i["group"], i["number"]) for i in read["items"]] == [("old row", None, 1)]
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert conn.execute("SELECT COUNT(*) FROM item_groups").fetchone()[0] == 0


def test_group_routes_need_auth(setup):
    with TestClient(setup.app) as anonymous:
        for method, path in [("post", f"{BASE}/lists/all/groups"), ("patch", f"{BASE}/groups/1"),
                             ("delete", f"{BASE}/groups/1"), ("post", f"{BASE}/items/1/group")]:
            assert getattr(anonymous, method)(path).status_code in (401, 403), path


def area_view(setup) -> None:
    set_view(SimpleNamespace(app=setup.app), "area")


def test_ungrouped_first_then_each_group_and_numbers_count_across_them(client, setup):
    area_view(setup)
    loose = add(client, "all", "loose")
    auth, ui = group(client, "all", "auth"), group(client, "all", "ui")
    assert client.post(f"{BASE}/lists/all/groups", json={"name": "AUTH"}).json() == {**body(client)["groups"][0], "created": False}
    added = client.post(f"{BASE}/lists/all/items", json={"text": "login", "group": auth}).json()
    client.post(f"{BASE}/lists/all/items", json={"text": "header", "group": ui})
    client.post(f"{BASE}/lists/all/items", json={"text": "token", "group": auth})
    add(client, "all", "loose two")
    assert screen(client) == [("loose", None, 1), ("loose two", None, 2), ("login", auth, 3), ("token", auth, 4),
                              ("header", ui, 5)]
    client.patch(f"{BASE}/items/{added['id']}", json={"approved": True})
    assert [n for _t, _g, n in screen(client)] == [1, 2, None, 3, 4]
    setup.published.clear()
    assert client.patch(f"{BASE}/groups/{ui}", json={"position": 0}).json()["position"] == 0
    assert [t for t, _g, _n in screen(client)] == ["loose", "loose two", "header", "login", "token"]
    assert setup.published == ["cplug.huddle.list:all", "cplug.huddle.cards:all"]
    assert client.patch(f"{BASE}/groups/{auth}", json={"name": "sign in"}).json()["name"] == "sign in"
    assert client.patch(f"{BASE}/groups/{auth}", json={"name": "UI"}).status_code == 400
    other = group(client, "12", "elsewhere")
    assert client.post(f"{BASE}/lists/all/items", json={"text": "x", "group": other}).status_code == 404
    assert client.post(f"{BASE}/items/{loose}/group", json={"group": other}).status_code == 404


def test_a_drag_sets_the_group_and_place_and_the_fold_is_a_view_flag(client, setup):
    a, b, c = add(client, "all", "a"), add(client, "all", "b"), add(client, "all", "c")
    area = group(client, "all", "area")
    revision = body(client)["revision"]
    assert revision > 0
    client.post(f"{BASE}/items/{a}/group", json={"group": area})
    moved = client.post(f"{BASE}/items/{c}/group", json={"group": area, "index": 0})
    assert moved.status_code == 200 and moved.json()["group"] == area
    assert [(t, g) for t, g, _n in screen(client)] == [("b", None), ("c", area), ("a", area)]
    client.post(f"{BASE}/items/{a}/group", json={"group": None, "index": 0})
    assert [(t, g) for t, g, _n in screen(client)] == [("a", None), ("b", None), ("c", area)]
    ids = [i["id"] for i in body(client)["items"]]
    stale = client.post(f"{BASE}/items/{b}/group", json={"group": area, "expected_revision": 999})
    assert stale.status_code == 409
    ordered = client.put(f"{BASE}/lists/all/order", json={"ids": [ids[1], ids[0], ids[2]], "expected_revision": body(client)["revision"]})
    assert ordered.status_code == 200 and [i["text"] for i in ordered.json()["items"]] == ["b", "a", "c"]
    before = body(client)["revision"]
    setup.published.clear()
    assert client.patch(f"{BASE}/groups/{area}", json={"folded": True}).json()["folded"] is True
    assert body(client)["revision"] == before and body(client)["groups"][0]["folded"] is True
    assert setup.published == ["cplug.huddle.list:all", "cplug.huddle.cards:all"]


def test_removing_a_group_ungroups_its_items_and_never_deletes_one(client, setup):
    loose = add(client, "all", "loose")
    area = group(client, "all", "area")
    kept = group(client, "all", "kept")
    one = client.post(f"{BASE}/lists/all/items", json={"text": "one", "group": area}).json()["id"]
    two = client.post(f"{BASE}/lists/all/items", json={"text": "two", "group": area}).json()["id"]
    client.post(f"{BASE}/lists/all/items", json={"text": "three", "group": kept})
    since = body(client)["cursor"]
    removed = client.delete(f"{BASE}/groups/{area}")
    assert removed.status_code == 200 and removed.json() == {"group": area, "list": "all", "ungrouped": [one, two]}
    assert screen(client) == [("loose", None, 1), ("one", None, 2), ("two", None, 3), ("three", kept, 4)]
    assert [g["name"] for g in body(client)["groups"]] == ["kept"]
    changed = client.get(f"{BASE}/changes", params={"since": since}).json()
    assert {i["id"] for i in changed["items"]} >= {one, two}
    assert [(g["id"], g["deleted"]) for g in changed["groups"]] == [(area, True), (kept, False)]
    assert client.delete(f"{BASE}/groups/{area}").status_code == 404
    assert loose in [i["id"] for i in body(client)["items"]]


def test_moving_to_another_list_lands_in_a_group_of_that_list_or_ungrouped(client, setup):
    item = add(client, "all", "carry me")
    there = group(client, "12", "there")
    moved = client.post(f"{BASE}/items/{item}/move", json={"list": "12", "group": there}).json()
    assert moved["list"] == "12" and moved["group"] == there
    back = client.post(f"{BASE}/items/{item}/move", json={"list": "all"}).json()
    assert back["list"] == "all" and back["group"] is None
    here = group(client, "all", "here")
    assert client.post(f"{BASE}/items/{item}/move", json={"list": "all", "group": here}).json()["group"] == here


def test_claude_files_items_by_area_through_the_mcp_tools(client, setup):
    manifest = json.loads((Path(service.__file__).parent / "cplug.json").read_text())
    names = {d["name"] for d in tools.tool_definitions()}
    for tool in ("task_manager_group_create", "task_manager_group_update"):
        assert tool in manifest["surfaces"]["mcp_tools"] and tool in names
    add_def = next(d for d in tools.tool_definitions() if d["name"] == "task_manager_add")
    assert "group" in add_def["inputSchema"]["properties"] and "area" in add_def["description"]
    ok, made = call(setup.manager, "task_manager_group_create", {"list": "all", "name": "build"})
    assert ok and made["created"] is True
    ok, again = call(setup.manager, "task_manager_group_create", {"list": "all", "name": "Build"})
    assert ok and again == {**made, "created": False}
    ok, added = call(setup.manager, "task_manager_add", {"list": "all", "text": "fix the bundle", "group": made["id"]})
    assert ok and added["group"] == made["id"]
    ok, named = call(setup.manager, "task_manager_add", {"list": "all", "text": "sidebar padding", "group": "sidebar"})
    assert ok and named["group"] not in (None, made["id"])
    loose = add(client, "all", "loose")
    ok, filed = call(setup.manager, "task_manager_move", {"item": loose, "group": "sidebar"})
    assert ok and filed["group"] == named["group"] and filed["list"] == "all"
    ok, listed = call(setup.manager, "task_manager_tasks_list", {"list": "all", "fields": ["text"]})
    assert ok and [g["name"] for g in listed["groups"]] == ["build", "sidebar"]
    assert [(i["text"], i["group"]) for i in listed["items"]] == [
        ("fix the bundle", made["id"]), ("sidebar padding", named["group"]), ("loose", named["group"])]
    ok, renamed = call(setup.manager, "task_manager_group_update", {"group": made["id"], "name": "bundle", "position": 1})
    assert ok and renamed["name"] == "bundle" and renamed["position"] == 1
    ok, gone = call(setup.manager, "task_manager_group_update", {"group": named["group"], "remove": True})
    assert ok and sorted(gone["ungrouped"]) == sorted([named["id"], loose])
    ok, changes = call(setup.manager, "task_manager_changes", {"since": 0, "list": "all"})
    assert ok and {g["name"] for g in changes["groups"]} == {"bundle", "sidebar"}
    ok, refused = call(setup.manager, "task_manager_group_update", {"group": made["id"], "folded": True})
    assert not ok
