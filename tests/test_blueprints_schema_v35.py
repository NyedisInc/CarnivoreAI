
from __future__ import annotations

import sqlite3
from contextlib import closing

from tests.layouts_helpers import migrated

# ruff: noqa: E402
from src.core import blueprints_store as store
from src.core import db_models
from src.core.archive_db_partition import SIDE_APP, side_for_table
from src.core.blueprints_ddl import DDL_V35, REVERSAL_SQL_V35
from src.core.db import connect, get_schema_version, table_exists
from src.core.db_schema_audit import UNGATED_VERSION_DDL
from src.core.db_steps import STEPS
from src.models.blueprints import BlueprintSpec


def _spec(name: str) -> BlueprintSpec:
    return BlueprintSpec.model_validate({"name": name, "sessions": [
        {"label": "a", "family": "claude", "folder": {"mode": "existing", "path": "/x"}}]})


def test_a_fresh_install_reaches_v35_with_the_table(tmp_path):
    with closing(connect(migrated(tmp_path / "s"), create=False)) as conn:
        assert get_schema_version(conn) == db_models.CURRENT_SCHEMA_VERSION >= 35
        assert table_exists(conn, "blueprints")


def test_a_v34_database_steps_up_idempotently(tmp_path):
    conn = sqlite3.connect(":memory:")
    STEPS[34](conn)
    STEPS[34](conn)
    assert table_exists(conn, "blueprints")


def test_the_step_is_audited_partitioned_and_its_reversal_declared():
    assert UNGATED_VERSION_DDL[35] == DDL_V35
    assert side_for_table("blueprints") == SIDE_APP
    assert db_models.REVERSAL_SQL_V35 == REVERSAL_SQL_V35
    assert db_models.REVERSAL_DESTROYS[35] == ("blueprints (whole table)",)


def test_the_reversal_steps_down_and_the_store_reports_unavailable(tmp_path):
    with closing(connect(migrated(tmp_path / "s"), create=False)) as conn:
        store.create_blueprint(conn, _spec("team"))
        for statement in REVERSAL_SQL_V35:
            conn.execute(statement)
        assert not table_exists(conn, "blueprints")
        try:
            store.list_blueprints(conn)
        except store.BlueprintsUnavailable:
            pass
        else:
            raise AssertionError("an absent table must not read as no blueprints")


def test_names_are_unique_ignoring_case_in_the_table_itself(tmp_path):
    with closing(connect(migrated(tmp_path / "s"), create=False)) as conn:
        store.create_blueprint(conn, _spec("Team"))
        try:
            conn.execute("INSERT INTO blueprints (blueprint_uuid, name, name_fold, spec, "
                         "created_at, updated_at) VALUES ('u', 'TEAM', 'team', '{}', 'n', 'n')")
        except sqlite3.IntegrityError:
            return
        raise AssertionError("name_fold must be UNIQUE")
