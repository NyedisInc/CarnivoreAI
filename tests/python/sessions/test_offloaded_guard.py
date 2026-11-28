
from __future__ import annotations

import subprocess
from contextlib import closing
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.core.backup_health import offload_guard
from src.core.backup_health import offloaded_marker
from src.core.deepsearch import fallback_hook
from src.core.session_imported_restart import DIRECTORY_NOT_FOUND, resume_directory
from src.core.session_respawn import RESPAWN_OFFLOADED, RESPAWN_REPLAY, RESPAWN_TRANSCRIPT_MISSING, RespawnPlan
from src.core.respawn.transcript_guard import refuse_if_transcript_missing
from tests.helpers.bridge_launch import UUID, capture_commands, tmux, use_bridge_config

SAVE_ON = SimpleNamespace()


@pytest.fixture()
def rig(tmp_path, monkeypatch):
    use_bridge_config(tmp_path, monkeypatch)
    corpus = tmp_path / "projects"
    corpus.mkdir()
    monkeypatch.setattr("src.core.session_imported_restart.default_projects_dir", lambda: corpus)
    monkeypatch.setattr("src.core.claude_transcript_correlate.default_projects_dir", lambda: corpus)
    work = tmp_path / "work"
    work.mkdir()
    fallback_hook.unregister(offload_guard.SAVE_SOURCE_ID)
    fallback_hook.end_boot()
    yield SimpleNamespace(state=tmp_path / "state", corpus=corpus, work=work)
    fallback_hook.unregister(offload_guard.SAVE_SOURCE_ID)
    from src.config import settings

    settings._auth_config_cache = None


def offload(rig, conversation: str = UUID) -> None:
    assert offloaded_marker.write(rig.state, [(conversation, ["S1"], 4096)])


def plugin(on: bool) -> None:
    (fallback_hook.register if on else lambda *_a: fallback_hook.unregister(offload_guard.SAVE_SOURCE_ID))(offload_guard.SAVE_SOURCE_ID, SAVE_ON)


def test_the_marker_round_trips_and_a_corrupt_one_refuses_rather_than_reading_as_empty(rig) -> None:
    assert offload_guard.lookup(UUID) is None
    offload(rig)
    info = offload_guard.lookup(UUID)
    assert info is not None and info.sessions == ("S1",) and info.bytes == 4096 and offload_guard.lookup("other") is None
    (rig.state / offloaded_marker.MARKER_FILE).write_text("{broken")
    doubt = offload_guard.lookup("anything")
    assert doubt is not None and doubt.unreadable and "not started fresh" in doubt.detail


@pytest.mark.parametrize("on,sentence", [(True, "restore it first"), (False, "turn backups on to restore")])
@pytest.mark.asyncio
async def test_waking_an_offloaded_session_is_refused_offloaded_and_start_fresh_starts_nothing(rig, monkeypatch, tmux_test_socket, on, sentence) -> None:
    from src.api.session_sleep_routes import wake_by_uuid
    from tests.python.sessions.test_wake_start_fresh import _asleep_row, _manager, _row

    session_uuid, name, row_id = _asleep_row(rig, tmux_test_socket)
    offload(rig)
    plugin(on)
    capture_commands(monkeypatch, run_instead="sh -c 'sleep 45'")
    state = SimpleNamespace(session_manager=_manager())
    plain = await wake_by_uuid(state, session_uuid, "cld")
    fresh = await wake_by_uuid(state, session_uuid, "cld", start_fresh=True)
    for answer in (plain, fresh):
        assert answer.status == "refused" and answer.code == "offloaded" and answer.codes == ["offloaded"], answer
        assert sentence in answer.detail
    try:
        live = tmux(tmux_test_socket, "list-sessions", "-F", "#{session_name}").split()
    except subprocess.CalledProcessError:
        live = []
    assert not [n for n in live if n.startswith("carnivore_wf")] and _row(rig, session_uuid) == (row_id, name, UUID), "nothing launched and the row is untouched"


def test_the_respawn_guard_refuses_an_offloaded_resume_with_its_own_kind(rig) -> None:
    plan = RespawnPlan(kind=RESPAWN_REPLAY, resume_uuid=UUID)
    assert refuse_if_transcript_missing(plan, "absent").kind == RESPAWN_TRANSCRIPT_MISSING
    offload(rig)
    guarded = refuse_if_transcript_missing(plan, "absent", "ignored")
    assert guarded.kind == RESPAWN_OFFLOADED and not guarded.actionable and guarded.command is None and "offloaded" in guarded.detail
    assert refuse_if_transcript_missing(plan, "present") is plan


