
from __future__ import annotations

import sqlite3
from pathlib import Path

from src.core.mcp import tools
from src.cplugs.huddle import title as titles
from src.cplugs.huddle.store import TaskManagerStore
from src.core.work.ladder import MIGRATIONS, SCHEMA_VERSION
from src.core.work.storage import WorkStorage
from tests.python.cplugs.huddle.test_task_manager_focus import CALLER, add, call, client, setup  # noqa: F401

BASE = "/api/v1/cplugs/huddle"


def test_a_rung_nine_file_gains_the_title_column_and_keeps_its_rows(tmp_path: Path):
    path = tmp_path / "huddle.db"
    with sqlite3.connect(path) as conn:
        for step in MIGRATIONS[:9]:
            conn.executescript(step)
        conn.execute("INSERT INTO items (list_key, text, position, created_by, state, created_at, updated_at, created_seq, "
                     "seq, review_description) VALUES ('all', 'old row', 0, 'joe', 'open', 1, 1, 1, 1, 'look')")
        conn.execute("PRAGMA user_version = 9")
    store = TaskManagerStore(WorkStorage(path.parent), notify=lambda t: None)
    items = store.list_items("all")["items"]
    assert [(i["text"], i["number"], i["review_description"], i["title"]) for i in items] == [("old row", 1, "look", None)]
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION


def test_the_route_round_trips_the_title_bounds_it_and_pushes(client, setup):
    item = add(client, "all", "the long text of what joe asked for")
    assert client.get(f"{BASE}/lists/all").json()["items"][0]["title"] is None
    setup.published.clear()
    answer = client.patch(f"{BASE}/items/{item}", json={"title": "  short summary "})
    assert answer.status_code == 200 and answer.json()["title"] == "short summary"
    assert setup.published == ["cplug.huddle.list:all", "cplug.huddle.cards:all"]
    assert client.get(f"{BASE}/lists/all").json()["items"][0]["title"] == "short summary"
    assert client.patch(f"{BASE}/items/{item}", json={"title": "x" * 121}).status_code == 400
    assert client.patch(f"{BASE}/items/{item}", json={"title": "x" * 120}).json()["title"] == "x" * 120
    assert client.patch(f"{BASE}/items/{item}", json={"note": "n"}).json()["title"] == "x" * 120
    assert client.patch(f"{BASE}/items/{item}", json={"title": ""}).json()["title"] is None
    added = client.post(f"{BASE}/lists/all/items", json={"text": "with a title", "title": "titled"})
    assert added.status_code == 200 and added.json()["title"] == "titled"
    assert client.post(f"{BASE}/lists/all/items", json={"text": "bad", "title": "y" * 121}).status_code == 400


def test_the_mcp_tools_set_a_title_on_any_item_the_owners_included(client, setup):
    manager = setup.manager
    ok, made = call(manager, "task_manager_add", {"list": "all", "text": "built it", "title": "build"})
    assert ok and made["title"] == "build"
    joes = add(client, "all", "joe wrote this long request")
    setup.published.clear()
    ok, titled = call(manager, "task_manager_update", {"item": joes, "title": "joe's request"})
    assert ok and titled["title"] == "joe's request" and titled["text"] == "joe wrote this long request"
    assert setup.published == ["cplug.huddle.list:all", "cplug.huddle.cards:all"]
    ok, text = call(manager, "task_manager_update", {"item": joes, "title": "z" * 121})
    assert not ok and "title" in text
    ok, listed = call(manager, "task_manager_tasks_list", {"list": "all"})
    assert {i["id"]: i.get("title") for i in listed["items"]} == {made["id"]: "build", joes: "joe's request"}
    for name in ("task_manager_add", "task_manager_update"):
        spec = next(d for d in tools.tool_definitions() if d["name"] == name)
        prop = spec["inputSchema"]["properties"][titles.FIELD]
        assert prop["maxLength"] == titles.MAX_TITLE == 120
        assert titles.FIELD not in spec["inputSchema"].get("required", [])
