
from __future__ import annotations

from src.core.claude_transcript_correlate import slugify_project_dir as enc
from tests.python.projects.move_world import plan_for, snapshot


def _failed(plan) -> set:
    return {c["id"] for c in plan.checks if not c["ok"]}


def test_a_missing_parent_is_named_and_the_rest_of_the_plan_still_shows(world):
    before = snapshot(world)
    target = world.base / "org" / "imc" / "alpha"
    plan = plan_for(world, move_folder=True, new_root=str(target))
    assert _failed(plan) == {"new_parent_exists"}
    message = next(c["message"] for c in plan.checks if c["id"] == "new_parent_exists")
    assert str(world.base / "org" / "imc") in message and "does not exist yet" in message
    assert plan.new_root == str(target)
    assert {s["new_dir"] for s in plan.sessions} == {str(target), str(target / "sub" / "deep")}
    assert [c["new_root"] for c in plan.children] == [str(target / "sub")]
    assert {m["to"] for m in plan.transcript_moves} == {
        str(world.projects / enc(str(target))), str(world.projects / enc(str(target / "sub")))}
    assert any(c["id"] == "transcript_targets_free" and c["ok"] for c in plan.checks)
    assert snapshot(world) == before


def test_the_short_spelling_is_stored_long_and_the_typed_text_is_echoed(world):
    typed = str(world.base / "home" / "Development" / "moved")
    plan = plan_for(world, move_folder=True, new_root=typed)
    assert plan.ok, plan.failed()
    assert plan.new_root == str(world.base / "dev" / "moved")
    assert plan.new_root_typed == typed


def test_a_folder_outside_the_allowed_roots_still_lists_sessions(world):
    plan = plan_for(world, move_folder=False, new_root="/private/etc/alpha")
    assert "new_root_valid" in _failed(plan)
    assert plan.new_root == "/private/etc/alpha"
    assert len(plan.sessions) == 2 and all(s["new_dir"] for s in plan.sessions)


def test_a_target_inside_the_old_folder_lists_what_it_can(world):
    plan = plan_for(world, move_folder=True, new_root=str(world.old / "inner"))
    assert "new_root_outside_old" in _failed(plan)
    assert len(plan.sessions) == 2 and all(s["new_dir"] is None for s in plan.sessions)
    assert plan.transcript_moves == []
    assert any("not measured" in w for w in plan.warnings)


def test_an_empty_new_root_is_a_named_failure_not_a_crash(world):
    plan = plan_for(world, move_folder=True, new_root="  ")
    assert "new_root_valid" in _failed(plan) and plan.new_root is None
    assert len(plan.sessions) == 2


def test_with_move_folder_an_existing_target_is_refused_in_plain_words(world):
    world.new.mkdir()
    plan = plan_for(world, move_folder=True)
    assert _failed(plan) == {"new_folder_absent"}
    assert "must not be there yet" in plan.failed()[0]


def test_each_transcript_move_names_the_spelling_that_found_it(world):
    plan = plan_for(world, move_folder=True)
    short_spelling = str(world.base / "home" / "Development" / "alpha")
    by_source = {m["from"]: m["spelling"] for m in plan.transcript_moves}
    assert by_source[str(world.short)] == short_spelling
    assert by_source[str(world.projects / enc(str(world.old)))] == str(world.old)
    assert plan.informational["transcript_spellings_searched"] == [str(world.old), short_spelling]
