
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_ir_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_ir_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.api.auth import require_auth  # noqa: E402
from src.api.imported_restart_routes import router as imported_router  # noqa: E402
from src.core.db import connect, db_path_for  # noqa: E402
from src.core.db_migration import ensure_db_migrated  # noqa: E402
from src.core.session_imported_restart import (  # noqa: E402
    DIRECTORY_MEASURED,
    DIRECTORY_NOT_FOUND,
    DIRECTORY_UNCHECKED,
    ResumeDirectory,
    as_respawn_plan,
    imported_extra_args,
    is_imported_row,
    plan_imported_restart,
    resume_directory,
)
from src.core.session_respawn import (  # noqa: E402
    RESPAWN_AGENT,
    RESPAWN_CANNOT_DETERMINE,
    RESPAWN_TRANSCRIPT_MISSING,
)

UUID = "aaaaaaaa-1111-2222-3333-444444444444"
ROW_UUID = "row-uuid-1"


def imported_row(**overrides):
    row = {
        "id": 7,
        "session_uuid": ROW_UUID,
        "tmux_name": None,
        "tmux_created_epoch": None,
        "working_dir": "/Users/x/proj",
        "claude_session_uuid": UUID,
        "title": "fix the deploy script",
        "claude_title": None,
        "agent_type": None,
        "origin": "imported",
    }
    row.update(overrides)
    return row




def test_the_spelling_that_holds_the_transcript_is_the_one_used(tmp_path: Path):
    real = tmp_path / "iCloud" / "Development" / "proj"
    real.mkdir(parents=True)
    link = tmp_path / "Development"
    link.symlink_to(tmp_path / "iCloud" / "Development")

    corpus = tmp_path / "corpus"
    from src.core.claude_transcript_correlate import slugify_project_dir

    short = str(link / "proj")
    slug = corpus / slugify_project_dir(short)
    slug.mkdir(parents=True)
    (slug / f"{UUID}.jsonl").write_text("{}\n", encoding="utf-8")

    found = resume_directory(short, UUID, corpus_root=corpus)
    assert found.outcome == DIRECTORY_MEASURED
    assert found.working_dir == short
    assert found.refuses is False


