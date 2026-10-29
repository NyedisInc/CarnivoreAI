
from __future__ import annotations

from contextlib import closing
from pathlib import Path

from tests.datastore_helpers import ROOT  # noqa: F401

from src.core.db import connect, db_path_for, set_meta, transaction
from src.core.db_migration import ensure_db_migrated
from src.core.db_models import CURRENT_SCHEMA_VERSION
from src.core.db_state import (
    STATUS_DEGRADED_SCHEMA_AHEAD,
    STATUS_OK,
    TRAIL_STATUS_ABSENT,
    TRAIL_STATUS_OK,
    TRAIL_STATUS_PAUSED,
    TRAIL_STATUS_UNREADABLE,
    DatastoreState,
)


def _state(status: str, trail_status: str) -> DatastoreState:
    return DatastoreState(
        status=status,
        schema_version=1,
        config_version=4,
        trail_status=trail_status,
        code_schema_version=1,
        message="",
    )


def test_a_healthy_install_reports_what_it_measured() -> None:
    for measured in (TRAIL_STATUS_OK, TRAIL_STATUS_ABSENT):
        state = _state(STATUS_OK, measured)
        assert state.to_dict()["trail_status"] == measured
        assert state.to_dict()["trail_status_measured"] == measured


def test_an_intact_trail_on_a_frozen_install_reports_paused() -> None:
    state = _state(STATUS_DEGRADED_SCHEMA_AHEAD, TRAIL_STATUS_OK)
    block = state.to_dict()
    assert state.migrations_paused is True
    assert block["trail_status"] == TRAIL_STATUS_PAUSED
    assert block["trail_status_measured"] == TRAIL_STATUS_OK


def test_unreadable_always_wins_over_paused() -> None:
    state = _state(STATUS_DEGRADED_SCHEMA_AHEAD, TRAIL_STATUS_UNREADABLE)
    assert state.to_dict()["trail_status"] == TRAIL_STATUS_UNREADABLE


def test_restore_is_not_offered_while_the_trail_cannot_be_read() -> None:
    assert _state(STATUS_OK, TRAIL_STATUS_UNREADABLE).restore_offered is False
    assert _state(STATUS_OK, TRAIL_STATUS_OK).restore_offered is True


def test_code_below_schema_reaches_the_data_block_with_both_numbers(
    tmp_path: Path,
) -> None:
    ensure_db_migrated(tmp_path, 4, "0.8.2")
    ahead = CURRENT_SCHEMA_VERSION + 3
    with closing(connect(db_path_for(tmp_path))) as conn:
        with transaction(conn):
            set_meta(conn, "schema_version", str(ahead))

    block = ensure_db_migrated(tmp_path, 4, "0.8.2").to_dict()

    assert block["status"] == STATUS_DEGRADED_SCHEMA_AHEAD
    assert block["readonly"] is True
    assert block["healthy"] is False
    assert block["migrations_paused"] is True
    assert block["schema_version"] == ahead
    assert block["code_schema_version"] == CURRENT_SCHEMA_VERSION
    assert block["schema_version_state"] == "known"
    assert f"v{ahead}" in block["message"]
    assert f"v{CURRENT_SCHEMA_VERSION}" in block["message"]
    assert block["trail_status"] == TRAIL_STATUS_PAUSED
    assert block["trail_status_measured"] != TRAIL_STATUS_UNREADABLE
    assert block["detail"] is not None
    assert "Migrating backward is not attempted" in block["detail"]


def test_the_data_block_still_carries_every_field_the_design_names(
    tmp_path: Path,
) -> None:
    block = ensure_db_migrated(tmp_path, 4, "0.8.2").to_dict()
    for field in (
        "schema_version", "config_version", "trail_status",
        "last_migration_at",
    ):
        assert field in block, field
    assert block["schema_version"] == CURRENT_SCHEMA_VERSION
    assert block["config_version"] == 4
    assert block["last_migration_at"] is not None
