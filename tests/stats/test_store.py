from pathlib import Path

import pytest

from src.core.pipeline import contract as PK
from src.core.pipeline import plugin_db as host
from src.core.stats.plugin.pipeline_plugin import STATS as STATS_PLUGIN
from src.core.stats.store import StatsStore
from tests.stats import seed


def test_the_store_is_the_plugin_database_and_keeps_rows_across_starts(tmp_path: Path):
    store = StatsStore(tmp_path)
    store.initialize()
    assert store.db_path == tmp_path / PK.PLUGIN_DIR / "stats.db"
    assert not (tmp_path / "cloude.db").exists() and not (tmp_path / "cloude-stats.db").exists()
    with store.connect() as conn:
        seed.execute(conn, "INSERT INTO minute_usage VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (60, "local", "claude", "conversation", "project", "model", "session",
                      1, 2, 3, 4, None, None, 1, 0, 1, "ok"))
    store.initialize()
    with store.connect(readonly=True) as conn:
        row = conn.execute("SELECT * FROM minute_usage").fetchone()
        assert row["output_tokens"] == 4 and row["estimated_cost_nano_usd"] is None
        assert row["unpriced_usage_count"] == 1


def test_a_newer_plugin_schema_is_refused(tmp_path: Path):
    store = StatsStore(tmp_path)
    store.initialize()
    with store.connect() as conn:
        conn.execute("UPDATE plugin_meta SET value = '99' WHERE key = 'schema_version'")
    with pytest.raises(RuntimeError, match="newer"):
        store.initialize()
    assert host.db_path(tmp_path, STATS_PLUGIN).exists()
