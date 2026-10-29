
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional

from src.core import config_writer
from src.core.crate_import import entries_in
from src.core.crate_import.idmap import IdMap
from src.core.crate_import.model import Collector, ImportRequest
from src.core.db import connect, db_path_for, set_meta
from src.core.exports.store import crate_written_key
from src.core.project_move.paths import PathMapping
from src.core.stats.plugin.extract import project_key
from src.cplugs.crate.handle import JobHandle
from src.cplugs.crate.plan import build_plan as build_export_plan
from src.cplugs.crate.writer import run_export
from src.cplugs.sdk import crate_format as cf
from tests.python.cplugs.crate.crate_world import env_for, make_world, project_request
from tests.python.crate_import.install import INSTALL_ID, Install, make_install
from tests.python.crate_import.test_import_same_path import rows_of, run
from tests.python.inventory import schemas
from tests.python.inventory.world import UUID_A
from tests.python.session_purge.purge_world import insert

ITEM = dict(text="local", position=1, created_by="joe", state="open", created_at=1.0, updated_at=1.0, created_seq=1, seq=1)
FILE_ID = "abcd1234"


BOARD_CARD = json.dumps({"board": {"slug": "20261019-crate-carry-test", "revision": "r1", "title": "Crate carry test board"}})


def export_world(tmp: Path, *, extra_messages: bool = False) -> SimpleNamespace:
    (tmp / "w").mkdir()
    world = make_world(tmp / "w")
    parts = json.dumps({"files": [{"id": FILE_ID, "name": "x.html", "mime": "text/html", "size": 15, "path": f"files/{world.item_a}/x.html"}]})
    with closing(sqlite3.connect(world.main)) as conn:
        conn.execute("UPDATE work_messages SET parts = ? WHERE item_id = ?", (parts, world.item_a))
        if extra_messages:
            for text, card in (("written from another project", ""), ("Crate carry test board r1", BOARD_CARD)):
                conn.execute("INSERT INTO work_messages (item_id, author, kind, text, created_at, seq, author_key, parts) "
                             "VALUES (?, 'claude', 'info', ?, 1.0, 9000 + (SELECT COUNT(*) FROM work_messages), 'system', ?)", (world.item_p, text, card))
        conn.execute("UPDATE work_items SET text = 'item ' || id, created_at = 100.0 + id")
        conn.execute("UPDATE crosstalk_messages SET status = 'queued' WHERE id = 'm-1'")
        conn.execute("UPDATE work_inbox SET status = 'queued', item_ids = ? WHERE list_key = ?", (json.dumps([world.item_a]), str(world.p1)))
        conn.execute("UPDATE work_items SET inbox_id = (SELECT id FROM work_inbox WHERE list_key = ?) WHERE id = ?", (str(world.p1), world.item_a))
        conn.commit()
    with closing(sqlite3.connect(world.side["automations.db"])) as conn:
        conn.execute("UPDATE automations SET next_fire_at = 5000.0, enabled = 1")
        conn.commit()
    env = env_for(world)
    plan = build_export_plan(env, project_request(world))
    assert plan.ok, plan.blockers
    result = run_export(env, plan, JobHandle("s5"))
    with cf.open_crate(result.path) as reader:
        install_id = reader.manifest.source["install_id"]
    return SimpleNamespace(world=world, path=result.path, sha256=result.sha256, install_id=install_id, bundle_id=result.bundle_id)


def target_install(tmp: Path, crate: SimpleNamespace, *, shift: int = 1, attach: bool = False, local_items: int = 0) -> Install:
    (tmp / "t").mkdir(exist_ok=True)
    install = make_install(tmp / "t", install_id=crate.install_id)
    schemas.build_side(install.state)
    config = tmp / "t" / "config.json"
    config.write_text("{}")
    with closing(install.db()) as conn:
        set_meta(conn, crate_written_key(crate.bundle_id), crate.sha256)
        for n in range(shift):
            root = crate.world.root1 if attach and n == shift - 1 else str(install.projects / f"other-{n}")
            insert(conn, "projects", uid=f"other-uid-{n}", display_name=f"Other {n}", root=root, raw_path=root, source="user",
                   created_at="now", updated_at="now")
        project_id = shift
        for n in range(local_items):
            insert(conn, "work_items", list_key=str(project_id), **{**ITEM, "text": f"local {n}", "created_at": 1.0 + n})
        insert(conn, "work_items", list_key="other", **ITEM)
        conn.commit()
    return Install(replace(install.env, config_path=config), install.state, install.projects, install.claude, install.codex)


