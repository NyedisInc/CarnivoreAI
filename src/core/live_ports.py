
from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

import structlog

from src.core.live_install_roots import LiveInstallRoots
from src.core.sessions.ports import (
    Clock,
    InstallRoots,
    ReadConnection,
    SessionRecordStore,
    SettingsReader,
)

logger = structlog.get_logger()


class SystemClock:

    def now(self) -> float:
        return time.time()

    def monotonic(self) -> float:
        return time.monotonic()


class LiveSettings:

    @staticmethod
    def _settings() -> Any:
        from src.core import session_manager

        return session_manager.settings

    def pinned_themes_path(self) -> Path:
        return self._settings().get_pinned_themes_path()

    def log_buffer_size(self) -> int:
        return self._settings().log_buffer_size

    def state_dir(self) -> Path:
        return Path(self._settings().get_state_dir())

    def session_metadata_path(self) -> Path:
        return self._settings().get_session_metadata_path()


class LiveSessionRecordStore:

    def __init__(self, *, settings_reader: SettingsReader) -> None:
        self._settings_reader = settings_reader

    def _open(self, *, warn: bool) -> Optional[sqlite3.Connection]:
        try:
            from src.core.db import connect, db_path_for

            path = db_path_for(self._settings_reader.state_dir())
            if not Path(path).exists():
                return None
            return connect(path, create=False)
        except (sqlite3.Error, OSError, ImportError, AttributeError) as exc:
            if warn:
                logger.warning("record_store_unavailable", error=str(exc))
            else:
                logger.debug("record_store_unavailable", error=str(exc))
            return None

    def read_connection(self) -> Optional[ReadConnection]:
        try:
            from src.core.db import db_path_for
            from src.core.db_reuse.core_read import lend_pooled_read

            lent = lend_pooled_read(db_path_for(self._settings_reader.state_dir()))
        except (sqlite3.Error, OSError, ImportError, AttributeError) as exc:
            logger.debug("record_store_unavailable", error=str(exc))
            return None
        return lent

    def write_connection(self) -> Optional[sqlite3.Connection]:
        return self._open(warn=True)

    def get_instance(
        self, *, socket: str, name: str, epoch: Optional[int]
    ) -> Optional[dict[str, Any]]:
        conn = self.read_connection()
        if conn is None:
            return None
        try:
            from src.core.session_store import get_instance

            return get_instance(conn, socket=socket, name=name, epoch=epoch)
        except sqlite3.Error as exc:
            logger.debug("record_store_row_read_failed", error=str(exc))
            return None
        finally:
            conn.close()


_PORT_IMPLEMENTATIONS: tuple[tuple[type, type], ...] = (
    (SystemClock, Clock),
    (LiveSettings, SettingsReader),
    (LiveSessionRecordStore, SessionRecordStore),
    (LiveInstallRoots, InstallRoots),
)
