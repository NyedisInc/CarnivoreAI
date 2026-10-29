
from __future__ import annotations

import json
import os

from src.core import config_writer
from tests.skill_manager.test_overrides_write_through_link import put, world  # noqa: F401


def _plant(link, victim):
    victim.write_text("VICTIM", encoding="utf-8")
    os.symlink(victim, link)


def test_planted_bak_symlink_is_not_followed_by_commit(tmp_path):
    cfg = tmp_path / "settings.json"
    cfg.write_text(json.dumps({"a": 1}), encoding="utf-8")
    victim = tmp_path / "victim.txt"
    _plant(tmp_path / "settings.json.bak", victim)
    outcome = config_writer.commit(cfg, lambda d: {**d, "b": 2}, file_mode=0o600)
    assert outcome.wrote
    assert victim.read_text() == "VICTIM"
    assert not os.path.islink(tmp_path / "settings.json.bak")
    assert json.loads((tmp_path / "settings.json.bak").read_text()) == {"a": 1}


def test_project_and_local_writes_leave_no_bak_and_follow_no_planted_link(world):  # noqa: F811
    claude_dir = world.project / ".claude"
    claude_dir.mkdir()
    victim = world.home / "victim.txt"
    for leaf in ("settings.json", "settings.local.json"):
        (claude_dir / leaf).write_text("{}", encoding="utf-8")
        _plant(claude_dir / f"{leaf}.bak", victim)
    for file in ("project", "local"):
        reply = put(world, file=file, project_path=str(world.project))
        assert reply.status_code == 200, reply.text
    assert victim.read_text() == "VICTIM"
    assert all(os.path.islink(claude_dir / f"{leaf}.bak") for leaf in ("settings.json", "settings.local.json"))
    assert sorted(p.name for p in claude_dir.iterdir() if p.name.endswith(".tmp")) == []
    (claude_dir / "settings.json.bak").unlink()
    assert put(world, file="project", project_path=str(world.project), state="on").status_code == 200
    assert not (claude_dir / "settings.json.bak").exists()


def test_user_scope_still_writes_a_backup(world):  # noqa: F811
    assert put(world, profile="linked").status_code == 200
    assert (world.shared.parent / "settings.json.bak").exists()


def test_toggle_targets_the_named_profiles_own_settings(world):  # noqa: F811
    other = world.home / ".carnivore" / "accounts" / "other"
    other.mkdir(parents=True)
    os.symlink(world.home / ".claude" / "skills", other / "skills")
    (other / "settings.json").write_text('{"own": true}', encoding="utf-8")
    before = world.shared.read_text()
    reply = put(world, profile="other")
    assert reply.status_code == 200, reply.text
    assert json.loads((other / "settings.json").read_text()) == {"own": True, "skillOverrides": {"sme": "off"}}
    assert world.shared.read_text() == before


def test_codex_toggle_works_with_no_claude_profile_and_claude_is_404(world):  # noqa: F811
    import shutil

    shutil.rmtree(world.home / ".claude")
    shutil.rmtree(world.home / ".carnivore")
    reply = put(world, harness="codex", file="user", state="off")
    assert reply.status_code == 200, reply.text
    assert put(world, profile=None).status_code == 404


def test_claude_group_with_no_profiles_is_a_404_not_an_index_error():
    import pytest
    from fastapi import HTTPException

    from src.api.skills_manager_routes import _claude_group
    from src.core.skill_manager.types import Profile

    with pytest.raises(HTTPException) as empty:
        _claude_group([], None)
    assert empty.value.status_code == 404
    with pytest.raises(HTTPException) as unknown:
        _claude_group([Profile("a", "/nowhere/a")], "b")
    assert unknown.value.status_code == 404
