
from __future__ import annotations

from contextlib import closing

import pytest

from src.core.db import connect
from src.core.project_move.apply import apply_plan
from src.core.skills.ledger_types import SCOPE_GLOBAL, SCOPE_PROJECT
from tests.python.projects.move_world import plan_for, snapshot


def _install(conn, install_id: str, name: str, scope: str, project_path: str, files: list) -> None:
    conn.execute(
        "INSERT INTO installed_items (install_id, item_id, kind, publisher, name, version, digest, scope,"
        " project_path, source_index_url, publisher_key_id, installed_at, updated_at)"
        " VALUES (?, ?, 'skill', 'pub', ?, '1', 'd', ?, ?, 'u', 'k', 'now', 'now')",
        (install_id, f"pub/{name}", name, scope, project_path))
    for path in files:
        conn.execute("INSERT INTO installed_item_targets (install_id, harness, path) VALUES (?, 'claude', ?)",
                     (install_id, path))


@pytest.fixture()
def installed(world):
    skill = world.sub / ".claude" / "skills" / "tidy" / "SKILL.md"
    with closing(connect(world.db, create=False)) as conn:
        _install(conn, "i-sub", "tidy", SCOPE_PROJECT, str(world.sub), [str(skill)])
        _install(conn, "i-global", "tidy", SCOPE_GLOBAL, "", ["/elsewhere/skills/tidy/SKILL.md"])
    return skill


def test_the_plan_counts_and_the_apply_rebases_install_rows(world, installed):
    plan = plan_for(world, move_folder=True)
    assert plan.ok, plan.failed()
    assert plan.skill_installs == {"items": 1, "files": 1}
    with closing(connect(world.db, create=False)) as conn:
        done = apply_plan(conn, plan, state_dir=world.state)
        items = dict(conn.execute("SELECT install_id, project_path FROM installed_items").fetchall())
        files = sorted(r[0] for r in conn.execute("SELECT path FROM installed_item_targets"))
    assert (done["skill_install_items"], done["skill_install_files"]) == (1, 1)
    assert items == {"i-sub": str(world.new / "sub"), "i-global": ""}
    assert files == sorted([str(world.new / "sub" / ".claude" / "skills" / "tidy" / "SKILL.md"),
                            "/elsewhere/skills/tidy/SKILL.md"])


def test_an_install_already_at_the_new_folder_is_refused_in_the_plan(world, installed):
    with closing(connect(world.db, create=False)) as conn:
        _install(conn, "i-there", "tidy", SCOPE_PROJECT, str(world.new / "sub"), [])
    before = snapshot(world)
    plan = plan_for(world, move_folder=True)
    assert [c["id"] for c in plan.checks if not c["ok"]] == ["skill_installs_free"]
    assert "tidy is already installed" in plan.failed()[0]
    assert snapshot(world) == before
