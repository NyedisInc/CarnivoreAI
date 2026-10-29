
import sqlite3

from src.core.db_models import META_SCHEMA_VERSION
from src.core.db_steps import run_chain
from src.core.flow_data.ddl import apply_v90

ROLLUP_TABLES = {"pack_rollups", "pack_rollup_counters", "pack_rollup_state"}


def _tables(conn: sqlite3.Connection) -> set:
    return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _at_88() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    run_chain(conn, 0, 88)
    return conn


def _version(conn: sqlite3.Connection) -> str:
    return conn.execute("SELECT value FROM meta WHERE key = ?", (META_SCHEMA_VERSION,)).fetchone()[0]


def test_a_database_stamped_89_by_the_old_flow_data_step_gains_the_rollup_tables():
    conn = _at_88()
    apply_v90(conn)
    conn.execute("UPDATE meta SET value = '89' WHERE key = ?", (META_SCHEMA_VERSION,))
    assert "agent_spawn_links" in _tables(conn) and not ROLLUP_TABLES & _tables(conn)
    run_chain(conn, 89, 90)
    assert ROLLUP_TABLES <= _tables(conn) and "agent_spawn_links" in _tables(conn)
    assert _version(conn) == "90"


def test_the_normal_path_88_to_90_yields_both():
    conn = _at_88()
    run_chain(conn, 88, 90)
    assert ROLLUP_TABLES <= _tables(conn) and {"agent_spawn_links", "mcp_events"} <= _tables(conn)
    assert _version(conn) == "90"


def test_a_database_that_took_the_rollup_v89_no_ops_on_it():
    conn = _at_88()
    run_chain(conn, 88, 89)
    run_chain(conn, 89, 90)
    assert ROLLUP_TABLES <= _tables(conn) and "agent_spawn_links" in _tables(conn)
