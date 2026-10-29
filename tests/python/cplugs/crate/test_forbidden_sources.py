
from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.cplugs.crate import forbidden
from src.cplugs.crate import plan as plan_module
from src.cplugs.crate import writer as writer_module
from src.cplugs.crate.handle import JobHandle
from src.cplugs.crate.plan import build_plan
from src.cplugs.crate.writer import run_export
from tests.python.cplugs.crate.crate_world import crate_text, env_for, make_world, session_request
from tests.python.cplugs.crate.forbidden_world import plant_canaries, plant_hardlink, plant_symlink


@pytest.fixture
def world(tmp_path: Path) -> SimpleNamespace:
    w = make_world(tmp_path)
    w.canary = plant_canaries(w)
    return w


def _carried(plan) -> set:
    return {f.source_path for f in plan.files}


def test_canaries_are_never_planned(world: SimpleNamespace) -> None:
    plan = build_plan(env_for(world), session_request())
    assert plan.ok, plan.blockers
    for path in _carried(plan):
        assert world.canary not in Path(path).read_text(errors="replace"), path
        assert "session-env" not in path


def test_a_symlink_named_like_a_rollout_blocks(world: SimpleNamespace) -> None:
    link = plant_symlink(world)
    plan = build_plan(env_for(world), session_request())
    assert not plan.ok and str(link) not in _carried(plan)
    assert any(b["code"] == "source_forbidden" and str(link) in b["detail"] and "symlink" in b["detail"]
               for b in plan.blockers)
    assert all(world.canary not in b["detail"] for b in plan.blockers)


def test_a_hard_link_named_like_a_rollout_blocks(world: SimpleNamespace) -> None:
    link = plant_hardlink(world)
    plan = build_plan(env_for(world), session_request())
    assert not plan.ok and str(link) not in _carried(plan)
    assert any(b["code"] == "source_forbidden" and str(link) in b["detail"] and "hard link" in b["detail"]
               for b in plan.blockers)


def test_the_inode_rule_can_fail(world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    link = plant_hardlink(world)
    monkeypatch.setattr(plan_module, "deny_inodes", lambda locs: set())
    plan = build_plan(env_for(world), session_request())
    assert str(link) in _carried(plan)


def test_no_canary_reaches_any_crate_member(world: SimpleNamespace) -> None:
    env = env_for(world)
    result = run_export(env, build_plan(env, session_request()), JobHandle("c"))
    text = crate_text(result.path)
    assert b"crate-canary-" not in text and len(text) > 1000


def test_the_crate_canary_check_can_fail(world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    plant_hardlink(world)
    monkeypatch.setattr(plan_module, "deny_inodes", lambda locs: set())
    monkeypatch.setattr(writer_module, "deny_inodes", lambda locs: set())
    env = env_for(world)
    result = run_export(env, build_plan(env, session_request()), JobHandle("r"))
    assert world.canary.encode() in crate_text(result.path)


def test_a_deny_name_is_refused_anywhere(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    for name in ("auth.json", ".credentials.json", "state_5.sqlite", "x.sqlite-wal", "config.toml"):
        (root / name).write_text("x")
        with pytest.raises(forbidden.SourceForbidden, match="by its name"):
            forbidden.open_source(str(root / name), [str(root.resolve())], set())


def test_outside_the_roots_and_not_regular_are_refused(tmp_path: Path) -> None:
    root, other = tmp_path / "root", tmp_path / "other"
    root.mkdir()
    other.mkdir()
    (other / "a.jsonl").write_text("{}\n")
    with pytest.raises(forbidden.SourceForbidden, match="outside"):
        forbidden.open_source(str(other / "a.jsonl"), [str(root.resolve())], set())
    os.mkfifo(root / "pipe.jsonl")
    writer = os.open(root / "pipe.jsonl", os.O_RDWR | os.O_NONBLOCK)
    try:
        with pytest.raises(forbidden.SourceForbidden, match="not a regular file"):
            forbidden.open_source(str(root / "pipe.jsonl"), [str(root.resolve())], set())
    finally:
        os.close(writer)


def test_deny_inodes_lists_every_credential_file(world: SimpleNamespace) -> None:
    deny = forbidden.deny_inodes(world.locations)
    for path in (Path(world.codex) / "auth.json", Path(world.codex) / "state_5.sqlite", Path(world.home) / ".credentials.json",
                 Path(world.home) / ".claude.json"):
        st = os.stat(path)
        assert (st.st_dev, st.st_ino) in deny, path
