
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Optional

import structlog

from src.core.safe_io.atomic_write import DEFAULT_PARENT_MODE, atomic_write_text
from src.core.db_reuse.change_cache import ChangeCache, main_file

from src.core.sessions.ports import SessionRecordStore

DB_INSTANCES_UNSET: Any = object()

logger = structlog.get_logger()

_OWNED_READS = ChangeCache()


class MetadataLoad:

    __slots__ = ("session", "owned_count")

    def __init__(self, *, session: Optional[dict[str, Any]], owned_count: int) -> None:
        self.session = session
        self.owned_count = owned_count


class OwnedTmuxLedger:

    def __init__(
        self,
        *,
        metadata_path: Callable[[], Path],
        records: SessionRecordStore,
        socket_name: Callable[[], str],
    ) -> None:
        self._metadata_path = metadata_path
        self._records = records
        self._socket_name = socket_name

        self.names: set[str] = set()

        self.needs_legacy_backfill: bool = False

        self.boot_listing: Any = None


    def path(self) -> Path:
        return self._metadata_path()

    def write_atomic(self, data: dict) -> None:
        atomic_write_text(
            self.path(), json.dumps(data, indent=2, default=str), parent_mode=DEFAULT_PARENT_MODE,
            tolerate_fsync_unsupported=True,
        )

    def load(self) -> MetadataLoad:
        metadata_path = self.path()

        if not metadata_path.exists():
            logger.info("no_existing_session_metadata")
            return MetadataLoad(session=None, owned_count=len(self.names))

        try:
            with open(metadata_path, "r") as f:
                raw = json.load(f)

            owned = raw.pop("owned_tmux_sessions", None)

            if not raw.get("id"):
                self.names = set(owned or [])
                self.needs_legacy_backfill = False
                logger.info(
                    "session_metadata_owned_set_only_loaded",
                    owned_count=len(self.names),
                    note="no persisted session to rehydrate",
                )
                return MetadataLoad(session=None, owned_count=len(self.names))

            if owned is None:
                self.names = set()
                self.needs_legacy_backfill = True
                logger.info(
                    "session_metadata_legacy_detected",
                    session_id=raw.get("id"),
                    note="owned_tmux_sessions will be backfilled on rehydrate",
                )
            else:
                self.names = set(owned)
                self.needs_legacy_backfill = False

            return MetadataLoad(session=raw, owned_count=len(self.names))
        except (OSError, ValueError, TypeError) as exc:
            logger.error("failed_to_load_session_metadata", error=str(exc))
            return MetadataLoad(session=None, owned_count=len(self.names))

    def save(self, payload: dict) -> bool:
        try:
            payload["owned_tmux_sessions"] = sorted(self.names)
            self.write_atomic(payload)
            self.needs_legacy_backfill = False
            logger.debug(
                "session_metadata_saved",
                session_id=payload.get("id"),
                owned_count=len(self.names),
            )
            return True
        except (OSError, ValueError, TypeError) as exc:
            logger.error("failed_to_save_session_metadata", error=str(exc))
            return False

    def drop_session_pointer(self) -> None:
        metadata_path = self.path()
        try:
            if metadata_path.exists():
                metadata_path.unlink()
                logger.info("stale_session_metadata_deleted")
            if self.names:
                self.write_atomic({"owned_tmux_sessions": sorted(self.names)})
                logger.info(
                    "stale_session_metadata_owned_set_kept",
                    owned_count=len(self.names),
                )
        except (OSError, ValueError, TypeError) as exc:
            logger.error("failed_to_delete_stale_metadata", error=str(exc))


    def instances_from_db(self) -> Optional[set]:
        socket = self._socket_name()
        found = _OWNED_READS.fetch_opened(self._records, ("owned_instances", socket), lambda: self._read_instances(socket))
        return None if found is None else set(found)

    def _read_instances(self, socket: str) -> tuple:
        conn = self._records.read_connection()
        if conn is None:
            return None, None
        try:
            from src.core.session_store import owned_instances, sessions_table_ready

            if not sessions_table_ready(conn):
                return None, None
            return frozenset(owned_instances(conn, socket=socket)), main_file(conn)
        except Exception as exc:  # noqa: BLE001
            logger.debug("ownership_db_read_failed", error=str(exc))
            return None, None
        finally:
            conn.close()

    def instances(self) -> Optional[set]:
        from_db = self.instances_from_db()
        if from_db is None:
            return None
        return set(from_db)

    def is_owned_name(self, name: Optional[str], *, db_instances: Any = DB_INSTANCES_UNSET) -> bool:
        if not name:
            return False
        if name in self.names:
            return True
        from_db = self.instances_from_db() if db_instances is DB_INSTANCES_UNSET else db_instances
        if from_db is None:
            return False
        return any(owned_name == name for owned_name, _epoch in from_db)