def imported(tmp: Path, **kw: Any) -> tuple:
    crate = export_world(tmp)
    install = target_install(tmp, crate, **kw)
    return crate, install, run(crate, install)


def items(install: Install) -> List[sqlite3.Row]:
    return rows_of(install, "SELECT * FROM work_items WHERE deleted = 0 ORDER BY id")


def test_items_land_under_the_new_list_key(tmp_path: Path) -> None:
    crate, install, receipt = imported(tmp_path)
    assert receipt.state in ("done", "done_with_warnings"), receipt.warnings
    new_project = rows_of(install, "SELECT id FROM projects WHERE uid = 'project-uid-1'")[0]["id"]
    assert new_project != crate.world.p1
    by_list = {}
    for row in items(install):
        by_list.setdefault(row["list_key"], []).append(row["text"])
    assert len(by_list[str(new_project)]) == 3 and str(crate.world.p1) not in by_list or str(crate.world.p1) == str(new_project)
    assert len(by_list.get("all", [])) == 1 and by_list["other"] == ["local"]
    assert rows_of(install, "SELECT tagged_session_key FROM work_items WHERE list_key = 'all'")[0][0] == UUID_A
    assert rows_of(install, "SELECT COUNT(*) FROM work_blockers")[0][0] == 1
    assert rows_of(install, "SELECT COUNT(*) FROM work_card_events WHERE kind = 'state'")[0][0] >= 3
    inbox = rows_of(install, "SELECT * FROM work_inbox")
    assert [r["status"] for r in inbox] == ["filed"] and inbox[0]["list_key"] == str(new_project)
    linked = rows_of(install, "SELECT inbox_id FROM work_items WHERE inbox_id IS NOT NULL")
    assert len(linked) == 1 and linked[0][0] == inbox[0]["id"]


def test_a_messages_file_path_follows_the_new_item_id(tmp_path: Path) -> None:
    crate, install, receipt = imported(tmp_path)
    message = rows_of(install, "SELECT m.parts, m.item_id FROM work_messages m WHERE m.parts LIKE '%x.html%'")[0]
    new_item = message["item_id"]
    assert new_item != crate.world.item_a
    assert json.loads(message["parts"])["files"][0]["path"] == f"files/{new_item}/x.html"
    placed = install.state / "cplugs" / "huddle" / "files" / str(new_item) / "x.html"
    assert placed.read_text() == "<p>artifact</p>"
    assert not (install.state / "cplugs" / "huddle" / "files" / str(crate.world.item_a)).exists() or new_item == crate.world.item_a
    assert receipt.task_files["written"] == 3 - receipt.task_files["no_item"] and receipt.task_files["failed"] == []


