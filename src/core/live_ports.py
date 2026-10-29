
from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

import structlog

from src.core.sessions.ports import (
    Clock,
    InstallRoots,
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
        """The application state directory that holds ``cloude.db``.

        Description: the suite points this at a throwaway directory via
          ``CLOUDE_STATE_DIR`` in ``tests/conftest.py``, so reading it
          through here is safe by two mechanisms rather than one.
        Inputs: none.
        Output: Path.
        Example: LiveSettings().state_dir() / 'cloude.db'
        """
        return Path(self._settings().get_state_dir())

    def session_metadata_path(self) -> Path:
        return self._settings().get_session_metadata_path()


class LiveSessionRecordStore:
    """The real ``cloude.db``, satisfying :class:`SessionRecordStore`.

    Description: the two connection vendors are the manager's
      ``_datastore_connection`` and ``_writable_datastore_connection``
      moved behind a port, byte-for-byte in behaviour including their
      failure posture. Neither creates the file, both answer None rather
      than raising, and the log level differs between them for the same
      reason it always has: a render-path miss is debug, an adopt-path
      miss is a warning the user may need to act on.
    Inputs: settings_reader (SettingsReader) - where the state directory
      comes from. Required, keyword-only: a default here would be a
      second way to find the database.
    Output: none.
    Example: LiveSessionRecordStore(settings_reader=LiveSettings())

    NOTHING CALLS THIS YET, and that is deliberate for S0, whose whole
    claim is that no behaviour moves. The manager keeps its own private
    helpers until the slice that owns those call sites migrates them.
    Two spellings of one read is exactly the drift this plan is about, so
    that slice DELETES the private pair rather than leaving both.
    """

    def __init__(self, *, settings_reader: SettingsReader) -> None:
        """Bind the store to a way of finding the state directory.

        Inputs: settings_reader (SettingsReader).
        Output: None.
        Example: LiveSessionRecordStore(settings_reader=LiveSettings())
        """
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

    def read_connection(self) -> Optional[sqlite3.Connection]:
        return self._open(warn=False)

    def write_connection(self) -> Optional[sqlite3.Connection]:
        return self._open(warn=True)

    def get_instance(
        self, *, socket: str, name: str, epoch: Optional[int]
    ) -> Optional[dict[str, Any]]:
        """The ``sessions`` row for one tmux instance triple, or None.

        Description: opens its own read connection and closes it, so a
          caller never holds one. A datastore that cannot be opened
          yields None, which every caller in this codebase reads as "not
          having been able to look" rather than as "there is no row".
        Inputs: socket (str) - the tmux socket name. name (str) - the
          literal tmux session name. epoch (int | None) - the instance's
          ``#{session_created}``.
        Output: dict[str, Any] | None.
        Example: store.get_instance(socket='cloude', name='cloude_x', epoch=17)
        """
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
            try:
                conn.close()
            except sqlite3.Error as exc:
                logger.debug("record_store_close_failed", error=str(exc))


from src.core.live_install_roots import (  # noqa: E402,F401
    AGENTS_DIR_NAME,
    CLAUDE_DIR_NAME,
    CODEX_DIR_NAME,
    CODEX_HOME_ENV_VAR,
    HARNESS_CLAUDE,
    HARNESS_CODEX,
    KIND_SKILL,
    PENDING_DIR_NAME,
    REQUIRED_MANIFEST,
    SCOPE_GLOBAL,
    SCOPE_PROJECT,
    SKILLS_DIR_NAME,
    STAGING_DIR_NAME,
    TRASH_DIR_NAME,
    LiveInstallRoots,
)


_PORT_IMPLEMENTATIONS: tuple[tuple[type, type], ...] = (
    (SystemClock, Clock),
    (LiveSettings, SettingsReader),
    (LiveSessionRecordStore, SessionRecordStore),
    (LiveInstallRoots, InstallRoots),
)
