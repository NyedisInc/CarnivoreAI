
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, List

from src.core.pack.migrate import task_manager_side

ITEM_INSERT = ("INSERT INTO work_items (list_key, text, note, position, created_by, state, created_at, updated_at, created_seq, seq) "
               "VALUES (?, ?, ?, ?, 'joe', ?, 1, 1, 1, 1)")


def machine(tmp_path: Path, name: str) -> str:
    folder = tmp_path / name
    folder.mkdir()
    task_manager_side._storage(str(folder)).connect(True).close()
    return str(folder)


def sql(state_dir: str, query: str, args: tuple = ()) -> List[Dict[str, Any]]:
    with closing(task_manager_side._storage(state_dir).connect(True)) as conn, conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute(query, args).fetchall()]


def old_item(item_id: int, **cols: Any) -> Dict[str, Any]:
    return {"id": item_id, "list_key": "16", "text": f"item {item_id}", "note": "", "position": item_id, "created_by": "claude",
            "state": "open", "created_at": 1.0, "updated_at": 1.0, "deleted": 0, "card_origin": "", "swarm_ref": "", "created_key": "",
            **cols}


def test_an_older_manifest_without_a_lane_lands_in_the_lane_its_provenance_gives(tmp_path: Path):
    target = machine(tmp_path, "b")
    items = [old_item(1, card_origin="agent:7"), old_item(2, swarm_ref="thread:3"), old_item(3, created_key="swarm"),
             old_item(4, card_origin="spawn:12", state="done_by_claude"), old_item(5, card_origin="owner"), old_item(6)]
    task_manager_side.import_list(target, "4", {"items": items, "messages": [], "groups": []}, {})
    rows = sql(target, "SELECT text, state, lane FROM work_items ORDER BY id")
    assert [(r["text"], r["lane"]) for r in rows] == [("item 1", "swarm"), ("item 2", "swarm"), ("item 3", "swarm"), ("item 4", "swarm"),
                                                      ("item 5", "task_manager"), ("item 6", "task_manager")]
    assert rows[3]["state"] == "review"


def test_a_manifest_that_carries_a_lane_keeps_it(tmp_path: Path):
    target = machine(tmp_path, "b")
    task_manager_side.import_list(target, "4", {"items": [old_item(1, card_origin="agent:7", lane="task_manager")], "messages": [], "groups": []}, {})
    assert sql(target, "SELECT lane FROM work_items")[0]["lane"] == "task_manager"


def test_the_export_speaks_the_retired_names_and_a_new_build_reads_them_back(tmp_path: Path):
    source, target = machine(tmp_path, "a"), machine(tmp_path, "b")
    for n, (state, note) in enumerate((("done", "read me"), ("done", ""), ("review", ""), ("waiting", ""), ("todo", ""), ("open", ""))):
        sql(source, ITEM_INSERT, ("16", f"item {n}", note, n, state))
    exported = task_manager_side.export_list(source, "16")
    assert [i["state"] for i in exported["items"]] == ["approved_with_note", "approved", "done_by_claude", "waiting_install", "back_burner", "open"]
    assert sql(source, "SELECT state FROM work_items ORDER BY id")[0]["state"] == "done"
    task_manager_side.import_list(target, "4", json.loads(json.dumps(exported)), {})
    assert [r["state"] for r in sql(target, "SELECT state FROM work_items ORDER BY id")] == ["done", "done", "review", "waiting", "todo", "open"]