def test_nothing_is_due_after_the_import(tmp_path: Path) -> None:
    crate, install, receipt = imported(tmp_path)
    assert rows_of(install, "SELECT COUNT(*) FROM work_item_triggers")[0][0] >= 1
    assert rows_of(install, "SELECT COUNT(*) FROM work_item_triggers WHERE paused = 0 AND fire_at IS NOT NULL AND fired_at IS NULL")[0][0] == 0
    assert rows_of(install, "SELECT COUNT(*) FROM work_item_nudges WHERE count != 0 OR stalled_at IS NOT NULL")[0][0] == 0
    assert rows_of(install, "SELECT COUNT(*) FROM work_inbox WHERE status IN ('queued', 'filing')")[0][0] == 0
    assert rows_of(install, "SELECT COUNT(*) FROM work_held_sends")[0][0] == 0 and rows_of(install, "SELECT COUNT(*) FROM work_card_deals")[0][0] == 0
    assert rows_of(install, "SELECT COUNT(*) FROM crosstalk_messages WHERE status IN ('queued', 'held', 'delivering')")[0][0] == 0
    assert rows_of(install, "SELECT status FROM crosstalk_messages WHERE id = 'm-1'")[0][0] == "expired"
    with closing(sqlite3.connect(install.state / "automations" / "automations.db")) as conn:
        rows = conn.execute("SELECT automation_id, enabled, next_fire_at, seed_key FROM automations").fetchall()
        assert len(rows) >= 3 and all(r[1] == 0 and r[2] is None for r in rows)
        assert conn.execute("SELECT COUNT(*) FROM runs WHERE status IN ('claimed', 'running', 'waiting_on_you')").fetchone()[0] == 0
    assert "automation_disabled" in {w["code"] for w in receipt.warnings}


def test_the_side_databases_follow_the_ids(tmp_path: Path) -> None:
    crate, install, receipt = imported(tmp_path)
    with closing(sqlite3.connect(install.state / "bookmarks.db")) as conn:
        assert conn.execute("SELECT session_uuid FROM bookmarks").fetchall() == [(UUID_A,)]
        row_id = conn.execute("SELECT session_row_id FROM bookmarks").fetchone()[0]
    assert rows_of(install, "SELECT session_uuid FROM sessions WHERE id = ?", row_id)[0][0] == UUID_A
    with closing(sqlite3.connect(install.state / "attention_history.db")) as conn:
        assert conn.execute("SELECT COUNT(*) FROM attention_events").fetchone()[0] == 1
    with closing(sqlite3.connect(install.state / "pipeline-plugins" / "stats.db")) as conn:
        scope = json.loads(conn.execute("SELECT scope_json FROM stats_annotations WHERE id = 'ann-Proj One'").fetchone()[0])
    assert scope["project"] == project_key(crate.world.root1)
    assert receipt.rows["bookmarks.db.bookmarks"]["inserted"] == 1 and receipt.rows["automations.db.automations"]["inserted"] >= 3


def test_the_drawer_arrangement_is_rekeyed_through_the_writer(tmp_path: Path) -> None:
    crate, install, receipt = imported(tmp_path)
    project = rows_of(install, "SELECT id FROM projects WHERE uid = 'project-uid-1'")[0]["id"]
    company = rows_of(install, "SELECT id FROM companies WHERE uid = 'company-uid-1'")[0]["id"]
    config = config_writer.read_config(install.env.config_path)
    drawer = config["ui_preferences"]["values"]["drawer_arrangement"]
    assert f"p:{project}" in drawer["collapsed"] and f"c:{company}" in drawer["collapsed"]
    assert f"p:{project}" in drawer["mobile"]["collapsed"] and UUID_A in drawer["pinned"] and UUID_A in drawer["order"]
    assert config["session_account_pins"] == {UUID_A: "work"}
    assert receipt.entries["drawer_members"] >= 5 and receipt.entries["pins"] == 1
    assert {"entry:pinned_themes.json", "entry:terminal_layouts"} <= {n["what"] for n in receipt.not_restored}


def test_a_second_run_writes_nothing(tmp_path: Path) -> None:
    crate, install, first = imported(tmp_path)
    before = (items(install), rows_of(install, "SELECT COUNT(*) FROM work_messages")[0][0], config_writer.read_config(install.env.config_path))
    second = run(crate, install)
    assert second.state == "noop"
    after = (items(install), rows_of(install, "SELECT COUNT(*) FROM work_messages")[0][0], config_writer.read_config(install.env.config_path))
    assert [dict(r) for r in after[0]] == [dict(r) for r in before[0]] and after[1:] == before[1:]


