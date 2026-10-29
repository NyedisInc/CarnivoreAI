"""Which index key this install trusts right now, and how that moves (#130).

THE CHAIN HAS TWO LINKS AND ONE DIRECTION. The live pinned index key, then
the pinned spare. :class:`IndexKeyChain` starts on the live key and moves
to the spare exactly once, when a ``carnivore-index-key-revoked-v1``
statement verifies (:mod:`src.core.catalog.index_key_revocation`). It never
moves back: there is no statement that un-revokes, and the move is
persisted.

WHERE THE STATEMENT COMES FROM. Beside the index, on the same host and
through the same hardened fetch: the index url's last path segment
replaced by ``index-key-revoked``, plus ``.minisig``. It cannot ride
INSIDE the index: after the move the index is signed by the spare, which
the app would refuse before parsing a byte of it, and before the move
whoever leaked the live key controls what the index says. It is fetched on
EVERY round trip while the live key is still trusted, whatever the index
answers (a 304 included), because a thief holding the live key serves
perfectly valid indexes and nothing else would ever prompt a look. Once
the move is made it is never fetched again. A 404, a transport failure or
a statement that does not verify all mean "no move" and never touch the
index fetch: a missing statement is the status quo.

WHERE THE MOVE IS PERSISTED. Two rows in the existing
``catalog_revocations_seen`` table (no schema change), written in ONE
transaction. The move: ``index_key_id`` is the REVOKED key id, ``kind`` is
:data:`KIND_INDEX_KEY_REVOKED`, ``subject`` is the successor key id,
``since`` the signed date. Its first spare serial: same ``index_key_id``
and ``subject``, ``kind`` :data:`KIND_INDEX_KEY_FIRST_SERIAL`, and the
signed decimal serial in ``since`` (that column is the kind's payload).
That table is append only and has no delete method, which is exactly the
property a revocation needs.
:meth:`~src.core.catalog.index_state.RevocationStore.seen` reads only the
publisher kinds, so neither row mixes into publisher revocations.

WHAT CARRIES ACROSS THE MOVE, AND WHAT DOES NOT.
- Publisher revocations DO: they are signed by the publisher key, which an
  index key compromise does not touch. :meth:`IndexKeyChain.chain_key_ids`
  is every key id they were stored under.
- The serial floor does NOT: it is keyed on the signing key, and the
  spare's floor is the first serial its own statement signed (#130 review
  M1, :mod:`src.core.catalog.index_key_revocation`). This is TUF's fast
  forward recovery rule: whoever held the leaked key could push the old
  key's floor up by ``MAX_SERIAL_JUMP`` per accepted index, and carrying
  that floor over would let them brick the spare before it signed
  anything; only the offline spare says where its own series starts.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import Awaitable, Callable, Optional, Tuple
from urllib.parse import urlsplit, urlunsplit

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
from src.core.catalog.trust_root import TrustRoot
from src.core.db import transaction

logger = structlog.get_logger(__name__)

KIND_INDEX_KEY_REVOKED = "index-key-revoked"

KIND_INDEX_KEY_FIRST_SERIAL = "index-key-first-serial"

STATEMENT_FILE_NAME = "index-key-revoked"

StatementFetch = Callable[[str], Awaitable[Optional[Tuple[bytes, str]]]]


def statement_url(index_url: str) -> str:
    parts = urlsplit(index_url)
    directory = parts.path.rsplit("/", 1)[0]
    return urlunsplit(
        parts._replace(path=f"{directory}/{STATEMENT_FILE_NAME}", query="", fragment="")
    )


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
        return active_trust_root(self._pinned, self._accepted)

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
        if not self._wants_statement():
            return False
        fetched = await self._fetch(index_url)
        if fetched is None:
            return False
        accepted = verify_index_key_revocation(fetched[0], fetched[1], self._pinned)
        if accepted is None:
            return False
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
