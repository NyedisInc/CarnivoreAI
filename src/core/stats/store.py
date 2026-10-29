
from __future__ import annotations

import sqlite3
from pathlib import Path

import structlog

from src.core.safe_io.readonly_db import READONLY_TIMEOUT_DEFAULT_S, connect_readonly
from src.core.db_reuse.pooled_read import ReadPool

logger = structlog.get_logger()


class _ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def _open_read_only(path: Path) -> sqlite3.Connection:
    conn = connect_readonly(path, timeout=READONLY_TIMEOUT_DEFAULT_S)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


_READS = ReadPool(_open_read_only)


class StatsStore:

    def __init__(self, state_dir: Path):
        from src.core.pipeline import plugin_db
        from src.core.stats.plugin.pipeline_plugin import STATS

        self.state_dir = Path(state_dir)
        self.db_path = plugin_db.db_path(self.state_dir, STATS)

    def initialize(self) -> None:
        from src.core.pipeline import plugin_db
        from src.core.db import transaction
        from src.core.stats.plugin import carry, revision
        from src.core.stats.plugin.pipeline_plugin import STATS

        self.state_dir.mkdir(parents=True, exist_ok=True)
        with plugin_db.lock_for(STATS.id):
            try:
                conn = plugin_db.open_db(self.state_dir, STATS)
            except plugin_db.PluginUnavailable as exc:
                raise RuntimeError(f"stats database unavailable: {exc}") from exc
            try:
                carry.retire_legacy(self.state_dir, conn)
                self._close_stale_backfills(conn)
                with transaction(conn):
                    revision.ensure(conn)
            finally:
                conn.close()

    def _close_stale_backfills(self, conn: sqlite3.Connection) -> None:
        from src.core.db import transaction
        from src.core.stats.plugin import carry

        with transaction(conn):
            closed = carry.close_open_backfills(conn)
        if closed:
            logger.info("stats_stale_backfills_closed", rows=closed)

    def connect(self, *, readonly: bool = False) -> sqlite3.Connection:
        if readonly:
            conn = connect_readonly(self.db_path, timeout=READONLY_TIMEOUT_DEFAULT_S, factory=_ClosingConnection)
        else:
            conn = sqlite3.connect(self.db_path, timeout=5, factory=_ClosingConnection)
        try:
            if not readonly:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=5000")
        except sqlite3.Error:
            conn.close()
            raise
        return conn

    def connect_read(self) -> sqlite3.Connection:
        return _READS.lend(self.db_path)  # type: ignore[return-value]

    def discard_read(self) -> None:
        _READS.forget(self.db_path)

    def revision(self) -> int:
        with self.connect(readonly=True) as conn:
            return int(conn.execute("SELECT value FROM stats_meta WHERE key='revision'").fetchone()[0])