def test_a_measured_absence_refuses(tmp_path: Path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    found = resume_directory("/Users/x/proj", UUID, corpus_root=corpus)
    assert found.outcome == DIRECTORY_NOT_FOUND
    assert found.refuses is True
    assert found.working_dir is None, (
        "a caller falling back to the row's own spelling on a refusal "
        "would be doing exactly what this exists to stop"
    )


def test_an_unreadable_corpus_never_refuses(tmp_path: Path):
    for outcome in (
        resume_directory(None, UUID, corpus_root=tmp_path),
        resume_directory("/Users/x/proj", None, corpus_root=tmp_path),
    ):
        assert outcome.outcome == DIRECTORY_UNCHECKED
        assert outcome.refuses is False




def test_the_test_is_the_absence_of_an_identity_not_the_origin_label():
    assert is_imported_row(imported_row()) is True
    assert is_imported_row(imported_row(origin="created")) is True
    assert is_imported_row(imported_row(tmux_name="cloude_x")) is False
    assert is_imported_row(imported_row(tmux_created_epoch=1000)) is False
    assert is_imported_row(None) is False




def _measured(directory="/Users/x/proj"):
    return ResumeDirectory(outcome=DIRECTORY_MEASURED, working_dir=directory)


def test_a_picked_wrapper_resumes_the_conversation():
    plan = plan_imported_restart(
        imported_row(),
        row_read_ok=True,
        choice_verdict="accepted",
        choice_command=f"zsh -c 'cld --resume {UUID}'",
        agent_type="claude-chrome",
        directory=_measured(),
    )
    assert plan.kind == RESPAWN_AGENT
    assert plan.actionable is True
    assert plan.conversation == "resumed"
    assert plan.reuse_session_id == 7, (
        "the new tmux instance must be recorded onto the IMPORTED row, or "
        "a second row appears beside the conversation"
    )
    assert plan.label == "fix the deploy script"
    assert plan.working_dir == "/Users/x/proj"


def test_the_conversation_claim_is_derived_from_the_argv():
    plan = plan_imported_restart(
        imported_row(),
        row_read_ok=True,
        choice_verdict="accepted",
        choice_command="zsh -c 'cld'",
        agent_type="claude",
        directory=_measured(),
    )
    assert plan.kind == RESPAWN_AGENT
    assert plan.conversation != "resumed"


def test_a_missing_transcript_refuses_ahead_of_the_wrapper():
    plan = plan_imported_restart(
        imported_row(),
        row_read_ok=True,
        choice_verdict="accepted",
        choice_command=f"zsh -c 'cld --resume {UUID}'",
        agent_type="claude-chrome",
        directory=ResumeDirectory(
            outcome=DIRECTORY_NOT_FOUND, detail="no transcript is filed"
        ),
    )
    assert plan.kind == RESPAWN_TRANSCRIPT_MISSING
    assert plan.actionable is False
    assert plan.command is None


def test_an_unresolved_wrapper_is_cannot_determine_not_a_shell():
    plan = plan_imported_restart(
        imported_row(),
        row_read_ok=True,
        choice_verdict="unknown_agent",
        choice_command=None,
        choice_detail="'nope' is not configured",
        agent_type="nope",
        directory=_measured(),
    )
    assert plan.kind == RESPAWN_CANNOT_DETERMINE
    assert plan.actionable is False
    assert "not configured" in plan.detail


def test_an_unreadable_row_is_cannot_determine():
    plan = plan_imported_restart(
        None,
        row_read_ok=False,
        choice_verdict="accepted",
        choice_command="zsh -c 'cld'",
    )
    assert plan.kind == RESPAWN_CANNOT_DETERMINE
    assert plan.conversation == "unknown"


def test_a_row_with_no_conversation_says_so_rather_than_pretending():
    plan = plan_imported_restart(
        imported_row(claude_session_uuid=None),
        row_read_ok=True,
        choice_verdict="accepted",
        choice_command="zsh -c 'cld'",
        agent_type="claude",
        directory=_measured(),
    )
    assert plan.conversation == "none_recorded"
    assert "WITHOUT its history" in plan.detail


def test_the_resume_fragment_is_built_in_one_place():
    assert imported_extra_args(imported_row(), row_read_ok=True) == [
        "--resume",
        UUID,
        "--name",
        "fix the deploy script",
    ]
    assert imported_extra_args(imported_row(), row_read_ok=False) is None
    assert (
        imported_extra_args(imported_row(claude_session_uuid=None), row_read_ok=True)
        is None
    )


def test_the_resume_fragment_adds_no_name_when_the_row_has_none():
    assert imported_extra_args(
        imported_row(title=None), row_read_ok=True
    ) == ["--resume", UUID]


def test_a_projection_can_never_kill_a_pane():
    plan = plan_imported_restart(
        imported_row(),
        row_read_ok=True,
        choice_verdict="accepted",
        choice_command=f"zsh -c 'cld --resume {UUID}'",
        agent_type="claude",
        directory=_measured(),
    )
    assert as_respawn_plan(plan).kills_live_pane is False




@pytest.fixture()
def app_env(tmp_path, monkeypatch):
    from src.config import settings

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    monkeypatch.setattr(
        type(settings), "get_state_dir", lambda self: state_dir, raising=True
    )
    assert ensure_db_migrated(state_dir).status == "ok"

    app = FastAPI()
    app.include_router(imported_router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    with TestClient(app) as client:
        yield client, state_dir


def _insert(state_dir, **overrides):
    row = {
        "session_uuid": ROW_UUID,
        "tmux_name": None,
        "tmux_created_epoch": None,
        "working_dir": "/Users/x/proj",
        "claude_session_uuid": UUID,
        "title": "fix the deploy script",
    }
    row.update(overrides)
    with connect(db_path_for(state_dir), create=False) as conn:
        conn.execute(
            "INSERT INTO sessions (session_uuid, tmux_socket, tmux_name, "
            "tmux_created_epoch, working_dir, claude_session_uuid, title, "
            "origin, lifecycle, archived_at, created_at, updated_at) "
            "VALUES (?, 'cloude', ?, ?, ?, ?, ?, 'imported', 'stopped', "
            "'2026-09-08T00:00:00Z', '2026-03-01T00:00:00Z', "
            "'2026-09-08T00:00:00Z')",
            (
                row["session_uuid"],
                row["tmux_name"],
                row["tmux_created_epoch"],
                row["working_dir"],
                row["claude_session_uuid"],
                row["title"],
            ),
        )
    return row["session_uuid"]


def test_the_preview_answers_for_a_row_with_no_tmux_identity(app_env):
    client, state_dir = app_env
    _insert(state_dir)
    r = client.get(
        "/api/v1/sessions/imported/restart/preview",
        params={"session_uuid": ROW_UUID},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["pane_state"] == "unknown", (
        "there is no pane, so its state is not a fact anybody measured"
    )
    assert body["unchanged"]["actionable"] is False, (
        "an unpicked restart of an imported row is not offered at all"
    )
    assert body["wrappers_status"] in ("ok", "unavailable")


def test_the_preview_refuses_a_row_that_has_a_tmux_identity(app_env):
    client, state_dir = app_env
    _insert(state_dir, tmux_name="cloude_live", tmux_created_epoch=1000)
    r = client.get(
        "/api/v1/sessions/imported/restart/preview",
        params={"session_uuid": ROW_UUID},
    )
    assert r.status_code == 409
    assert "cloude_live" in r.json()["detail"]


def test_an_unknown_session_uuid_is_a_404(app_env):
    client, _ = app_env
    r = client.get(
        "/api/v1/sessions/imported/restart/preview",
        params={"session_uuid": "nope"},
    )
    assert r.status_code == 404


def test_the_action_refuses_rather_than_starting_when_a_gate_declines(app_env):
    client, state_dir = app_env
    _insert(state_dir)
    r = client.post(
        "/api/v1/sessions/imported/restart",
        json={"session_uuid": ROW_UUID, "agent_type": "not-a-configured-wrapper"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "refused"
    assert body["session_uuid"] == ROW_UUID
    assert body["detail"]


def test_the_literal_imported_restart_route_matches_before_the_uuid_restart_route():
    from src.api.routes import router as api_router

    def flat(routes):
        for r in routes:
            inner = getattr(r, "original_router", None)
            if inner is not None:
                yield from flat(inner.routes)
            else:
                yield getattr(r, "path", "")

    paths = list(flat(api_router.routes))
    assert paths.index("/sessions/imported/restart") < paths.index("/sessions/{session_uuid}/restart")


def test_a_transcript_only_under_a_managed_logins_projects_folder_is_found(tmp_path, monkeypatch):
    import json

    from src.core.claude_config import profile_roots
    from src.core.claude_transcript_correlate import slugify_project_dir

    home = tmp_path / "home"
    (home / ".claude" / "projects").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    profile = tmp_path / "accounts" / "evergreen"
    folder = profile / "projects" / slugify_project_dir("/Users/x/SoundDesk")
    folder.mkdir(parents=True)
    (folder / f"{UUID}.jsonl").write_text("{}\n", encoding="utf-8")
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"provider_accounts": {"accounts": [
        {"id": "evergreen", "name": "evergreen", "provider": "claude",
         "claude_config_dir": str(profile)}]}}))
    monkeypatch.setattr(profile_roots, "_default_config_path", lambda: config)
    profile_roots.reset_profile_roots_cache_for_tests()
    try:
        found = resume_directory("/Users/x/SoundDesk", UUID)
    finally:
        profile_roots.reset_profile_roots_cache_for_tests()
    assert found.outcome == DIRECTORY_MEASURED
    assert found.transcript_path == str(folder / f"{UUID}.jsonl")
