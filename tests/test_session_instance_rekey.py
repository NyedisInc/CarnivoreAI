
from __future__ import annotations

import os
import sys
from contextlib import closing
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DEFAULT_WORKING_DIR", "/tmp")

from src.core.db import connect, db_path_for  # noqa: E402
from src.core.db_models import SESSION_ORIGIN_OBSERVED  # noqa: E402
from src.core.session_identity import record_instance  # noqa: E402
from src.core.session_instance_rekey import (  # noqa: E402
    IDENTITY_CANNOT_DETERMINE,
    IDENTITY_REKEYED,
    IDENTITY_UNCHANGED,
    parse_epoch,
    reconcile_instance_epoch,
)
from tests.s7_helpers import migrated_connection  # noqa: E402

SOCKET = "cloude_pytest_rekey"


@pytest.fixture()
def db(tmp_path):
    db_dir = tmp_path / "state"
    db_dir.mkdir()
    with closing(migrated_connection(db_dir)):
        pass
    name = "cloude_rekey"
    epoch = 1788821572
    with closing(connect(db_path_for(db_dir))) as conn:
        record_instance(
            conn,
            socket=SOCKET,
            name=name,
            epoch=epoch,
            origin=SESSION_ORIGIN_OBSERVED,
        )
        conn.commit()
    return db_dir, name, epoch


def _epoch_of(db_dir: Path, name: str):
    with closing(connect(db_path_for(db_dir))) as conn:
        row = conn.execute(
            "SELECT tmux_created_epoch FROM sessions WHERE tmux_name = ?",
            (name,),
        ).fetchone()
    return None if row is None else row["tmux_created_epoch"]


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1788821572", 1788821572),
        ("  1788821572\n", 1788821572),
        ("", None),
        ("   ", None),
        (None, None),
        ("not-a-number", None),
        ("-5", None),
    ],
)
def test_an_unreadable_epoch_is_none_and_never_zero(raw, expected):
    assert parse_epoch(raw) == expected


def test_matching_epochs_write_nothing(db):
    db_dir, name, epoch = db
    with closing(connect(db_path_for(db_dir))) as conn:
        status, rows = reconcile_instance_epoch(
            conn,
            socket=SOCKET,
            tmux_name=name,
            epoch_before=epoch,
            epoch_after=epoch,
        )
    assert (status, rows) == (IDENTITY_UNCHANGED, 0)
    assert _epoch_of(db_dir, name) == epoch


def test_a_moved_epoch_moves_the_row_with_it(db):
    db_dir, name, epoch = db
    moved = epoch + 1000
    with closing(connect(db_path_for(db_dir))) as conn:
        status, rows = reconcile_instance_epoch(
            conn,
            socket=SOCKET,
            tmux_name=name,
            epoch_before=epoch,
            epoch_after=moved,
        )
    assert status == IDENTITY_REKEYED
    assert rows == 1
    assert _epoch_of(db_dir, name) == moved


def test_the_rekey_matches_the_old_triple_and_not_the_name(db):
    db_dir, name, epoch = db
    with closing(connect(db_path_for(db_dir))) as conn:
        status, rows = reconcile_instance_epoch(
            conn,
            socket=SOCKET,
            tmux_name=name,
            epoch_before=epoch + 5555,
            epoch_after=epoch + 9999,
        )
    assert (status, rows) == (IDENTITY_UNCHANGED, 0)
    assert _epoch_of(db_dir, name) == epoch, (
        "a row was re-keyed on a triple the caller never observed"
    )


@pytest.mark.parametrize(
    "before,after",
    [(None, 1), (1, None), (None, None)],
)
def test_an_unread_epoch_is_cannot_determine_not_unchanged(db, before, after):
    db_dir, name, epoch = db
    with closing(connect(db_path_for(db_dir))) as conn:
        status, rows = reconcile_instance_epoch(
            conn,
            socket=SOCKET,
            tmux_name=name,
            epoch_before=before,
            epoch_after=after,
        )
    assert status == IDENTITY_CANNOT_DETERMINE
    assert rows == 0
    assert _epoch_of(db_dir, name) == epoch


def test_a_moved_epoch_with_no_database_is_cannot_determine(db):
    _db_dir, name, epoch = db
    status, rows = reconcile_instance_epoch(
        None,
        socket=SOCKET,
        tmux_name=name,
        epoch_before=epoch,
        epoch_after=epoch + 1,
    )
    assert (status, rows) == (IDENTITY_CANNOT_DETERMINE, 0)


def test_no_row_at_all_is_not_a_fault(db):
    db_dir, _name, epoch = db
    with closing(connect(db_path_for(db_dir))) as conn:
        status, rows = reconcile_instance_epoch(
            conn,
            socket=SOCKET,
            tmux_name="a_name_this_database_has_never_seen",
            epoch_before=epoch,
            epoch_after=epoch + 1,
        )
    assert (status, rows) == (IDENTITY_UNCHANGED, 0)
