
from __future__ import annotations

import os
import sys
from contextlib import closing
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("DEFAULT_WORKING_DIR", "/tmp")
os.environ.setdefault("LOG_DIRECTORY", "/tmp")
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core.claude_resume_argv import ProcessRow
from src.core.db import transaction
from src.core.db_models import (
    SESSION_CLAUDE_UUID_SOURCE_CORRELATED_ARGV,
    SESSION_ORIGIN_CREATED,
)
from src.core.session_identity import record_instance
from src.core.session_lineage_recovery import (
    RECOVERY_BOUND,
    RECOVERY_NOT_ATTEMPTED,
    RECOVERY_NO_MATCH,
    recover_claude_uuid,
)
from tests.s7_helpers import TEST_SOCKET, migrated_connection, session_row

NAME = "cloudes7test_recover"
EPOCH = 1_800_000_000
PANE_PID = 4242
UUID = "cccccccc-cccc-cccc-cccc-cccccccccccc"


@pytest.fixture()
def conn(tmp_path):
    with closing(migrated_connection(tmp_path)) as connection:
        yield connection


@pytest.fixture()
def anchor(conn):
    with transaction(conn):
        result = record_instance(
            conn,
            socket=TEST_SOCKET,
            name=NAME,
            epoch=EPOCH,
            origin=SESSION_ORIGIN_CREATED,
            working_dir="/tmp/proj",
        )
    return result.session_id


def _argv_table(uuid: str = UUID):
    return [
        ProcessRow(pid=PANE_PID, ppid=1, command="-zsh"),
        ProcessRow(
            pid=PANE_PID + 1,
            ppid=PANE_PID,
            command=f"/Users/x/.local/bin/claude --dangerously-skip-permissions --resume {uuid}",
        ),
    ]


def test_the_panes_own_argv_recovers_the_uuid_the_hook_lost(conn, anchor, tmp_path):
    with transaction(conn):
        outcome, uuid = recover_claude_uuid(
            conn,
            socket=TEST_SOCKET,
            tmux_name=NAME,
            tmux_created_epoch=EPOCH,
            working_dir="/tmp/proj",
            pane_pid=PANE_PID,
            projects_dir=tmp_path / "projects",
            process_table=_argv_table(),
        )

    assert outcome == RECOVERY_BOUND
    assert uuid == UUID
    row = session_row(conn, NAME)
    assert row["claude_session_uuid"] == UUID
    assert (
        row["claude_session_uuid_source"] == SESSION_CLAUDE_UUID_SOURCE_CORRELATED_ARGV
    ), "argv evidence must be labelled as argv, not as a hook write"


def test_recovery_abstains_when_there_is_no_evidence(conn, anchor, tmp_path):
    with transaction(conn):
        outcome, uuid = recover_claude_uuid(
            conn,
            socket=TEST_SOCKET,
            tmux_name=NAME,
            tmux_created_epoch=EPOCH,
            working_dir="/tmp/proj",
            pane_pid=PANE_PID,
            projects_dir=tmp_path / "projects",
            process_table=[ProcessRow(pid=PANE_PID, ppid=1, command="-zsh")],
        )

    assert outcome == RECOVERY_NO_MATCH
    assert uuid is None
    assert session_row(conn, NAME)["claude_session_uuid"] is None


def test_recovery_never_writes_a_uuid_another_row_already_claims(
    conn, anchor, tmp_path
):
    other = "cloudes7test_other"
    with transaction(conn):
        record_instance(
            conn,
            socket=TEST_SOCKET,
            name=other,
            epoch=EPOCH + 1,
            origin=SESSION_ORIGIN_CREATED,
        )
        from src.core.session_claude_correlate_bind import bind_correlated_uuid

        bind_correlated_uuid(
            conn, socket=TEST_SOCKET, name=other, epoch=EPOCH + 1, claude_uuid=UUID
        )

    with transaction(conn):
        outcome, uuid = recover_claude_uuid(
            conn,
            socket=TEST_SOCKET,
            tmux_name=NAME,
            tmux_created_epoch=EPOCH,
            working_dir="/tmp/proj",
            pane_pid=PANE_PID,
            projects_dir=tmp_path / "projects",
            process_table=_argv_table(),
        )

    assert outcome == RECOVERY_NO_MATCH
    assert session_row(conn, NAME)["claude_session_uuid"] is None
    assert session_row(conn, other)["claude_session_uuid"] == UUID


def test_recovery_without_a_tmux_name_is_not_attempted(conn):
    outcome, uuid = recover_claude_uuid(
        conn,
        socket=TEST_SOCKET,
        tmux_name="",
        tmux_created_epoch=EPOCH,
        working_dir="/tmp/proj",
        pane_pid=None,
    )
    assert outcome == RECOVERY_NOT_ATTEMPTED
    assert uuid is None


def test_recovery_never_raises_when_the_binder_explodes(conn, anchor, tmp_path):

    def _boom(*_args, **_kwargs):
        raise RuntimeError("binder exploded")

    with transaction(conn):
        outcome, uuid = recover_claude_uuid(
            conn,
            socket=TEST_SOCKET,
            tmux_name=NAME,
            tmux_created_epoch=EPOCH,
            working_dir="/tmp/proj",
            pane_pid=PANE_PID,
            projects_dir=tmp_path / "projects",
            process_table=_argv_table(),
            bind=_boom,
        )

    assert outcome == RECOVERY_NO_MATCH
    assert uuid is None
