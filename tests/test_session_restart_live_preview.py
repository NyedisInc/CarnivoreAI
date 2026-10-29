
from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DEFAULT_WORKING_DIR", "/tmp")

from src.core.session_respawn import (  # noqa: E402
    ALL_PANE_STATES,
    PANE_ALIVE,
    PANE_DEAD,
    PANE_UNKNOWN,
    RESPAWN_AGENT,
    RESPAWN_CANNOT_DETERMINE,
    RESPAWN_NOT_DEAD,
    RESPAWN_REPLAY,
    RESPAWN_SHELL,
    RESPAWN_TRANSCRIPT_MISSING,
    pane_state_from_probe,
    project_restart_rung,
    refuse_if_transcript_missing,
    resolve_respawn_plan,
)
from src.core.session_restart_preview import (  # noqa: E402
    WrapperOffer,
    build_restart_preview,
)

SRC = ROOT / "src"


def _live(**kw):
    args = dict(
        name="cloude_live",
        probe_ok=True,
        pane_dead="0",
        pane_start_command="",
        stored_agent_type=None,
        stored_agent_command=None,
        offers=[],
    )
    args.update(kw)
    return build_restart_preview(**args)




def test_a_live_session_with_an_empty_start_command_projects_a_shell():
    preview = _live(pane_start_command="")

    assert preview.unchanged.kind == RESPAWN_NOT_DEAD
    assert preview.unchanged.actionable is False

    assert preview.projected.kind == RESPAWN_SHELL
    assert "plain shell" in preview.projected.detail


def test_a_live_session_with_a_command_but_no_agent_type_projects_replay():
    preview = _live(
        pane_start_command='"keyc"',
        stored_agent_type=None,
        stored_agent_command=None,
    )
    assert preview.unchanged.kind == RESPAWN_NOT_DEAD
    assert preview.projected.kind == RESPAWN_REPLAY


def test_a_live_session_projects_agent_only_when_both_halves_are_present():
    preview = _live(
        pane_start_command='"keyc"',
        stored_agent_type="claude-skip-permissions",
        stored_agent_command="keyc",
    )
    assert preview.projected.kind == RESPAWN_AGENT
    assert preview.projected.command == "keyc"


def test_each_wrapper_is_predicted_for_a_live_session():
    preview = _live(
        pane_start_command="",
        offers=[
            WrapperOffer(agent_type="claude-chrome", command="cldc"),
            WrapperOffer(agent_type="claude-skip-permissions", command="keyc"),
        ],
    )
    assert [o.kind for o in preview.options] == [RESPAWN_NOT_DEAD] * 2
    assert not any(o.actionable_now for o in preview.options)

    assert [o.projected_kind for o in preview.options] == [RESPAWN_AGENT] * 2
    assert [o.command for o in preview.options] == ["cldc", "keyc"]
    assert all("plain shell" in o.projected_detail for o in preview.options)




def test_a_projection_is_never_not_dead():
    for dead in ("0", "1"):
        for start in ("", '"keyc"', None):
            projected = project_restart_rung(
                probe_ok=True,
                pane_start_command=start,
                agent_command="keyc",
            )
            assert projected.kind != RESPAWN_NOT_DEAD
            acting = resolve_respawn_plan(
                probe_ok=True,
                pane_dead=dead,
                pane_start_command=start,
                agent_command="keyc",
            )
            if dead == "0":
                assert acting.kind == RESPAWN_NOT_DEAD


def test_picking_a_wrapper_cannot_revive_a_live_pane_through_the_preview():
    preview = _live(
        pane_start_command="",
        offers=[WrapperOffer(agent_type="claude-chrome", command="cldc")],
    )
    assert preview.unchanged.kind == RESPAWN_NOT_DEAD
    assert preview.options[0].kind == RESPAWN_NOT_DEAD
    assert preview.options[0].actionable_now is False


def test_pane_state_is_its_own_three_valued_fact():
    assert pane_state_from_probe(True, "1") == PANE_DEAD
    assert pane_state_from_probe(True, "0") == PANE_ALIVE
    assert pane_state_from_probe(False, None) == PANE_UNKNOWN
    assert pane_state_from_probe(True, None) == PANE_UNKNOWN
    assert {PANE_DEAD, PANE_ALIVE, PANE_UNKNOWN} == set(ALL_PANE_STATES)

    assert _live(pane_dead="0").pane_state == PANE_ALIVE
    assert _live(pane_dead="1").pane_state == PANE_DEAD
    assert _live(probe_ok=False, pane_dead=None).pane_state == PANE_UNKNOWN


def test_an_unreadable_probe_projects_cannot_determine_never_a_shell():
    preview = _live(probe_ok=False, pane_dead=None, pane_start_command=None)
    assert preview.pane_state == PANE_UNKNOWN
    assert preview.projected.kind == RESPAWN_CANNOT_DETERMINE
    assert preview.projected.actionable is False
    assert preview.unchanged.kind == RESPAWN_CANNOT_DETERMINE


