
from __future__ import annotations

import asyncio
import re
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.cplugs.host import runtime
from src.cplugs.huddle import lineage, routes as huddle_routes, service
from src.cplugs.huddle.rules import CLAUDE, JOE
from src.cplugs.huddle.swarm_port import TaskManagerSwarmPort
from src.cplugs.sdk.swarm import SwarmError
from tests.python.cplugs.huddle.test_task_manager_agent_lists import BASE, world  # noqa: F401
from tests.python.cplugs.huddle.test_task_manager_lane import synthetic_v37
from tests.python.cplugs.huddle.test_task_manager_mcp import huddle_store, manager  # noqa: F401
from tests.python.cplugs.huddle.test_task_manager_state_rungs import walk
from tests.python.cplugs.owner import turn_on

ROOT = Path(__file__).resolve().parents[4]
HUDDLE = ROOT / "src" / "cplugs" / "huddle"


def moves(store, item_id: int):
    with closing(store._connect(False)) as conn:
        return [(r["from"], r["to"], r["by"], r["detail"]) for r in lineage.for_item(conn, item_id)]


def test_rung_41_adds_an_empty_table_and_changes_no_row(tmp_path):
    path = synthetic_v37(tmp_path)
    walk(path, 40)
    with closing(sqlite3.connect(path)) as conn:
        before = [tuple(r) for r in conn.execute("SELECT * FROM items ORDER BY id")]
    walk(path, 41)
    with closing(sqlite3.connect(path)) as conn:
        assert [tuple(r) for r in conn.execute("SELECT * FROM items ORDER BY id")] == before
        assert conn.execute("SELECT COUNT(*) FROM item_lineage").fetchone()[0] == 0


def test_a_birth_and_every_state_move_is_one_event_and_a_text_edit_is_none(manager):  # noqa: F811
    store = huddle_store(manager)
    item = store.add("all", "work", actor=JOE)
    assert moves(store, item["id"]) == [("", "open", "owner", "born")]
    store.update(item["id"], actor=JOE, text="work, reworded")
    assert len(moves(store, item["id"])) == 1
    store.update(item["id"], actor=CLAUDE, state="review")
    store.post(item["id"], "not quite", actor=JOE)
    store.update(item["id"], actor=JOE, state="todo")
    store.update(item["id"], actor=JOE, approve=True)
    assert [(a, b) for a, b, *_ in moves(store, item["id"])] == [("", "open"), ("open", "review"), ("review", "open"), ("open", "todo"), ("todo", "done")]
    assert {by for _, _, by, _ in moves(store, item["id"])[1:]} <= {"owner", "claude"}


def test_both_sides_of_a_fork_are_recorded(manager):  # noqa: F811
    store = huddle_store(manager)
    parent = store.add("all", "big", actor=JOE)
    made = store.fork(parent["id"], actor=JOE, fork_state="todo", parent_state="waiting")
    assert moves(store, made["fork"]["id"]) == [("", "open", "owner", "born"), ("open", "todo", "owner", "")]
    assert moves(store, parent["id"])[-1][:2] == ("open", "waiting")


def test_a_card_ops_own_by_is_recorded_not_the_sql_actor(vw_world=None):
    from src.cplugs.huddle.cards.flow import CardAct

    assert lineage.decided_by(JOE, CardAct("done", "auto_done")) == "auto_done"
    assert lineage.decided_by(JOE, None) == "owner"


