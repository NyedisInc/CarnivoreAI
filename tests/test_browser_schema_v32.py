
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_brw_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_brw_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
import sqlite3
from contextlib import closing

from src.core import db_models
from src.core.archive_db_partition import SIDE_APP, side_for_table
from src.core.browser_sessions_ddl import DDL_V32, REVERSAL_SQL_V32
from src.core.browsers import store
from src.core.db import connect, db_path_for, get_schema_version, table_exists
from src.core.db_migration import ensure_db_migrated
from src.core.db_schema_audit import UNGATED_VERSION_DDL
from src.core.db_steps import STEPS


def test_a_fresh_install_reaches_v32_with_the_table(tmp_path):
    assert ensure_db_migrated(tmp_path).status == "ok"
    with closing(connect(db_path_for(tmp_path), create=False)) as conn:
        assert get_schema_version(conn) == db_models.CURRENT_SCHEMA_VERSION >= 32
        assert table_exists(conn, "browser_sessions")
        with conn:
            store.insert(conn, "0123456789abcdef", "example.com", "https://example.com/")
        assert store.get(conn, "0123456789abcdef").label == "example.com"


def test_a_v31_database_steps_forward_and_the_step_is_idempotent():
    conn = sqlite3.connect(":memory:")
    STEPS[31](conn)
    STEPS[31](conn)
    assert table_exists(conn, "browser_sessions")


def test_the_audit_repairs_it_and_the_split_keeps_it_in_main():
    assert UNGATED_VERSION_DDL[32] == DDL_V32
    assert side_for_table("browser_sessions") == SIDE_APP


def test_the_reversal_drops_exactly_the_table_and_says_so():
    assert db_models.REVERSAL_SQL_V32 == REVERSAL_SQL_V32
    assert db_models.REVERSAL_DESTROYS[32] == ("browser_sessions (whole table)",)
    conn = sqlite3.connect(":memory:")
    for statement in DDL_V32:
        conn.execute(statement)
    for statement in REVERSAL_SQL_V32:
        conn.execute(statement)
    assert not table_exists(conn, "browser_sessions")
