
from __future__ import annotations

import json
import os
import shutil
import tempfile
from contextlib import closing
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_wbf_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_wbf_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

from src.core.db import connect, db_path_for  # noqa: E402
from src.core.db_migration import ensure_db_migrated  # noqa: E402
from src.core.session_work_backfill import (  # noqa: E402
    backfill_last_work_at,
    is_work,
    run_boot_backfill,
)

from tests.helpers.subagent_fixture import CONV, PROJECT_DIR, WORKDIR, build_corpus  # noqa: E402

KEPT = "5ab0c0de-0000-4000-8000-0000000000aa"
CODEX = "5ab0c0de-0000-4000-8000-0000000000bb"


@pytest.fixture
def state(tmp_path: Path) -> Path:
    directory = tmp_path / "state"
    directory.mkdir()
    result = ensure_db_migrated(directory, 4, "0.0.0")
    assert result.status == "ok", result.message
    return directory


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    target = tmp_path / "projects"
    build_corpus(target)
    return target


def _row(conn, name: str, *, uuid, last_work_at=None, family="claude", workdir=WORKDIR) -> int:
    cur = conn.execute(
        "INSERT INTO sessions (session_uuid, origin, tmux_socket, tmux_name, "
        "tmux_created_epoch, lifecycle, project_attribution, working_dir, "
        "agent_family, claude_session_uuid, last_work_at, created_at, updated_at) "
        "VALUES (?, 'created', 'cloude', ?, 1, 'running', 'explicit', ?, ?, ?, ?, "
        "'2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')",
        (f"su-{name}", name, workdir, family, uuid, last_work_at),
    )
    return int(cur.lastrowid)


def _value(conn, row_id: int):
    return conn.execute("SELECT last_work_at FROM sessions WHERE id=?", (row_id,)).fetchone()[0]


def test_null_rows_get_the_newest_work_line_and_nothing_else_moves(state, corpus):
    project = corpus / PROJECT_DIR
    for other in (KEPT, CODEX):
        shutil.copy(project / f"{CONV}.jsonl", project / f"{other}.jsonl")
    with closing(connect(db_path_for(state))) as conn:
        worked = _row(conn, "cloude_worked", uuid=CONV)
        kept = _row(conn, "cloude_kept", uuid=KEPT, last_work_at="2020-01-01T00:00:00.000000Z")
        missing = _row(conn, "cloude_missing", uuid="00000000-0000-4000-8000-000000000000")
        codex = _row(conn, "cloude_codex", uuid=CODEX, family="codex")
        result = backfill_last_work_at(conn, projects_dir=corpus)
        assert _value(conn, worked) == "2026-09-26T11:40:01.000000Z"
        assert _value(conn, kept) == "2020-01-01T00:00:00.000000Z"
        assert _value(conn, missing) is None
        assert _value(conn, codex) is None
        assert (result.considered, result.stamped, result.no_transcript) == (2, 1, 1)
        again = backfill_last_work_at(conn, projects_dir=corpus)
        assert again.stamped == 0 and _value(conn, worked) == "2026-09-26T11:40:01.000000Z"


def test_a_transcript_with_no_work_line_leaves_the_row_null(state, tmp_path):
    corpus = tmp_path / "bare"
    project = corpus / PROJECT_DIR
    project.mkdir(parents=True)
    (project / f"{CONV}.jsonl").write_text(json.dumps({
        "type": "user", "timestamp": "2026-09-26T10:00:00.000Z",
        "message": {"role": "user", "content": "a prompt, not work"}}) + "\n")
    with closing(connect(db_path_for(state))) as conn:
        row = _row(conn, "cloude_idle", uuid=CONV)
        result = backfill_last_work_at(conn, projects_dir=corpus)
        assert _value(conn, row) is None
        assert result.no_work_line == 1


def test_what_counts_as_work():
    assert is_work({"type": "assistant"})
    assert is_work({"type": "user", "message": {"content": [{"type": "tool_result"}]}})
    assert not is_work({"type": "user", "message": {"content": "typed"}})
    assert not is_work({"type": "user", "isMeta": True,
                        "message": {"content": [{"type": "tool_result"}]}})
    assert not is_work({"type": "queue-operation"})


def test_the_boot_entry_point_never_raises_on_a_missing_database(tmp_path):
    assert run_boot_backfill(tmp_path / "nope.db") is None


def test_newest_rows_win_when_old_rows_without_evidence_fill_the_batch(state, corpus):
    with closing(connect(db_path_for(state))) as conn:
        dead = _row(conn, "cloude_dead", uuid="00000000-0000-4000-8000-000000000001")
        worked = _row(conn, "cloude_new_worked", uuid=CONV)
        backfill_last_work_at(conn, projects_dir=corpus, max_rows=1)
        assert _value(conn, worked) is not None
        assert _value(conn, dead) is None