STATE_SET = re.compile(r"UPDATE\s+work_items\s+SET\s(?:(?!\bWHERE\b)[^;])*?\bstate\s*=", re.I | re.S)
INSERT_COLS = re.compile(r"INSERT\s+INTO\s+work_items\s*\(([^)]*)\)", re.I | re.S)
DYNAMIC_SET = re.compile(r"UPDATE\s+work_items\s+SET\s*(?:\{|[\"']\s*\+)", re.I)
KNOWN_WRITERS = {
    "src/cplugs/huddle/store.py": "update and insert announce to flow.on_state_write / lineage.record_birth; _set_optional is an allow-list",
    "src/cplugs/huddle/store_triggers.py": "a one-time reminder unparking a back-burner item announces to flow.on_state_write with lineage detail reminder came due (_unpark_for_reminder)",
    "src/cplugs/huddle/fork.py": "both sides of a fork announce to flow.on_state_write (store.fork)",
    "src/cplugs/huddle/answer_writer.py": "a reply reopening a review announces to flow.on_state_write",
    "src/cplugs/huddle/closure_undo.py": "undo completion announces to flow.on_state_write with its lineage detail (undo completion / undo cancellation)",
    "src/cplugs/huddle/roles/ask.py": "park announces to flow.on_state_write with its lineage detail (stall_park)",
    "src/cplugs/huddle/roles/wait_stuck.py": "the owner's answer to the stuck-wait question announces to flow.on_state_write with its lineage detail (wait_handle, wait_drop, wait_push, wait_until)",
    "src/cplugs/huddle/from_project.py": "dynamic SET of the from-project columns, no state",
    "src/cplugs/huddle/item_owner.py": "dynamic SET of the owner column (triggers), no state",
    "src/cplugs/huddle/cards/flow.py": "flow._set writes only _WRITABLE card columns, no state",
    "src/core/work/import_rows.py": "the list import body (Pack migrate and the crate import) inserts items in their state and records lineage (task_manager_history.import_into)",
}


def _writes_items(text: str) -> bool:
    inserts = INSERT_COLS.findall(text)
    return bool(STATE_SET.search(text) or DYNAMIC_SET.search(text) or any(re.search(r"\bstate\b|\{", cols) for cols in inserts))


def test_only_the_known_files_write_items_state():
    from src.cplugs.huddle import from_project, item_owner, kinds, store as store_mod
    from src.cplugs.huddle.cards import flow

    found = {str(p.relative_to(ROOT)) for top in ("src", "scripts") for p in (ROOT / top).rglob("*.py")
             if (ROOT / "src" / "core" / "work" / "ladder") not in p.parents and _writes_items(p.read_text(encoding="utf-8"))}
    assert found == set(KNOWN_WRITERS), f"unexpected {sorted(found - set(KNOWN_WRITERS))}; gone {sorted(set(KNOWN_WRITERS) - found)}"
    for name in ("store.py", "answer_writer.py"):
        assert "on_state_write" in (HUDDLE / name).read_text()
    assert "on_state_write" in (HUDDLE / "store.py").read_text() and "write_state" in (HUDDLE / "store.py").read_text()
    assert "task_manager_history.import_into" in (ROOT / "src/core/work/import_rows.py").read_text()
    assert "state" not in flow._WRITABLE | store_mod.OPTIONAL_COLUMNS | {item_owner.COLUMN, from_project.ID_FIELD, from_project.NAME_FIELD}
    assert _writes_items("conn.execute(f\"INSERT INTO work_items ({cols}) VALUES (?)\")") and _writes_items("INSERT INTO work_items (list_key, state) VALUES")
    assert _writes_items("conn.execute(f\"UPDATE work_items SET {sets} WHERE id = ?\")") and _writes_items("UPDATE work_items SET text = ?, state = ? WHERE")
    assert not _writes_items("INSERT INTO work_items (list_key, text) VALUES") and not _writes_items("UPDATE work_items SET x = 1 WHERE state = 'open'")


def test_state_can_never_ride_through_the_optional_column_writer(manager):  # noqa: F811
    store = huddle_store(manager)
    item = store.add("all", "work", actor=JOE)
    with pytest.raises(ValueError):
        with closing(store._connect(True)) as conn, conn:
            store._set_optional(conn, item["id"], {"state": "done"})
    assert moves(store, item["id"]) == [("", "open", "owner", "born")]


