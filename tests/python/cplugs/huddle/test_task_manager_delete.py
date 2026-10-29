
from __future__ import annotations

from src.core.work import tables
from src.core.mcp import tools
from src.cplugs.huddle import blockers, files, lineage
from src.cplugs.huddle.rules import STATE_REQUEST_TOOL
from tests.python.cplugs.huddle.test_task_manager_mcp import call, huddle_store, manager  # noqa: F401


def _live_ids(manager, list_key="12"):
    return [i["id"] for i in huddle_store(manager).list_items(list_key)["items"] if not i.get("deleted")]


def _rows(store, table, item_id):
    from contextlib import closing

    where = "item_id = ? AND kind = 'state'" if table == "item_lineage" else "item_id = ?"
    table = tables.CARD_EVENTS if table == "item_lineage" else tables.PREFIX + table
    with closing(store._connect(False)) as conn:
        return conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}", (item_id,)).fetchone()[0]


def test_there_is_no_delete_tool_on_mcp_under_either_name(manager):  # noqa: F811
    item = huddle_store(manager).add("12", "keep me", actor="claude")
    listed = {d["name"] for d in tools.tool_definitions()}
    for name in ("task_manager_delete", "task_manager_delete"):
        assert not tools.has_tool(name) and name not in listed
    assert item["id"] in _live_ids(manager)


def test_a_batch_delete_op_is_refused_the_same_way(manager):  # noqa: F811
    a = huddle_store(manager).add("12", "a", actor="joe")["id"]
    ok, body = call(manager, "task_manager_batch_run", {"list_id": "12", "ops": [{"op": "delete", "item_id": a}]})
    assert ok and body["applied"] == 0 and body["failed"] == 1 and STATE_REQUEST_TOOL in str(body["results"][0])
    assert _live_ids(manager) == [a]


def test_joes_delete_is_hard_thread_history_blockers_and_folder_go_and_a_tombstone_stays(manager):  # noqa: F811
    store = huddle_store(manager)
    item = store.add("12", "to remove", actor="joe")
    store.post(item["id"], "a note", actor="joe")
    store.post(item["id"], "noted", actor="claude", kind="answer", quote_text="a note")
    store.update(item["id"], actor="claude", state="review")
    store.fork(item["id"], actor="claude", parent_waits=True)
    folder = files.item_dir(store._storage, item["id"])
    folder.mkdir(parents=True)
    (folder / "ab12cd34-a.txt").write_text("x")
    assert _rows(store, "messages", item["id"]) and _rows(store, "item_lineage", item["id"]) and _rows(store, "blockers", item["id"])
    store.delete(item["id"], actor="joe")
    assert [_rows(store, t, item["id"]) for t in ("messages", "item_lineage", "blockers", "write_actors")] == [0, 0, 0, 0]
    assert not folder.exists()
    gone = next(i for i in store.changes(0, "12")["items"] if i["id"] == item["id"])
    assert gone["deleted"] is True
    assert item["id"] not in _live_ids(manager)


def test_remove_completed_hides_and_keeps_the_history(manager):  # noqa: F811
    store = huddle_store(manager)
    item = store.add("12", "finished", actor="joe")
    store.update(item["id"], actor="joe", approve=True)
    assert store.remove_completed("12", actor="joe")["removed"] == [item["id"]]
    assert _rows(store, "item_lineage", item["id"]) == 2
    assert item["id"] not in _live_ids(manager)