def test_a_list_that_has_items_gets_a_restored_group(tmp_path: Path) -> None:
    crate = export_world(tmp_path)
    install = target_install(tmp_path, crate, shift=2, attach=True, local_items=2)
    already = rows_of(install, "SELECT id FROM projects WHERE root = ?", crate.world.root1)[0]["id"]
    with closing(sqlite3.connect(crate.world.main)) as conn:
        first = conn.execute("SELECT created_at, text FROM work_items WHERE id = ?", (crate.world.item_p,)).fetchone()
    with closing(install.db()) as conn:
        insert(conn, "work_items", list_key=str(already), **{**ITEM, "created_at": first[0], "text": first[1]})
        conn.commit()
    receipt = run(crate, install)
    assert receipt.state in ("done", "done_with_warnings"), receipt.warnings
    groups = [g for g in rows_of(install, "SELECT id, name, list_key FROM work_item_groups") if g["name"].startswith("restored from ")]
    assert len(groups) == 1 and groups[0]["list_key"] == str(already)
    mine = [r for r in items(install) if r["list_key"] == str(already)]
    assert len(mine) == 2 + 1 + 2
    assert sorted(r["text"] for r in mine if r["group_id"] == groups[0]["id"]) == [f"item {crate.world.item_a}", f"item {crate.world.item_b}"]
    assert all(r["group_id"] is None for r in mine if r["text"].startswith("local") or r["text"] == f"item {crate.world.item_p}")
    assert receipt.rows["cloude.db.work_items"]["present"] == 1


def test_a_relocated_import_rebases_the_automation_folder_and_the_stats_key(tmp_path: Path) -> None:
    crate = export_world(tmp_path)
    install = target_install(tmp_path, crate)
    new = str((install.projects / "moved").resolve())
    receipt = run(crate, install, request=ImportRequest(mode="relocate", new_root=new))
    assert receipt.state in ("done", "done_with_warnings"), receipt.warnings
    with closing(sqlite3.connect(install.state / "automations" / "automations.db")) as conn:
        folders = [json.loads(r[0]).get("folder") for r in conn.execute("SELECT target FROM automations")]
    assert new in folders and crate.world.root1 not in folders
    with closing(sqlite3.connect(install.state / "pipeline-plugins" / "stats.db")) as conn:
        scope = json.loads(conn.execute("SELECT scope_json FROM stats_annotations WHERE id = 'ann-Proj One'").fetchone()[0])
    assert scope["project"] == project_key(new) != project_key(crate.world.root1)


def test_a_relocated_import_keeps_a_blank_parts_and_a_board_card_in_a_project_that_exists(tmp_path: Path) -> None:
    crate = export_world(tmp_path, extra_messages=True)
    install = target_install(tmp_path, crate, attach=True)
    new = str((install.projects / "moved").resolve())
    receipt = run(crate, install, request=ImportRequest(mode="relocate", new_root=new))
    assert receipt.state in ("done", "done_with_warnings"), receipt.warnings
    parts = [r["parts"] for r in rows_of(install, "SELECT parts FROM work_messages WHERE text IN ('written from another project', 'Crate carry test board r1')")]
    assert sorted(parts) == sorted(["", BOARD_CARD]) and None not in parts


def test_a_theme_dotfile_is_written_only_where_there_is_none(tmp_path: Path) -> None:
    mapping = PathMapping.of([("/old/proj", str(tmp_path / "new"))])
    (tmp_path / "new").mkdir()
    (tmp_path / "other").mkdir()
    (tmp_path / "other" / ".cc.theme").write_text("keep\n")
    col = Collector()
    entries = [{"value": {"path": "/old/proj/.cc.theme", "text": "acid_trip\n"}}, {"value": {"path": "/old/proj/.cc.theme", "text": "../bad\n"}}]
    assert entries_in._themes(entries[:1], mapping, col, None) == 1
    assert (tmp_path / "new" / ".cc.theme").read_text() == "acid_trip\n"
    assert entries_in._themes(entries[:1], mapping, col, None) == 0
    assert entries_in._themes(entries[1:], mapping, col, None) == 0 and any(w.code == "entry_not_restored" for w in col.warnings)
