
from __future__ import annotations

from contextlib import closing
from pathlib import Path

import pytest

from src.core.session_move import plan as mp
from src.core.session_move.plan import build_plan, read_row
from tests.session_move.helpers import (
    FakeSettings,
    Preview,
    Rung,
    add_project,
    add_session,
    migrated_state,
    open_conn,
    resumable,
    write_transcript,
)


@pytest.fixture()
def world(tmp_path: Path) -> dict:
    temp_root = tmp_path / "carnivore-projects"
    source = temp_root / "ses_ab12"
    source.mkdir(parents=True)
    (source / "notes.md").write_text("hello", encoding="utf-8")
    project = temp_root / "app"
    project.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    state = migrated_state(tmp_path)
    corpus = tmp_path / "claude-projects"
    write_transcript(corpus, source)
    return {"temp_root": temp_root, "source": source, "project": project, "home": home, "state": state,
            "corpus": corpus, "settings": FakeSettings(working_dir=temp_root, state_dir=state)}


def _plan(world: dict, working_dir: Path, *, preview=None, project: bool = True, new_folder=None, **kw):
    with closing(open_conn(world["state"])) as conn:
        project_id = add_project(conn, world["project"], "app") if project else None
        uuid = add_session(conn, working_dir, **kw)
        row = read_row(conn, uuid)
        return build_plan(conn, row, project_id=project_id, new_folder=new_folder, settings=world["settings"],
                          preview=preview if preview is not None else resumable(), home=str(world["home"]),
                          corpus_root=world["corpus"])


def _codes(plan) -> list:
    return [r["code"] for r in plan.refusals]


def test_a_temp_session_into_a_project_plans_clean(world: dict) -> None:
    plan = _plan(world, world["source"])
    assert plan.ok, plan.refusals
    assert plan.source_kind == "temp" and plan.destination_kind == "project"
    assert list(plan.files) == ["notes.md"]


def test_a_session_in_a_real_project_folder_is_refused(world: dict) -> None:
    chosen = world["temp_root"] / "my-app"
    chosen.mkdir()
    assert _codes(_plan(world, chosen)) == [mp.NOT_MOVABLE]


def test_neither_or_both_destinations_are_refused(world: dict) -> None:
    assert mp.NO_DESTINATION in _codes(_plan(world, world["source"], project=False))
    both = _plan(world, world["source"], new_folder=str(world["temp_root"] / "new"), name="carnivore_mv2",
                 conversation=None)
    assert mp.NO_DESTINATION in _codes(both)


def test_a_same_name_file_in_the_destination_is_refused(world: dict) -> None:
    (world["project"] / "notes.md").write_text("theirs", encoding="utf-8")
    plan = _plan(world, world["source"])
    assert _codes(plan) == [mp.COLLISION]
    assert plan.collisions == ["notes.md"]
    assert "notes.md" in plan.refusals[0]["message"]


def test_two_repositories_are_refused(world: dict) -> None:
    (world["source"] / ".git").mkdir()
    (world["project"] / ".git").mkdir()
    assert mp.BOTH_GIT in _codes(_plan(world, world["source"]))


def test_a_restart_that_would_not_resume_is_refused(world: dict) -> None:
    shell = _plan(world, world["source"], preview=Preview(pane_state="dead", projected=Rung(kind="shell")))
    assert mp.NOT_A_RESUME in _codes(shell)


def test_unmeasured_liveness_is_refused(world: dict) -> None:
    plan = _plan(world, world["source"], preview=Preview(pane_state="unknown", projected=Rung()))
    assert mp.LIVENESS_UNKNOWN in _codes(plan)


def test_a_session_with_no_conversation_is_refused(world: dict) -> None:
    assert mp.NO_CONVERSATION in _codes(_plan(world, world["source"], conversation=None))


def test_a_conversation_with_no_transcript_is_refused(world: dict) -> None:
    plan = _plan(world, world["source"], conversation="0bad0bad-1111-4222-8333-444455556666")
    assert mp.CONVERSATION_MISSING in _codes(plan)


def test_the_home_folder_carries_no_files(world: dict) -> None:
    (world["home"] / "taxes.pdf").write_text("private", encoding="utf-8")
    plan = _plan(world, world["home"])
    assert plan.ok, plan.refusals
    assert plan.source_kind == "home" and plan.files == {}


def test_a_new_folder_inside_the_temp_folder_is_refused(world: dict) -> None:
    plan = _plan(world, world["source"], project=False, new_folder=str(world["source"] / "inner"))
    assert mp.DESTINATION_IS_SOURCE in _codes(plan)


def test_a_live_pane_plans_ok_but_says_it_kills(world: dict) -> None:
    plan = _plan(world, world["source"], preview=resumable("alive"))
    assert plan.ok and plan.kills_live_pane
