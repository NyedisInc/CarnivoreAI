
from __future__ import annotations

import sqlite3
from pathlib import Path

from src.core.mcp import tools
from src.cplugs.huddle import item_marker, mcp
from src.cplugs.huddle.store import TaskManagerStore
from src.core.work.ladder import MIGRATIONS, SCHEMA_VERSION, feature_rungs
from src.core.work.storage import WorkStorage
from tests.python.cplugs.huddle.test_task_manager_focus import add, call, client, setup  # noqa: F401

BASE = "/api/v1/cplugs/huddle"


def test_a_rung_21_file_gains_the_marker_column_and_keeps_its_rows(tmp_path: Path):
    path = tmp_path / "huddle.db"
    with sqlite3.connect(path) as conn:
        for step in MIGRATIONS[:21]:
            conn.executescript(step)
        conn.execute("INSERT INTO items (list_key, text, position, created_by, state, created_at, updated_at, created_seq, "
                     "seq) VALUES ('all', 'old row', 0, 'joe', 'open', 1, 1, 1, 1)")
        conn.execute("PRAGMA user_version = 21")
    store = TaskManagerStore(WorkStorage(path.parent), notify=lambda t: None)
    items = store.list_items("all")["items"]
    assert [i["text"] for i in items] == ["old row"] and "marker" not in items[0]
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION


def test_the_marker_set_is_eight_distinct_shapes_and_no_schema_rung_was_added():
    assert len(item_marker.MARKERS) == len(set(item_marker.MARKERS)) == 8
    assert set(item_marker.LEGACY.values()) <= set(item_marker.MARKERS)
    assert item_marker.COLUMN == "flag_color"
    assert feature_rungs.COLUMN_MIGRATION in MIGRATIONS


def test_clean_fields_reads_names_and_old_flag_colors_and_refuses_the_rest():
    assert item_marker.clean_fields(" Star ") == {"flag_color": "star", "flag_reason": None}
    assert item_marker.clean_fields("purple") == {"flag_color": "star", "flag_reason": None}
    assert item_marker.clean_fields("") == {"flag_color": None, "flag_reason": None}
    assert item_marker.clean_fields(None) == {}
    assert item_marker.canonical("orange") is None and item_marker.canonical(7) is None
    assert item_marker.from_args(None, "pink") == "pink" and item_marker.from_args("star", "pink") == "star"
    assert item_marker.wire({"flag_color": "teal"}) == {"marker": "hexagon"} and item_marker.wire({"flag_color": None}) == {}
    assert item_marker.wire({"flag_color": "nonsense"}) == {}


def test_update_sets_replaces_and_clears_one_marker_and_lists_it_only_when_set(client, setup):
    manager = setup.manager
    item = add(client, "all", "decide the thing")
    ok, listed = call(manager, "task_manager_tasks_list", {"list": "all"})
    assert ok and "marker" not in listed["items"][0]
    ok, marked = call(manager, "task_manager_update", {"item": item, "marker": "star"})
    assert ok and marked["marker"] == "star" and "flag_color" not in marked and "flag_reason" not in marked
    ok, listed = call(manager, "task_manager_tasks_list", {"list": "all"})
    assert listed["items"][0]["marker"] == "star"
    ok, replaced = call(manager, "task_manager_update", {"item": item, "marker": "cross"})
    assert ok and replaced["marker"] == "cross"
    ok, cleared = call(manager, "task_manager_update", {"item": item, "marker": ""})
    assert ok and "marker" not in cleared
    assert "marker" not in client.get(f"{BASE}/lists/all").json()["items"][0]


def test_the_deprecated_flag_arguments_still_work_as_a_marker(client, setup):
    manager = setup.manager
    item = add(client, "all", "old caller")
    ok, marked = call(manager, "task_manager_update", {"item": item, "flag_color": "teal", "flag_reason": "ignored"})
    assert ok and marked["marker"] == "hexagon" and "flag_reason" not in marked


def test_an_unknown_marker_is_refused_with_a_clear_error(client, setup):
    manager = setup.manager
    item = add(client, "all", "x")
    for bad in ("orange", "#ff00ff", "blob"):
        ok, text = call(manager, "task_manager_update", {"item": item, "marker": bad})
        assert not ok and "unknown marker" in text and "star" in text


