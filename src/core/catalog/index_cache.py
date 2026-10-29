
from __future__ import annotations

import asyncio
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional, Union

import structlog

from src.core import resource_push
from src.core.catalog.client import fetch_index
from src.core.catalog.fetch_stream import FetchRefusal
from src.core.catalog.index_freshness import (
    FORCE_REFRESH_FLOOR_SECONDS,
    is_degraded,
    is_overdue,
    within_force_floor,
)
from src.core.catalog.index_snapshot import (  # noqa: F401
    EMPTY_SNAPSHOT,
    IndexSnapshot,
    content_fingerprint,
    serial_of,
)
from src.core.catalog.index_key_chain import IndexKeyChain
from src.core.catalog.index_state import IndexStateStore, RevocationStore
from src.core.catalog.revocation import KIND_KEY, KIND_VERSION
from src.core.catalog.trust_root import TrustRoot
from src.core.catalog.verify import verify_index
from src.core.catalog.verify_types import VerifiedIndex, VerifyRefusal
from src.core.resource_push import topics as resource_topics
from src.core.sessions.ports import Clock
from src.core.single_flight import flight_on

logger = structlog.get_logger()

REFRESH_INTERVAL_SECONDS: float = 300.0

INDEX_FLIGHT_ATTR = "_index_refresh_flight"
INDEX_FLIGHT_NAME = "catalog_index"


