
from __future__ import annotations

import json
import os
from contextlib import closing

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import project_move_routes
from src.api.auth import require_auth
from src.api.routes import router as api_router
from src.core.claude_transcript_correlate import slugify_project_dir as enc
from src.core.db import connect
from src.core.project_move.apply import MoveRefused, apply_plan
from src.core.project_move.plan import PaneListing
from src.core.session_journal_store import journal_path
from tests.python.projects.move_world import NO_PANES
from tests.python.projects.move_world import add_session as _session
from tests.python.projects.move_world import plan_for as _plan
from tests.python.projects.move_world import snapshot as _snapshot


def test_plan_lists_everything_and_changes_nothing(world):
    before = _snapshot(world)
    plan = _plan(world, move_folder=True)
    assert plan.ok, plan.failed()
    assert plan.new_root == str(world.new)
    assert [c["id"] for c in plan.children] == [world.ids["sub"]]
    assert plan.children[0]["new_root"] == str(world.new / "sub")
    assert {s["old_dir"]: s["new_dir"] for s in plan.sessions} == {
        str(world.old): str(world.new), str(world.sub / "deep"): str(world.new / "sub" / "deep")}
    assert plan.conversation_rows == 1
    assert {(os.path.basename(m["from"]), os.path.basename(m["to"]), m["mode"]) for m in plan.transcript_moves} == {
        (enc(str(world.old)), enc(str(world.new)), "rename"), (enc(str(world.sub)), enc(str(world.new / "sub")), "rename"),
        (world.short.name, enc(str(world.new)), "merge")}
    info = plan.informational
    assert info["claude_json_trust_keys"] == [{"file": str(world.base / "claude.json"), "keys": [str(world.old)]}]
    assert "never echoed" not in json.dumps(info)
    assert info["settings_files_naming_old_folder"][0]["file"].endswith(".claude/settings.json")
    assert _snapshot(world) == before


def test_apply_moves_folder_and_repoints_in_place(world):
    plan = _plan(world, move_folder=True)
    with closing(connect(world.db, create=False)) as conn:
        done = apply_plan(conn, plan, state_dir=world.state)
    assert done["folder_moved"] and done["transcripts_moved"] == 3
    assert (done["projects"], done["sessions"], done["conversation_index"]) == (2, 2, 1)
    assert not world.old.exists() and (world.new / "notes.md").read_text() == "x"
    with closing(connect(world.db, create=False)) as conn:
        roots = {r["id"]: (r["root"], r["raw_path"]) for r in conn.execute("SELECT * FROM projects")}
        dirs = dict(conn.execute("SELECT session_uuid, working_dir FROM sessions").fetchall())
        index = dict(conn.execute("SELECT conversation_id, working_dir FROM conversation_index").fetchall())
    assert roots[world.ids["alpha"]] == (str(world.new), str(world.new))
    assert roots[world.ids["sub"]] == (str(world.new / "sub"),) * 2
    assert roots[world.ids["alpha_x"]][0] == str(world.sibling)
    assert dirs == {"s-root": str(world.new), "s-sub": str(world.new / "sub" / "deep"), "s-sibling": str(world.sibling)}
    assert index == {"c1": str(world.new / "sub"), "c2": str(world.sibling)}
    names = set(os.listdir(world.projects))
    assert {enc(str(world.new)), enc(str(world.new / "sub")), enc(str(world.sibling))} == names
    merged = world.projects / enc(str(world.new))
    assert sorted(str(p.relative_to(merged)) for p in merged.rglob("*") if p.is_file()) == [
        "memory/a.md", "memory/b.md", "short.jsonl", "t.jsonl"]
    journal = json.loads(journal_path(world.state).read_text())
    assert journal["sessions"]["k"] == {"cwd": str(world.new / "sub"), "working_dir": str(world.sibling)}
    assert journal["offer"]["candidates"][0]["folder"] == str(world.new)
    assert done["journal"] == {"state": "updated", "rewritten": 2}


