
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_cx_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_cx_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core import claude_transcript_correlate
from src.core.agent_families import get_family
from src.core.attention import codex_gather
from src.core.db import connect, db_path_for, transaction
from src.core.db_migration import ensure_db_migrated
from src.core.session_imported_restart import (
    DIRECTORY_MEASURED,
    imported_extra_args,
    plan_imported_restart,
    resume_directory,
)
from src.core.session_respawn import RESPAWN_TRANSCRIPT_MISSING
from src.core.session_restart import (
    RESTART_CONVERSATION_MISSING,
    RESTART_RESUMABLE,
    resolve_restart_source,
    resume_arguments,
)
from src.core.session_transcript_presence import (
    CONVERSATION_ABSENT,
    CONVERSATION_PRESENT,
    CONVERSATION_UNCHECKED,
    family_conversation_presence,
)
from src.core.trail_entry import utc_now

CODEX_UUID = "019a1b2c-3d4e-7f60-8a9b-0c1d2e3f4a5b"
OTHER_UUID = "019a1b2c-3d4e-7f60-8a9b-ffffffffffff"
WORKING_DIR = "/Users/x/Development/proj"


@pytest.fixture
def stores(tmp_path, monkeypatch):
    corpus = tmp_path / "projects"
    corpus.mkdir()
    monkeypatch.setattr(
        claude_transcript_correlate, "default_projects_dir", lambda: corpus
    )
    codex_home = tmp_path / "codex"
    (codex_home / "sessions").mkdir(parents=True)
    monkeypatch.setattr(codex_gather, "DEFAULT_CODEX_HOME", str(codex_home))
    return corpus, codex_home


def _write_rollout(codex_home: Path, uuid: str) -> Path:
    day = codex_home / "sessions" / "2026" / "09" / "24"
    day.mkdir(parents=True, exist_ok=True)
    path = day / f"rollout-2026-09-24T10-00-00-{uuid}.jsonl"
    path.write_text('{"type":"session_meta"}\n', encoding="utf-8")
    return path