def test_lineage_blockers_and_the_original_ask_travel_with_the_items_and_undo_removes_them(tmp_path: Path):
    source, target = machine(tmp_path, "a"), machine(tmp_path, "b")
    entry = sql(source, "INSERT INTO work_inbox (list_key, raw_text, author, created_at, status, item_ids) VALUES ('16', 'make dark mode', 'joe', 1, 'filed', '[1]') RETURNING id")[0]["id"]
    sql(source, ITEM_INSERT, ("16", "dark mode", "", 0, "waiting"))
    sql(source, "UPDATE work_items SET inbox_id = ? WHERE id = 1", (entry,))
    for frm, to in (("", "open"), ("open", "review"), ("review", "open"), ("open", "waiting")):
        sql(source, "INSERT INTO work_card_events (item_id, list_key, at, kind, from_col, to_col, by, detail) VALUES (1, '16', 2, 'state', ?, ?, 'owner', '')", (frm, to))
    sql(source, "INSERT INTO work_blockers (item_id, kind, text, created_by, created_at) VALUES (1, 'install', 'needs the app restarted', 'claude', 3)")
    unrelated = sql(target, "INSERT INTO work_inbox (list_key, raw_text, author, created_at, status) VALUES ('99', 'fix the printer', 'joe', 1, 'filed') RETURNING id")[0]["id"]
    assert unrelated == entry

    record = task_manager_side.import_list(target, "4", task_manager_side.export_list(source, "16"), {})
    [new_id] = record["item_ids"]
    [item] = sql(target, "SELECT inbox_id, (SELECT raw_text FROM work_inbox i WHERE i.id = work_items.inbox_id) AS ask FROM work_items WHERE id = ?", (new_id,))
    assert item["ask"] == "make dark mode"
    assert json.loads(sql(target, "SELECT item_ids FROM work_inbox WHERE id = ?", (item["inbox_id"],))[0]["item_ids"]) == [new_id]
    moves = [(r["from_col"], r["to_col"], r["by"], r["detail"]) for r in sql(target, "SELECT * FROM work_card_events WHERE kind = 'state' AND item_id = ? ORDER BY id", (new_id,))]
    assert moves[:4] == [("", "open", "owner", ""), ("open", "review", "owner", ""), ("review", "open", "owner", ""), ("open", "waiting", "owner", "")]
    assert moves[4] == ("waiting", "waiting", "carnivore", "imported")
    assert [(b["kind"], b["cleared_at"]) for b in sql(target, "SELECT * FROM work_blockers WHERE item_id = ?", (new_id,))] == [("install", None)]

    task_manager_side.undo(target, "4", record)
    assert sql(target, "SELECT COUNT(*) AS n FROM work_card_events")[0]["n"] == 0
    assert sql(target, "SELECT COUNT(*) AS n FROM work_blockers")[0]["n"] == 0
    assert [r["raw_text"] for r in sql(target, "SELECT raw_text FROM work_inbox")] == ["fix the printer"]


def test_an_older_manifest_never_links_an_unrelated_entry_and_still_records_the_import(tmp_path: Path):
    target = machine(tmp_path, "b")
    sql(target, "INSERT INTO work_inbox (list_key, raw_text, author, created_at, status) VALUES ('99', 'fix the printer', 'joe', 1, 'filed')")
    record = task_manager_side.import_list(target, "4", {"items": [old_item(1, inbox_id=1, state="waiting_install")], "messages": [], "groups": []}, {})
    [new_id] = record["item_ids"]
    assert sql(target, "SELECT inbox_id FROM work_items WHERE id = ?", (new_id,))[0]["inbox_id"] is None
    assert [(r["from_col"], r["to_col"], r["by"]) for r in sql(target, "SELECT * FROM work_card_events WHERE kind = 'state' AND item_id = ?", (new_id,))] == [
        ("waiting", "waiting", "carnivore")]


def test_an_open_entry_that_travels_lands_final_so_the_target_never_delivers_it(tmp_path: Path):
    source, target = machine(tmp_path, "a"), machine(tmp_path, "b")
    entry = sql(source, "INSERT INTO work_inbox (list_key, raw_text, author, created_at, status) VALUES ('16', 'half filed', 'joe', 1, 'filing') RETURNING id")[0]["id"]
    sql(source, ITEM_INSERT, ("16", "first part", "", 0, "open"))
    sql(source, "UPDATE work_items SET inbox_id = ? WHERE id = 1", (entry,))
    task_manager_side.import_list(target, "4", task_manager_side.export_list(source, "16"), {})
    assert [r["status"] for r in sql(target, "SELECT status FROM work_inbox")] == ["filed"]
