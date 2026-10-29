
from __future__ import annotations

import json
from contextlib import closing

from src.core.db import connect
from src.core.pack.trust_carry import store
from src.core.project_move.apply import apply_plan
from tests.python.projects.move_world import plan_for


def _tree_state(root):
    return {str(p): (p.read_bytes(), p.stat().st_mtime_ns) for p in sorted(root.rglob("*")) if p.is_file()}


def test_a_move_writes_nothing_to_a_claude_json(world, monkeypatch):
    home = world.base / "home"
    fake = home / ".claude.json"
    fake.write_text(json.dumps({"projects": {str(world.old): {"hasTrustDialogAccepted": True}}}))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("src.core.project_move.claude_side.claude_json_files", lambda config_path=None: [fake, world.base / "claude.json"])
    before = {**_tree_state(home), str(world.base / "claude.json"): (world.base / "claude.json").read_bytes()}
    plan = plan_for(world, move_folder=True)
    assert plan.ok, plan.failed()
    with closing(connect(world.db, create=False)) as conn:
        done = apply_plan(conn, plan, state_dir=world.state)
    assert "claude_json_trust" not in done
    assert not (home / ".claude.json.bak").exists()
    assert _tree_state(home)[str(fake)] == before[str(fake)]
    assert (world.base / "claude.json").read_bytes() == before[str(world.base / "claude.json")]


def test_carried_trust_follows_the_move_on_the_carnivore_record(world):
    with closing(connect(world.db, create=False)) as conn:
        uid = conn.execute("SELECT uid FROM projects WHERE id = ?", (world.ids["alpha"],)).fetchone()[0]
        store.record(conn, str(world.old), uid, "inst-a", "op-1", projects_dir=str(world.base))
        assert store.carried_op(conn, str(world.old)) == "op-1"
    plan = plan_for(world, move_folder=True)
    assert plan.ok, plan.failed()
    with closing(connect(world.db, create=False)) as conn:
        done = apply_plan(conn, plan, state_dir=world.state)
        assert done["carried_trust"] == 1
        assert store.carried_op(conn, str(world.new)) == "op-1"
        assert store.carried_op(conn, str(world.old)) is None


def test_an_uncarried_project_stays_uncarried_after_a_move(world):
    plan = plan_for(world, move_folder=True)
    with closing(connect(world.db, create=False)) as conn:
        done = apply_plan(conn, plan, state_dir=world.state)
        assert done["carried_trust"] == 0
        assert store.carried_op(conn, str(world.new)) is None