def test_route_plan_then_repoint_only(world, monkeypatch):
    monkeypatch.setattr(project_move_routes, "read_live_panes", lambda: NO_PANES)
    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    client = TestClient(app)
    url = "/api/v1/projects/alpha/move"
    refused = client.post(url, json={"new_root": str(world.new)}).json()
    assert refused["ok"] is False and not refused["applied"]
    assert any(c["id"] == "new_folder_exists" and not c["ok"] for c in refused["checks"])
    os.rename(world.old, world.new)
    plan = client.post(url, json={"new_root": str(world.new)}).json()
    assert plan["ok"] is True, plan["checks"]
    answer = client.post(url, json={"new_root": str(world.new), "apply": True, "plan_fingerprint": plan["fingerprint"]})
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body["applied"] and body["done"]["projects"] == 2 and body["done"]["folder_moved"] is False
    with closing(connect(world.db, create=False)) as conn:
        assert conn.execute("SELECT root FROM projects WHERE id = ?", (world.ids["alpha"],)).fetchone()[0] == str(world.new)


@pytest.mark.parametrize("live", ["row", "pane", "unanswered"])
def test_refuses_while_a_session_under_the_old_root_is_live(world, live):
    panes = NO_PANES
    if live == "row":
        with closing(connect(world.db, create=False)) as conn:
            _session(conn, "s-live", str(world.sub), lifecycle="running", name="cloude_live", epoch=7)
    elif live == "pane":
        panes = PaneListing(ok=True, panes=(("cloude_shell", 9, str(world.sub)),))
    else:
        panes = PaneListing(ok=False, reason="tmux_missing")
    before = _snapshot(world)
    plan = _plan(world, move_folder=True, panes=panes)
    failed = {c["id"] for c in plan.checks if not c["ok"]}
    assert failed == ({"tmux_listing"} if live == "unanswered" else {"no_live_sessions"})
    if live != "unanswered":
        assert ("cloude_live" if live == "row" else "cloude_shell") in " ".join(plan.failed())
    with closing(connect(world.db, create=False)) as conn, pytest.raises(MoveRefused):
        apply_plan(conn, plan, state_dir=world.state)
    assert _snapshot(world) == before


def test_refuses_when_the_new_transcript_folder_exists(world):
    (world.projects / enc(str(world.new))).mkdir()
    before = _snapshot(world)
    plan = _plan(world, move_folder=True)
    assert [c["id"] for c in plan.checks if not c["ok"]] == ["transcript_targets_free"]
    assert "merge it by hand" in plan.failed()[0]
    with closing(connect(world.db, create=False)) as conn, pytest.raises(MoveRefused):
        apply_plan(conn, plan, state_dir=world.state)
    assert _snapshot(world) == before


def test_refuses_a_same_named_file_in_both_spellings(world):
    (world.short / "t.jsonl").write_text("{}\n")
    before = _snapshot(world)
    plan = _plan(world, move_folder=True)
    assert [c["id"] for c in plan.checks if not c["ok"]] == ["transcript_targets_free"]
    assert "t.jsonl" in plan.failed()[0]
    with closing(connect(world.db, create=False)) as conn, pytest.raises(MoveRefused):
        apply_plan(conn, plan, state_dir=world.state)
    assert _snapshot(world) == before


def test_a_failed_database_step_puts_every_folder_back(world, monkeypatch):
    import sqlite3

    from src.core.project_move import apply as apply_mod

    def boom(conn, plan):
        raise sqlite3.OperationalError("database is locked")

    before = _snapshot(world)
    short_files = sorted(str(p.relative_to(world.short)) for p in world.short.rglob("*"))
    plan = _plan(world, move_folder=True)
    monkeypatch.setattr(apply_mod, "_rewrite_db", boom)
    with closing(connect(world.db, create=False)) as conn, pytest.raises(apply_mod.MoveFailed) as failed:
        apply_plan(conn, plan, state_dir=world.state)
    assert failed.value.step == "database update" and failed.value.undo_errors == []
    assert _snapshot(world) == before
    assert sorted(str(p.relative_to(world.short)) for p in world.short.rglob("*")) == short_files
    assert not world.new.exists()
