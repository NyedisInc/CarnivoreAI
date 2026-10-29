
from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import Awaitable, Callable, Optional, Tuple

import structlog

from src.core.catalog import client as catalog_client
from src.core.catalog.fetch_stream import FetchRefusal, fetch_document
from src.core.catalog.log_safe import log_value
from src.core.catalog.publisher_key_revocation import (
    MAX_STATEMENT_BYTES,
    PublisherKeyRevocation,
    apply_publisher_revocation,
    verify_publisher_key_revocation,
)
from src.core.catalog.trust_root import TrustRoot

logger = structlog.get_logger(__name__)

KIND_PUBLISHER_KEY_REVOKED = "publisher-key-revoked"

StatementFetch = Callable[[str], Awaitable[Optional[Tuple[bytes, str]]]]

STATEMENT_FILE_NAME = "publisher-key-revoked"


async def fetch_statement(index_url: str) -> Optional[Tuple[bytes, str]]:
    if catalog_client.refuse_index_url(index_url) is not None:
        return None
    url = catalog_client.sibling_url(index_url, STATEMENT_FILE_NAME)
    client = await catalog_client.shared_client()
    async with catalog_client.counted_fetch():
        body = await fetch_document(
            client, url, limit=MAX_STATEMENT_BYTES, url_kind="publisher-key-revoked",
        )
        if isinstance(body, FetchRefusal):
            return None
        sig = await fetch_document(
            client,
            catalog_client.minisig_url(url),
            limit=catalog_client.MAX_MINISIG_BYTES,
            url_kind="publisher-key-revoked minisig",
        )
    if isinstance(sig, FetchRefusal) or body[0] != 200 or sig[0] != 200:
        return None
    text = catalog_client.read_minisig(sig[1])
    if isinstance(text, FetchRefusal):
        return None
    return body[1], text


class PublisherKeyChain:

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
        self._accepted: Optional[PublisherKeyRevocation] = None
        self._loaded = False

    def _load(self) -> None:
        live = self._pinned.publisher_key
        if self._loaded or self._accepted is not None or live is None:
            return
        try:
            with closing(self._open_db()) as conn:
                rows = conn.execute(
                    "SELECT subject, since FROM catalog_revocations_seen "
                    "WHERE index_key_id = ? AND kind = ? ORDER BY subject",
                    (live.key_id, KIND_PUBLISHER_KEY_REVOKED),
                ).fetchall()
        except sqlite3.Error as exc:
            logger.warning("catalog_publisher_key_chain_unreadable", error=str(exc))
            return
        self._loaded = True
        for row in rows:
            candidate = PublisherKeyRevocation(
                revoked_key_id=live.key_id,
                replacement_pub=str(row["subject"]),
                since=str(row["since"]),
            )
            try:
                apply_publisher_revocation(self._pinned, candidate)
            except ValueError:
                logger.error("catalog_publisher_key_row_unreadable",
                             stored=log_value(candidate.replacement_pub))
                continue
            self._accepted = candidate
            return

    def apply(self, root: TrustRoot) -> TrustRoot:
        self._load()
        return apply_publisher_revocation(root, self._accepted)

    async def check(self, index_url: str) -> bool:
        self._load()
        if (
            self._accepted is not None
            or self._pinned.publisher_key is None
            or self._pinned.spare_publisher_key is None
        ):
            return False
        fetched = await self._fetch(index_url)
        if fetched is None:
            return False
        accepted = verify_publisher_key_revocation(fetched[0], fetched[1], self._pinned)
        if accepted is None:
            return False
        self._accepted = accepted
        try:
            with closing(self._open_db()) as conn, conn:
                conn.execute(
                    "INSERT OR IGNORE INTO catalog_revocations_seen "
                    "(index_key_id, kind, subject, since) VALUES (?, ?, ?, ?)",
                    (accepted.revoked_key_id, KIND_PUBLISHER_KEY_REVOKED,
                     accepted.replacement_pub, accepted.since),
                )
        except sqlite3.Error as exc:
            logger.error(
                "catalog_publisher_key_revocation_not_persisted",
                error=str(exc), revoked_key_id=accepted.revoked_key_id,
            )
        logger.warning(
            "catalog_publisher_key_revoked",
            revoked_key_id=accepted.revoked_key_id,
            since=log_value(accepted.since),
        )
        return True