@pytest.fixture
def conn(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    ensure_db_migrated(state, 4, "0.8.2")
    c = connect(db_path_for(state))
    yield c
    c.close()


def _insert(conn, **overrides) -> int:
    row = {
        "session_uuid": "row-uuid",
        "origin": "created",
        "tmux_socket": "cloude",
        "tmux_name": "cloude_proj",
        "tmux_created_epoch": 1788787880,
        "working_dir": WORKING_DIR,
        "agent_type": "codex",
        "agent_family": "codex",
        "claude_session_uuid": CODEX_UUID,
        "title": "codex work",
        "lifecycle": "stopped",
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }
    row.update(overrides)
    cols = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    with transaction(conn):
        cur = conn.execute(
            f"INSERT INTO sessions ({cols}) VALUES ({marks})", list(row.values())
        )
    return int(cur.lastrowid)




def test_restart_resumes_a_codex_row_whose_rollout_exists(conn, stores):
    _, codex_home = stores
    _write_rollout(codex_home, CODEX_UUID)
    _insert(conn)

    source = resolve_restart_source(conn, session_uuid="row-uuid")

    assert source.outcome == RESTART_RESUMABLE, source.detail
    argv = resume_arguments(
        source.claude_session_uuid, family=get_family(source.agent_type).name
    )
    assert argv == ["resume", CODEX_UUID]


def test_restart_refuses_a_codex_row_with_no_rollout(conn, stores):
    _, codex_home = stores
    _write_rollout(codex_home, OTHER_UUID)
    _insert(conn)

    source = resolve_restart_source(conn, session_uuid="row-uuid")

    assert source.outcome == RESTART_CONVERSATION_MISSING
    assert source.claude_session_uuid == CODEX_UUID
    assert CODEX_UUID in (source.detail or "")


def test_restart_resolves_a_profile_id_to_its_family_for_the_rollout_check(conn, stores, monkeypatch):
    from types import SimpleNamespace

    from src.config import settings

    _, codex_home = stores
    _write_rollout(codex_home, CODEX_UUID)
    _insert(conn, agent_type="rigcodex")
    monkeypatch.setattr(
        type(settings), "load_auth_config",
        lambda self: SimpleNamespace(agents=SimpleNamespace(wrappers=[{"id": "rigcodex", "family": "codex"}])),
    )

    source = resolve_restart_source(conn, session_uuid="row-uuid")

    assert source.outcome == RESTART_RESUMABLE, source.detail




def test_recreate_resumes_a_codex_row_whose_rollout_exists(stores):
    _, codex_home = stores
    rollout = _write_rollout(codex_home, CODEX_UUID)
    row = {
        "id": 7,
        "working_dir": WORKING_DIR,
        "claude_session_uuid": CODEX_UUID,
        "agent_family": "codex",
    }

    directory = resume_directory(
        WORKING_DIR, CODEX_UUID, family=row["agent_family"]
    )
    assert directory.outcome == DIRECTORY_MEASURED, directory.detail
    assert directory.working_dir == WORKING_DIR
    assert directory.transcript_path == str(rollout)

    extra = imported_extra_args(row, row_read_ok=True)
    assert extra == ["resume", CODEX_UUID]
    plan = plan_imported_restart(
        row,
        row_read_ok=True,
        choice_verdict="accepted",
        choice_command="zsh -c 'codex resume %s --yolo'" % CODEX_UUID,
        agent_type="codex",
        directory=directory,
    )
    assert plan.kind != RESPAWN_TRANSCRIPT_MISSING


def test_recreate_refuses_a_codex_row_with_no_rollout(stores):
    _, codex_home = stores
    _write_rollout(codex_home, OTHER_UUID)
    row = {"id": 7, "claude_session_uuid": CODEX_UUID, "agent_family": "codex"}

    directory = resume_directory(WORKING_DIR, CODEX_UUID, family="codex")
    assert directory.refuses

    plan = plan_imported_restart(
        row,
        row_read_ok=True,
        choice_verdict="accepted",
        choice_command="zsh -c 'codex resume %s'" % CODEX_UUID,
        agent_type="codex",
        directory=directory,
    )
    assert plan.kind == RESPAWN_TRANSCRIPT_MISSING


def test_the_recreate_route_passes_the_rows_family(tmp_path, stores, monkeypatch):
    from src.api import recreate_routes

    _, codex_home = stores
    _write_rollout(codex_home, CODEX_UUID)
    row = {
        "tmux_name": "cloude_proj",
        "working_dir": WORKING_DIR,
        "claude_session_uuid": CODEX_UUID,
        "agent_family": "codex",
    }
    monkeypatch.setattr(recreate_routes, "_read_row", lambda u: {"row": row})
    monkeypatch.setattr(recreate_routes, "_resolved", lambda s, u: s["row"])
    monkeypatch.setattr(recreate_routes, "_measure_presence", lambda n, s: None)
    monkeypatch.setattr(recreate_routes, "_socket_name", lambda: "cloude")

    gathered = recreate_routes._gather("row-uuid")

    assert gathered["directory"].outcome == DIRECTORY_MEASURED
    assert gathered["extra_args"] == ["resume", CODEX_UUID]




def test_codex_lookup_reports_three_distinct_outcomes(tmp_path, stores):
    _, codex_home = stores
    _write_rollout(codex_home, CODEX_UUID)

    assert family_conversation_presence("codex", CODEX_UUID).outcome == (
        CONVERSATION_PRESENT
    )
    assert family_conversation_presence("codex", OTHER_UUID).outcome == (
        CONVERSATION_ABSENT
    )
    assert family_conversation_presence("codex", "not-a-uuid").outcome == (
        CONVERSATION_UNCHECKED
    )
    assert family_conversation_presence(
        "codex", CODEX_UUID, codex_home=str(tmp_path / "nowhere")
    ).outcome == CONVERSATION_UNCHECKED


def test_claude_lookup_is_unchanged_and_ignores_codex_rollouts(conn, stores):
    corpus, codex_home = stores
    _write_rollout(codex_home, CODEX_UUID)
    _insert(conn, agent_type="claude-skip-permissions", agent_family="claude")

    source = resolve_restart_source(conn, session_uuid="row-uuid")
    assert source.outcome == RESTART_CONVERSATION_MISSING
    assert resume_directory(
        WORKING_DIR, CODEX_UUID, family="claude", corpus_root=corpus
    ).refuses

    project = corpus / "-Users-x-Development-proj"
    project.mkdir()
    (project / f"{CODEX_UUID}.jsonl").write_text("{}\n", encoding="utf-8")
    assert resolve_restart_source(conn, session_uuid="row-uuid").outcome == (
        RESTART_RESUMABLE
    )
    assert resume_directory(
        WORKING_DIR, CODEX_UUID, corpus_root=corpus
    ).outcome == DIRECTORY_MEASURED