def test_reply_marks_the_item_and_a_bad_marker_posts_nothing(client, setup):
    manager = setup.manager
    item = add(client, "all", "reply here")
    ok, text = call(manager, "task_manager_reply", {"item": item, "text": "fyi", "kind": "info", "marker": "blob"})
    assert not ok
    thread = client.get(f"{BASE}/items/{item}").json()["thread"] if client.get(f"{BASE}/items/{item}").status_code == 200 else []
    assert thread == []
    ok, done = call(manager, "task_manager_reply", {"item": item, "text": "fyi", "kind": "info", "marker": "circle", "lean": False})
    assert ok and done["item"]["marker"] == "circle"


def test_focus_marks_every_focused_row_and_a_batch_op_can_set_and_clear(client, setup):
    manager = setup.manager
    a, b = add(client, "all", "a"), add(client, "all", "b")
    ok, _ = call(manager, "huddle_focus", {"list": "all", "items": [a, b], "marker": "diamond"})
    assert ok
    rows = {i["id"]: i for i in client.get(f"{BASE}/lists/all").json()["items"]}
    assert rows[a]["marker"] == rows[b]["marker"] == "diamond"
    ok, answer = call(manager, "task_manager_batch_run", {"list_id": "all", "ops": [
        {"op": "update", "item_id": a, "marker": ""},
        {"op": "reply", "item_id": b, "text": "more", "kind": "info", "marker": "hexagon"}]})
    assert ok and answer["failed"] == 0
    rows = {i["id"]: i for i in client.get(f"{BASE}/lists/all").json()["items"]}
    assert "marker" not in rows[a] and rows[b]["marker"] == "hexagon"


def test_approving_or_deleting_clears_the_marker_and_an_approved_item_takes_none(client, setup):
    manager = setup.manager
    ticked, deleted = add(client, "all", "tick me"), add(client, "all", "delete me")
    for item in (ticked, deleted):
        assert call(manager, "task_manager_update", {"item": item, "marker": "square"})[0]
    assert client.patch(f"{BASE}/items/{ticked}", json={"approved": True}).status_code == 200
    rows = {i["id"]: i for i in client.get(f"{BASE}/lists/all").json()["items"]}
    assert "marker" not in rows[ticked]
    assert client.patch(f"{BASE}/items/{ticked}", json={"marker": "star"}).status_code == 400
    assert client.delete(f"{BASE}/items/{deleted}").status_code == 200


def test_an_old_flag_row_reads_as_its_marker_on_the_wire(client, setup):
    item = add(client, "all", "legacy")
    assert client.patch(f"{BASE}/items/{item}", json={"flag_color": "lime"}).status_code == 200
    assert client.get(f"{BASE}/lists/all").json()["items"][0]["marker"] == "circle"


def test_a_deleted_item_keeps_no_marker_in_its_tombstone(tmp_path: Path):
    store = TaskManagerStore(WorkStorage(tmp_path), notify=lambda t: None)
    item = store.add("all", "x", actor="claude")["id"]
    assert store.update(item, actor="claude", marker="cross")["marker"] == "cross"
    store.delete(item, actor="joe")
    with sqlite3.connect(store._storage.db_path) as conn:
        assert conn.execute("SELECT flag_color, flag_reason FROM work_items WHERE id = ?", (item,)).fetchone() == (None, None)


def test_the_marker_field_is_optional_on_every_tool_that_takes_it():
    for name in ("task_manager_add", "task_manager_update", "task_manager_reply", "huddle_focus"):
        spec = next(d for d in tools.tool_definitions() if d["name"] == name)
        props = spec["inputSchema"]["properties"]
        assert "marker" in props and "flag_color" not in props and "flag_reason" not in props
        assert not {"marker"} & set(spec["inputSchema"].get("required", []))
        assert set(props["marker"]["enum"]) == {*item_marker.MARKERS, ""}
    assert all(len(spec.description) <= 400 for spec in mcp.TOOLS.values())