def test_the_lineage_route_reads_an_items_moves_and_404s_for_none(manager, tmp_path):  # noqa: F811
    app = manager.app
    app.include_router(huddle_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    store = huddle_store(manager)
    item = store.add("all", "work", actor=JOE)
    store.update(item["id"], actor=JOE, state="todo")
    with TestClient(app) as client:
        body = client.get(f"/api/v1/cplugs/huddle/items/{item['id']}/lineage").json()
        assert [(r["from"], r["to"]) for r in body["lineage"]] == [("", "open"), ("open", "todo")] and body["item_id"] == item["id"]
        assert client.get("/api/v1/cplugs/huddle/items/99999/lineage").status_code == 404


def test_system_closes_and_a_refused_tick_rollback_never_read_as_the_owner(world, monkeypatch):  # noqa: F811
    ctx = world.host.context("huddle")
    port = TaskManagerSwarmPort(ctx)

    async def run():
        old = await port.post_card(world.key, "question", "trust?", "trust it", "trust:4:ab")
        await port.close_open_cards(world.key, "trust:")
        info = await port.post_card(world.key, "info", "naming", "naming", "naming:2")
        await port.settle_cards("naming:2", resolve=True)
        refused = await port.post_card(world.key, "question", "import?", "import it", "import:3:cd")
        return old, info, refused

    old, info, refused = asyncio.run(run())
    store = service.store(ctx)
    assert moves(store, old)[-1] == ("open", "done", "carnivore", "superseded")
    assert moves(store, info)[-1] == ("open", "done", "carnivore", "cause_gone")

    real = service.swarm_of(ctx)

    class Refusing:

        def __getattr__(self, name):
            return getattr(real, name)

        async def card_decided(self, *args, **kwargs):
            raise SwarmError("the swarm refused")

    monkeypatch.setattr(service, "swarm_of", lambda ctx: Refusing())
    assert world.client.patch(f"{BASE}/items/{refused}", json={"approved": True}).status_code == 409
    assert moves(store, refused)[-2:] == [("open", "done", "owner", ""), ("done", "open", "carnivore", "swarm_refused")]


def test_the_lineage_route_still_answers_for_a_removed_completed_item(manager):  # noqa: F811
    app = manager.app
    app.include_router(huddle_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    store = huddle_store(manager)
    item = store.add("all", "work", actor=JOE)
    store.update(item["id"], actor=JOE, approve=True)
    assert store.remove_completed("all", actor=JOE)["removed"] == [item["id"]]
    with TestClient(app) as client:
        body = client.get(f"/api/v1/cplugs/huddle/items/{item['id']}/lineage").json()
    assert body["deleted"] is True and [(r["from"], r["to"]) for r in body["lineage"]] == [("", "open"), ("open", "done")]


def test_rung_47_copies_every_lineage_row_into_card_events_keeps_the_table_and_a_card_event_is_not_a_state(tmp_path):
    path = synthetic_v37(tmp_path)
    walk(path, 46)
    with closing(sqlite3.connect(path)) as conn, conn:
        for item, frm, to, by in ((1, "", "open", "owner"), (1, "open", "review", "u-1"), (2, "", "open", "agent:3")):
            conn.execute("INSERT INTO item_lineage (item_id, list_key, at, from_state, to_state, by, detail) VALUES (?, '16', 5, ?, ?, ?, 'x')", (item, frm, to, by))
        conn.execute("INSERT INTO card_events (item_id, list_key, at, kind, from_col, to_col, by) VALUES (1, '16', 1, 'created', '', 'todo', 'owner')")
        before_items = [tuple(r) for r in conn.execute("SELECT * FROM items ORDER BY id")]
    walk(path, 47)
    with closing(sqlite3.connect(path)) as conn:
        assert [tuple(r) for r in conn.execute("SELECT * FROM items ORDER BY id")] == before_items
        assert conn.execute("SELECT COUNT(*) FROM item_lineage").fetchone()[0] == 3
        assert [tuple(r) for r in conn.execute("SELECT item_id, from_col, to_col, by, detail FROM card_events WHERE kind = 'state' ORDER BY id")] == [
            (1, "", "open", "owner", "x"), (1, "open", "review", "u-1", "x"), (2, "", "open", "agent:3", "x")]
        assert conn.execute("SELECT COUNT(*) FROM card_events WHERE kind = 'created'").fetchone()[0] == 1


def test_a_state_move_writes_card_events_not_item_lineage_and_no_swarm_read_sees_it(manager):  # noqa: F811
    from src.cplugs.huddle.cards import reads, state_log

    store = huddle_store(manager)
    item = store.add("all", "work", actor=JOE)["id"]
    store.update(item, actor=CLAUDE, state="review")
    with closing(store._connect(False)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM work_item_lineage WHERE item_id = ?", (item,)).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM work_card_events WHERE item_id = ? AND kind = ?", (item, state_log.KIND)).fetchone()[0] == 2
        assert state_log.KIND not in {e["kind"] for e in reads.events(conn, item)}
        assert state_log.KIND not in {e["kind"] for e in reads.events_window(conn, ["all"], 0, 4e9, 100)["events"]}
