
from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import Awaitable, Callable, Optional, Tuple

import structlog

from src.core.catalog import client as catalog_client
from src.core.catalog.fetch_stream import FetchRefusal, fetch_document
from src.core.catalog.index_key_revocation import (
    FIRST_SERIAL_UNRECORDED,
    MAX_STATEMENT_BYTES,
    IndexKeyRevocation,
    active_trust_root,
    verify_index_key_revocation,
)
from src.core.catalog.log_safe import log_value
from src.core.catalog.publisher_key_chain import PublisherKeyChain
from src.core.catalog.trust_root import TrustRoot
from src.core.db import transaction

logger = structlog.get_logger(__name__)

KIND_INDEX_KEY_REVOKED = "index-key-revoked"

KIND_INDEX_KEY_FIRST_SERIAL = "index-key-first-serial"

STATEMENT_FILE_NAME = "index-key-revoked"

StatementFetch = Callable[[str], Awaitable[Optional[Tuple[bytes, str]]]]


def statement_url(index_url: str) -> str:
    return catalog_client.sibling_url(index_url, STATEMENT_FILE_NAME)


async def fetch_statement(index_url: str) -> Optional[Tuple[bytes, str]]:
    if catalog_client.refuse_index_url(index_url) is not None:
        return None
    url = statement_url(index_url)
    client = await catalog_client.shared_client()
    async with catalog_client.counted_fetch():
        body = await fetch_document(
            client, url, limit=MAX_STATEMENT_BYTES, url_kind="index-key-revoked",
        )
        if isinstance(body, FetchRefusal):
            return None
        sig = await fetch_document(
            client,
            catalog_client.minisig_url(url),
            limit=catalog_client.MAX_MINISIG_BYTES,
            url_kind="index-key-revoked minisig",
        )
    if isinstance(sig, FetchRefusal) or body[0] != 200 or sig[0] != 200:
        return None
    text = catalog_client.read_minisig(sig[1])
    if isinstance(text, FetchRefusal):
        return None
    return body[1], text


class IndexKeyRevocationStore:

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def for_key(self, revoked_key_id: str) -> Tuple[IndexKeyRevocation, ...]:
        rows = self._conn.execute(
            "SELECT kind, subject, since FROM catalog_revocations_seen "
            "WHERE index_key_id = ? AND kind IN (?, ?) ORDER BY subject",
            (revoked_key_id, KIND_INDEX_KEY_REVOKED, KIND_INDEX_KEY_FIRST_SERIAL),
        ).fetchall()
        serials = {
            str(row["subject"]): _stored_serial(str(row["since"]))
            for row in rows
            if row["kind"] == KIND_INDEX_KEY_FIRST_SERIAL
        }
        return tuple(
            IndexKeyRevocation(
                revoked_key_id=revoked_key_id,
                successor_key_id=str(row["subject"]),
                first_serial=serials.get(str(row["subject"]), FIRST_SERIAL_UNRECORDED),
                since=str(row["since"]),
            )
            for row in rows
            if row["kind"] == KIND_INDEX_KEY_REVOKED
        )

    def remember(self, revocation: IndexKeyRevocation) -> bool:
        insert = (
            "INSERT OR IGNORE INTO catalog_revocations_seen "
            "(index_key_id, kind, subject, since) VALUES (?, ?, ?, ?)"
        )
        with transaction(self._conn):
            cursor = self._conn.execute(
                insert,
                (
                    revocation.revoked_key_id,
                    KIND_INDEX_KEY_REVOKED,
                    revocation.successor_key_id,
                    revocation.since,
                ),
            )
            inserted = cursor.rowcount > 0
            self._conn.execute(
                insert,
                (
                    revocation.revoked_key_id,
                    KIND_INDEX_KEY_FIRST_SERIAL,
                    revocation.successor_key_id,
                    str(revocation.first_serial),
                ),
            )
        return inserted


def _stored_serial(text: str) -> int:
    if text.isascii() and text.isdigit() and int(text) > 0:
        return int(text)
    logger.error("catalog_index_key_first_serial_unreadable", stored=log_value(text))
    return FIRST_SERIAL_UNRECORDED


def _pick(
    rows: Tuple[IndexKeyRevocation, ...], trust_root: TrustRoot,
) -> Optional[IndexKeyRevocation]:
    spare = trust_root.spare_index_key
    for row in rows:
        if spare is not None and row.successor_key_id == spare.key_id:
            return row
    return rows[0] if rows else None


class IndexKeyChain:

    def __init__(
        self,
        *,
        trust_root: TrustRoot,
        open_db: Callable[[], sqlite3.Connection],
        fetch: StatementFetch = fetch_statement,
    ) -> None:
        self._pinned = trust_root
        self._open_db = open_db
        self._fetch = fetch
        self._accepted: Optional[IndexKeyRevocation] = None
        self._loaded = False
        self.publisher_chain = PublisherKeyChain(
            trust_root=trust_root, open_db=open_db,
        )

    def _load(self) -> None:
        live = self._pinned.index_key
        if self._loaded or self._accepted is not None or live is None:
            return
        try:
            with closing(self._open_db()) as conn:
                rows = IndexKeyRevocationStore(conn).for_key(live.key_id)
        except sqlite3.Error as exc:
            logger.warning("catalog_index_key_chain_unreadable", error=str(exc))
            return
        self._loaded = True
        self._accepted = _pick(rows, self._pinned)

    def active_root(self) -> TrustRoot:
        self._load()
        return self.publisher_chain.apply(
            active_trust_root(self._pinned, self._accepted)
        )

    def chain_key_ids(self) -> Tuple[str, ...]:
        self._load()
        ids = [] if self._pinned.index_key is None else [self._pinned.index_key.key_id]
        if self._accepted is not None:
            ids.append(self._accepted.successor_key_id)
        return tuple(ids)

    def _wants_statement(self) -> bool:
        self._load()
        return (
            self._accepted is None
            and self._pinned.index_key is not None
            and self._pinned.spare_index_key is not None
        )

    async def check(self, index_url: str) -> bool:
        publisher_moved = await self.publisher_chain.check(index_url)
        if not self._wants_statement():
            return publisher_moved
        fetched = await self._fetch(index_url)
        if fetched is None:
            return publisher_moved
        accepted = verify_index_key_revocation(fetched[0], fetched[1], self._pinned)
        if accepted is None:
            return publisher_moved
        self._accepted = accepted
        try:
            with closing(self._open_db()) as conn:
                IndexKeyRevocationStore(conn).remember(accepted)
        except sqlite3.Error as exc:
            logger.error(
                "catalog_index_key_revocation_not_persisted",
                error=str(exc),
                revoked_key_id=accepted.revoked_key_id,
            )
        logger.warning(
            "catalog_index_key_revoked",
            revoked_key_id=accepted.revoked_key_id,
            successor_key_id=accepted.successor_key_id,
            since=log_value(accepted.since),
        )
        return True
