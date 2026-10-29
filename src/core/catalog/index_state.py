
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Iterable, Optional

import structlog

from src.core.catalog.log_safe import log_value
from src.core.catalog.revocation import KIND_KEY, KIND_VERSION, RevocationRef
from src.core.db import transaction

logger = structlog.get_logger()


@dataclass(frozen=True)
class IndexState:

    last_verified_serial: int
    last_verified_at: str
    etag: Optional[str]


class IndexStateStore:

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def get(self, index_key_id: str) -> Optional[IndexState]:
        row = self._conn.execute(
            "SELECT last_verified_serial, last_verified_at, etag "
            "FROM catalog_index_state WHERE index_key_id = ?",
            (index_key_id,),
        ).fetchone()
        if row is None:
            return None
        return IndexState(
            last_verified_serial=int(row["last_verified_serial"]),
            last_verified_at=str(row["last_verified_at"]),
            etag=None if row["etag"] is None else str(row["etag"]),
        )

    def record(
        self,
        index_key_id: str,
        serial: int,
        at: str,
        etag: Optional[str] = None,
    ) -> IndexState:
        with transaction(self._conn):
            current = self.get(index_key_id)
            if current is not None and serial < current.last_verified_serial:
                logger.warning(
                    "catalog_index_serial_not_lowered",
                    index_key_id=log_value(index_key_id),
                    offered_serial=serial,
                    stored_serial=current.last_verified_serial,
                )
                return current
            self._conn.execute(
                "INSERT INTO catalog_index_state "
                "(index_key_id, last_verified_serial, last_verified_at, etag) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(index_key_id) DO UPDATE SET "
                "last_verified_serial = excluded.last_verified_serial, "
                "last_verified_at = excluded.last_verified_at, "
                "etag = excluded.etag",
                (index_key_id, int(serial), at, etag),
            )
        return IndexState(
            last_verified_serial=int(serial),
            last_verified_at=at,
            etag=etag,
        )


class RevocationStore:

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def seen(self, index_key_id: str) -> frozenset[RevocationRef]:
        rows = self._conn.execute(
            "SELECT kind, subject, since FROM catalog_revocations_seen "
            "WHERE index_key_id = ? AND kind IN (?, ?)",
            (index_key_id, KIND_KEY, KIND_VERSION),
        ).fetchall()
        return frozenset(
            RevocationRef(
                kind=str(row["kind"]),
                subject=str(row["subject"]),
                since=str(row["since"]),
            )
            for row in rows
        )

    def remember(
        self, index_key_id: str, refs: Iterable[RevocationRef]
    ) -> int:
        inserted = 0
        with transaction(self._conn):
            for ref in refs:
                cursor = self._conn.execute(
                    "INSERT OR IGNORE INTO catalog_revocations_seen "
                    "(index_key_id, kind, subject, since) VALUES (?, ?, ?, ?)",
                    (index_key_id, ref.kind, ref.subject, ref.since),
                )
                inserted += max(cursor.rowcount, 0)
        if inserted:
            logger.info(
                "catalog_revocations_persisted",
                index_key_id=log_value(index_key_id),
                inserted=inserted,
            )
        return inserted