def test_resolvable_and_actionable_now_are_different_facts():
    preview = _live(
        pane_start_command="",
        offers=[
            WrapperOffer(agent_type="good", command="cldc"),
            WrapperOffer(
                agent_type="needs-model",
                command=None,
                unavailable_reason="the 'cldl' agent needs a model",
            ),
        ],
    )
    good, broken = preview.options

    assert good.actionable_now is False
    assert broken.actionable_now is False
    assert good.resolvable is True
    assert broken.resolvable is False
    assert broken.projected_kind == RESPAWN_CANNOT_DETERMINE
    assert "needs a model" in broken.detail




def test_on_a_dead_pane_the_projection_equals_the_action():
    for start in ("", '"keyc"', None, "   "):
        for agent in ("keyc", None, ""):
            for chosen in (None, "cldc"):
                acting = resolve_respawn_plan(
                    probe_ok=True,
                    pane_dead="1",
                    pane_start_command=start,
                    agent_command=agent,
                    chosen_agent_command=chosen,
                    chosen_agent_type="claude-chrome" if chosen else None,
                )
                projected = project_restart_rung(
                    probe_ok=True,
                    pane_start_command=start,
                    agent_command=agent,
                    chosen_agent_command=chosen,
                    chosen_agent_type="claude-chrome" if chosen else None,
                )
                assert acting == projected, (start, agent, chosen)


def test_a_dead_pane_preview_reports_the_same_rung_twice():
    preview = _live(pane_dead="1", pane_start_command="")
    assert preview.pane_state == PANE_DEAD
    assert preview.unchanged == preview.projected
    assert preview.unchanged.kind == RESPAWN_SHELL




RESUME_BUILDER = "core/session_restart.py"
RESUME_EXTRACTOR = "core/session_respawn.py"

RESTART_PATH_MODULES = (
    "core/session_restart_preview.py",
    "core/session_agent_choice.py",
    "core/session_resume_target.py",
    "core/session_manager.py",
    "core/tmux_backend.py",
)


def test_no_module_on_the_restart_path_spells_its_own_resume():
    offenders = []
    for rel in RESTART_PATH_MODULES:
        tree = ast.parse((SRC / rel).read_text(encoding="utf-8"))
        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(
                node,
                (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
            ):
                body = getattr(node, "body", None)
                if (
                    body
                    and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)
                ):
                    docstrings.add(id(body[0].value))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in docstrings
                and "--resume" in node.value
            ):
                offenders.append(f"src/{rel}:{node.lineno}")

    assert not offenders, (
        "a module on the restart path builds its own --resume:\n  "
        + "\n  ".join(offenders)
        + f"\n\nBuild it in src/{RESUME_BUILDER} via resume_arguments and "
        f"read it back in src/{RESUME_EXTRACTOR} via resume_uuid_in, so "
        "src/core/session_transcript_presence.py can prove the file is "
        "there first. Resuming a transcript that is not there kills the "
        "pane while the row still reads lifecycle=running."
    )


def test_a_replay_that_resumes_is_refused_when_the_transcript_is_gone():
    plan = resolve_respawn_plan(
        probe_ok=True,
        pane_dead="1",
        pane_start_command=(
            "zsh -c 'claude --resume 82aabe7b-c0be-4430-b127-bbf8aad17a57'"
        ),
        agent_command=None,
    )
    assert plan.kind == RESPAWN_REPLAY
    assert plan.resume_uuid == "82aabe7b-c0be-4430-b127-bbf8aad17a57", (
        "the replay rung no longer notices the conversation it would resume"
    )

    refused = refuse_if_transcript_missing(plan, "absent")
    assert refused.kind == RESPAWN_TRANSCRIPT_MISSING
    assert refused.actionable is False
    assert refused.command is None, "a refusal handed back a command to run"
    assert refused.resume_uuid == plan.resume_uuid
    assert refused.detail.strip()


def test_only_a_definite_absence_refuses_a_replay():
    plan = resolve_respawn_plan(
        probe_ok=True,
        pane_dead="1",
        pane_start_command=(
            "zsh -c 'claude --resume 82aabe7b-c0be-4430-b127-bbf8aad17a57'"
        ),
        agent_command=None,
    )
    for outcome in ("present", "unchecked", None):
        passed = refuse_if_transcript_missing(plan, outcome)
        assert passed is plan, (
            f"presence {outcome!r} refused a restart; only 'absent' may"
        )
        assert passed.actionable is True


def test_a_command_with_no_resume_is_never_refused_for_a_transcript():
    plan = resolve_respawn_plan(
        probe_ok=True,
        pane_dead="1",
        pane_start_command='"keyc"',
        agent_command="keyc",
    )
    assert plan.resume_uuid is None
    assert refuse_if_transcript_missing(plan, "absent") is plan
