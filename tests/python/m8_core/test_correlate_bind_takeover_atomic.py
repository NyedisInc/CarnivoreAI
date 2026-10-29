from __future__ import annotations

from contextlib import closing

import pytest

from src.core.db import transaction
from src.core.db_models import SESSION_ORIGIN_ADOPTED
from src.core.session_claude_correlate_bind import BIND_UNRESOLVED, bind_correlated_uuid
from src.core.session_identity import record_instance
from tests.s7_helpers import TEST_SOCKET, migrated_connection, session_row

EPOCH = 1_800_000_000
UUID_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


@pytest.fixture()
def conn(tmp_path):
    with closing(migrated_connection(tmp_path)) as connection:
        yield connection


def test_integrity_error_after_release_leaves_the_holder_bound(conn) -> None:
    with transaction(conn):
        target = record_instance(conn, socket=TEST_SOCKET, name="m8_target", epoch=EPOCH,
                                 origin=SESSION_ORIGIN_ADOPTED)
        holder = record_instance(conn, socket=TEST_SOCKET, name="m8_holder", epoch=EPOCH + 1,
                                 origin=SESSION_ORIGIN_ADOPTED)
        bind_correlated_uuid(conn, socket=TEST_SOCKET, name="m8_holder", epoch=EPOCH + 1, claude_uuid=UUID_B)
        conn.execute(
            "CREATE TRIGGER m8_race BEFORE UPDATE OF claude_session_uuid ON sessions "
            f"WHEN NEW.id = {target.session_id} BEGIN SELECT RAISE(ABORT, 'raced'); END"
        )
    with transaction(conn):
        result = bind_correlated_uuid(conn, socket=TEST_SOCKET, name="m8_target", epoch=EPOCH,
                                      claude_uuid=UUID_B, takes_from_row_id=holder.session_id)
    assert result.outcome == BIND_UNRESOLVED
    assert session_row(conn, "m8_holder")["claude_session_uuid"] == UUID_B, "the release survived the failed bind"
    assert session_row(conn, "m8_target")["claude_session_uuid"] is None