def test_the_resume_directory_and_imported_restart_plan_carry_offloaded(rig) -> None:
    from src.core.session_imported_restart import plan_imported_restart

    directory = resume_directory(str(rig.work), UUID)
    assert directory.outcome == DIRECTORY_NOT_FOUND and not directory.offloaded
    offload(rig)
    directory = resume_directory(str(rig.work), UUID)
    assert directory.refuses and directory.offloaded and "offloaded" in directory.detail
    row = {"id": 1, "session_uuid": "S", "claude_session_uuid": UUID, "working_dir": str(rig.work), "agent_type": "cld"}
    plan = plan_imported_restart(row, row_read_ok=True, choice_verdict="accepted", choice_command="claude", directory=directory)
    assert plan.kind == RESPAWN_OFFLOADED


def test_a_restart_from_recent_refuses_offloaded_and_never_a_blank_session(rig, tmp_path) -> None:
    from src.core.db import connect, db_path_for, transaction
    from src.core.db_migration import ensure_db_migrated
    from src.core.session_restart import RESTART_CONVERSATION_MISSING, resolve_restart_source
    from src.core.trail_entry import utc_now

    state = tmp_path / "dbstate"
    state.mkdir()
    ensure_db_migrated(state, 4, "0.8.2")
    with closing(connect(db_path_for(state))) as conn:
        with transaction(conn):
            conn.execute("INSERT INTO sessions (session_uuid, origin, tmux_socket, tmux_name, tmux_created_epoch, working_dir, agent_type, title, claude_session_uuid, created_at, updated_at) "
                         "VALUES ('s-1', 'created', 'cloude', 'cloude_x', 1700000000, ?, 'claude', 'T', ?, ?, ?)", (str(rig.work), UUID, utc_now(), utc_now()))
        before = resolve_restart_source(conn, session_uuid="s-1")
        assert before.outcome == RESTART_CONVERSATION_MISSING and not before.offloaded
        offload(rig)
        after = resolve_restart_source(conn, session_uuid="s-1")
    assert after.outcome == RESTART_CONVERSATION_MISSING and after.offloaded
    body = offload_guard.refusal_body(offload_guard.lookup(after.claude_session_uuid))  # type: ignore[arg-type]
    assert body["code"] == "offloaded" and body["conversations"] == [UUID] and body["restore_route"].endswith("/restore") and body["plugin_on"] is False


def test_resuming_an_older_conversation_that_is_offloaded_answers_the_code(rig, tmp_path, monkeypatch) -> None:
    from src.api import session_conversations_routes as routes
    from src.core.db import connect, db_path_for, transaction
    from src.core.db_migration import ensure_db_migrated
    from src.core.trail_entry import utc_now

    state = tmp_path / "dbstate2"
    state.mkdir()
    ensure_db_migrated(state, 4, "0.8.2")
    monkeypatch.setattr(routes, "_corpus_root", lambda: rig.corpus)
    with closing(connect(db_path_for(state))) as conn:
        with transaction(conn):
            conn.execute("INSERT INTO sessions (session_uuid, origin, tmux_socket, tmux_name, tmux_created_epoch, working_dir, agent_type, title, claude_session_uuid, created_at, updated_at) "
                         "VALUES ('s-1', 'created', 'cloude', 'cloude_x', 1700000000, ?, 'claude', 'T', ?, ?, ?)", (str(rig.work), UUID, utc_now(), utc_now()))
        with pytest.raises(HTTPException) as plain:
            routes._resume_source(conn, "s-1", UUID)
        offload(rig)
        with pytest.raises(HTTPException) as offloaded:
            routes._resume_source(conn, "s-1", UUID)
    assert plain.value.status_code == 409 and isinstance(plain.value.detail, str)
    assert offloaded.value.status_code == 409 and offloaded.value.detail["code"] == "offloaded"


def test_a_launch_that_resumes_an_offloaded_conversation_is_refused_at_the_create_seam(rig) -> None:
    from src.api.session_crud_routes import create_session_with_extra
    from src.models.session_requests import CreateSessionRequest

    offload(rig)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(session_manager=None)), state=SimpleNamespace())
    with pytest.raises(HTTPException) as caught:
        import asyncio

        asyncio.run(create_session_with_extra(request, CreateSessionRequest(working_dir=str(rig.work)), agent_extra_args=["--resume", UUID, "--fork-session"]))
    assert caught.value.status_code == 409 and caught.value.detail["code"] == offload_guard.OFFLOADED_CODE
    assert offload_guard.resumed_offloaded(["--resume", "another-conversation"]) is None and offload_guard.resumed_offloaded(None) is None


def test_the_restart_route_maps_an_offloaded_refusal_to_its_code_not_conversation_missing(rig) -> None:
    from src.api.session_restart_apply_routes import restart_error_to_http
    from src.core.session_ops import restart as restart_ops

    offload(rig)
    http = restart_error_to_http(restart_ops.ConversationOffloaded(offload_guard.refusal_body(offload_guard.lookup(UUID))))  # type: ignore[arg-type]
    assert http.status_code == 409 and http.detail["code"] == offload_guard.OFFLOADED_CODE and http.detail["conversations"] == [UUID]
