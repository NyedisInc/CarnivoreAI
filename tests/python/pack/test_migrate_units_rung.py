
from __future__ import annotations

import asyncio
import subprocess
from contextlib import closing
from pathlib import Path

import pytest

from test_migrate_two_machines import world  # noqa: F401

from src.api import federation_pack_carry_routes as carry_routes
from src.api import federation_pack_migrate_routes as migrate_routes
from src.api import pack_migrate_env as env_mod
from src.core.pack.carry import scan
from src.core.pack.migrate import apply, plan
from src.core.project_writes import create_project


def git(path: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(path), "-c", "user.name=t", "-c", "user.email=t@t", *args], check=True, capture_output=True)
    return done.stdout.decode().strip()


def test_a_non_git_root_with_a_repo_is_carried_as_units_and_an_old_target_keeps_tar(world) -> None:
    a, b, current, link = world
    root = a.projects / "quar"
    repo = root / "PillPanic"
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    (repo / ".gitignore").write_text("*.log\n")
    (repo / "a.txt").write_text("one\n")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "first")
    (repo / "a.txt").write_text("one\nuncommitted\n")
    (repo / "new.txt").write_text("untracked\n")
    (repo / "junk.log").write_text("ignored\n")
    (root / "note.txt").write_text("loose\n")
    with closing(a.conn()) as conn:
        project = create_project(conn, name="quar", path=str(root))
        project = dict(conn.execute("SELECT * FROM projects WHERE id = ?", (project["id"],)).fetchone())
    head = git(repo, "rev-parse", "HEAD")
    request = link(a, b)
    b.app.include_router(carry_routes.router, prefix="/api/v1")
    b.app.dependency_overrides[carry_routes._require_migrate] = b.app.dependency_overrides[migrate_routes._require_migrate]
    env = env_mod.source_env()

    old = asyncio.run(plan.plan_project(env, project, "iid-b", apply.guarded(request)))
    assert old.rung == "tar" and old.carry is None, old.view()

    made = asyncio.run(plan.plan_project(env, project, "iid-b", apply.guarded(request), target_caps=[scan.CARRY_TREE]))
    assert made.rung == "units" and not made.blocking, made.view()
    assert [r.rel for r in made.carry.repos] == ["PillPanic"] and made.carry.files == ["note.txt"]
    names = {c["name"]: c for c in made.checks}
    assert "junk.log" in names["left_behind"]["detail"] and "2 uncommitted" in names["carried_work"]["detail"]

    asyncio.run(apply.apply_project(env, made, request))
    landed = Path(b.project(project["uid"])["root"])
    assert git(landed / "PillPanic", "rev-parse", "HEAD") == head
    assert git(landed / "PillPanic", "status", "--porcelain") == git(repo, "status", "--porcelain")
    assert (landed / "PillPanic" / "a.txt").read_text() == "one\nuncommitted\n"
    assert (landed / "note.txt").read_text() == "loose\n"
    assert not (landed / "PillPanic" / "junk.log").exists()
    assert a.project(project["uid"])["pack_state"] == "moved_away"