class IndexCache:

    def __init__(
        self,
        *,
        index_url: Callable[[], str],
        trust_root: TrustRoot,
        clock: Clock,
        open_db: Callable[[], sqlite3.Connection],
    ) -> None:
        self._index_url = index_url
        self._trust_root = trust_root
        self._clock = clock
        self._open_db = open_db
        self.key_chain = IndexKeyChain(trust_root=trust_root, open_db=open_db)
        self._snapshot = EMPTY_SNAPSHOT
        self._etag: Optional[str] = None
        self._etag_loaded = False
        self._fetched_monotonic: Optional[float] = None
        self.after_refresh: Optional[Callable[[], Awaitable[None]]] = None
        self.after_refresh_task: Optional["asyncio.Task[None]"] = None

    @property
    def index_key_id(self) -> Optional[str]:
        key = self.key_chain.active_root().index_key
        return None if key is None else key.key_id

    def snapshot(self) -> IndexSnapshot:
        held = self._snapshot
        stale = self._is_overdue()
        degraded = self._is_degraded(held.as_of)
        if held.stale == stale and held.degraded == degraded:
            return held
        return IndexSnapshot(
            verified=held.verified,
            refusal=held.refusal,
            as_of=held.as_of,
            degraded=degraded,
            fetched_at=held.fetched_at,
            stale=stale,
        )

    async def refresh_now(self) -> tuple[IndexSnapshot, bool]:
        if self._within_force_floor():
            logger.info(
                "catalog_index_force_floored",
                floor_seconds=FORCE_REFRESH_FLOOR_SECONDS,
                serial=serial_of(self._snapshot),
            )
            return self.snapshot(), False
        return await self.get(force=True), True

    async def get(self, *, force: bool = False) -> IndexSnapshot:
        if not force and not self._is_stale():
            return self.snapshot()

        flight = flight_on(self, INDEX_FLIGHT_ATTR, INDEX_FLIGHT_NAME)
        await flight.run(self._refresh)
        return self.snapshot()

    async def refresh_if_due(self) -> tuple[IndexSnapshot, bool]:
        due = self._is_stale()
        return await self.get(), due


    def _is_stale(self) -> bool:
        if self._fetched_monotonic is None:
            return True
        elapsed = self._clock.monotonic() - self._fetched_monotonic
        return elapsed >= REFRESH_INTERVAL_SECONDS

    def _is_overdue(self) -> bool:
        return is_overdue(
            self._fetched_monotonic, monotonic_now=self._clock.monotonic()
        )

    def _within_force_floor(self) -> bool:
        return within_force_floor(
            self._fetched_monotonic, monotonic_now=self._clock.monotonic()
        )

    def _is_degraded(self, as_of: Optional[datetime]) -> bool:
        return is_degraded(
            as_of,
            now=datetime.fromtimestamp(self._clock.now(), tz=timezone.utc),
            staleness_days=self._trust_root.staleness_days,
        )

    def _stored_etag(self) -> Optional[str]:
        if self._etag_loaded:
            return self._etag
        self._etag_loaded = True
        key_id = self.index_key_id
        if key_id is None:
            return None
        try:
            with closing(self._open_db()) as conn:
                state = IndexStateStore(conn).get(key_id)
        except sqlite3.Error as exc:
            logger.warning("catalog_index_etag_unreadable", error=str(exc))
            return None
        if state is not None:
            self._etag = state.etag
        return self._etag

    def _floor_and_revocations(self) -> tuple[int, frozenset]:
        key_id = self.index_key_id
        if key_id is None:
            return 0, frozenset()
        try:
            with closing(self._open_db()) as conn:
                state = IndexStateStore(conn).get(key_id)
                store = RevocationStore(conn)
                seen = frozenset().union(
                    *(store.seen(k) for k in self.key_chain.chain_key_ids())
                )
        except sqlite3.Error as exc:
            logger.warning("catalog_index_state_unreadable", error=str(exc))
            return 0, frozenset()
        floor = 0 if state is None else state.last_verified_serial
        return floor, seen

    def revoked_sets(self, verified: VerifiedIndex) -> tuple[frozenset, frozenset]:
        _floor, seen = self._floor_and_revocations()
        effective = frozenset(seen) | frozenset(verified.revocations)
        keys = frozenset(r.subject.strip().upper() for r in effective if r.kind == KIND_KEY)
        versions = frozenset(r.subject for r in effective if r.kind == KIND_VERSION)
        return keys, versions

    def _persist(self, verified: VerifiedIndex, etag: Optional[str]) -> None:
        stamp = (
            datetime.fromtimestamp(self._clock.now(), tz=timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )
        try:
            with closing(self._open_db()) as conn:
                IndexStateStore(conn).record(
                    verified.index_key_id, verified.serial, stamp, etag
                )
                RevocationStore(conn).remember(
                    verified.index_key_id, verified.revocations
                )
        except sqlite3.Error as exc:
            logger.warning(
                "catalog_index_state_not_persisted",
                error=str(exc),
                serial=verified.serial,
            )

    def _keep(self, refusal: Union[VerifyRefusal, FetchRefusal]) -> None:
        held = self._snapshot
        self._snapshot = IndexSnapshot(
            verified=held.verified,
            refusal=refusal,
            as_of=held.as_of,
            degraded=held.degraded,
            fetched_at=held.fetched_at,
            stale=True,
        )

    async def _refresh(self) -> None:
        before = content_fingerprint(self.snapshot())
        await self._round_trip()
        if content_fingerprint(self.snapshot()) != before:
            resource_push.notify(resource_topics.CATALOG)

    async def _round_trip(self) -> None:
        url = self._index_url()
        if await self.key_chain.check(url):
            self._forget_revoked_key_snapshot()
        etag = (
            self._stored_etag() if self._snapshot.verified is not None else None
        )
        fetched = await fetch_index(url, etag=etag)
        self._fetched_monotonic = self._clock.monotonic()

        if isinstance(fetched, FetchRefusal):
            logger.warning(
                "catalog_index_fetch_refused", code=fetched.code, url=url
            )
            self._keep(fetched)
            return

        if fetched.not_modified:
            held = self._snapshot
            logger.info("catalog_index_unchanged", serial=serial_of(held))
            self._snapshot = IndexSnapshot(
                verified=held.verified,
                refusal=None,
                as_of=held.as_of,
                degraded=held.degraded,
                fetched_at=self._clock.now(),
                stale=False,
            )
            return

        floor, seen = self._floor_and_revocations()
        result = verify_index(
            fetched.index_bytes,
            fetched.minisig_text,
            trust_root=self.key_chain.active_root(),
            seen_revocations=seen,
            last_verified_serial=floor,
            now=datetime.fromtimestamp(self._clock.now(), tz=timezone.utc),
        )
        if isinstance(result, VerifyRefusal):
            logger.warning(
                "catalog_index_verify_refused",
                code=result.code,
                detail=result.detail,
            )
            self._keep(result)
            return

        self._etag = fetched.etag
        self._persist(result, fetched.etag)
        self._snapshot = IndexSnapshot(
            verified=result,
            refusal=None,
            as_of=result.generated_at,
            degraded=result.degraded,
            fetched_at=self._clock.now(),
            stale=False,
        )
        logger.info(
            "catalog_index_verified",
            serial=result.serial,
            items=len(result.items),
            untrusted=len(result.untrusted_items),
            degraded=result.degraded,
        )
        self._schedule_after_refresh()

    def _forget_revoked_key_snapshot(self) -> None:
        self._snapshot = EMPTY_SNAPSHOT
        self._etag = None
        self._etag_loaded = False

    def _schedule_after_refresh(self) -> None:
        hook = self.after_refresh
        if hook is None:
            return
        self.after_refresh_task = asyncio.create_task(hook())
