
from __future__ import annotations

import asyncio
import sqlite3
import time
from contextlib import closing
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set, Tuple
from urllib.parse import urlencode

import structlog

from src.core.computers import direction
from src.core.db import transaction
from src.core.pack.machines import capabilities as caps_mod
from src.core.pack.rollup_import import store

logger = structlog.get_logger()

ROLLUP_PATH = "/federation/pack/rollup"
MIN_INTERVAL_SECONDS = 60.0
PAGE_BYTES = 512 * 1024
BULK_MAX_BODY = 1024 * 1024 + 64 * 1024
MAX_PAGES = 5000
REV_KEY = "stats"

PostFn = Callable[[str, str, Optional[dict]], Awaitable[Tuple[int, Any]]]


def advertised(snapshot: Any) -> Optional[int]:
    rev = (snapshot.get("pipeline_rev") if isinstance(snapshot, dict) else None)
    value = rev.get(REV_KEY) if isinstance(rev, dict) else None
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


class RollupImporter:

    def __init__(self, open_db: Callable[[], sqlite3.Connection], post_for: Callable[[str], Optional[PostFn]],
                 capabilities_for: Callable[[str], List[str]], clock: Callable[[], float] = time.time) -> None:
        self._open_db, self._post_for, self._caps_for, self._clock = open_db, post_for, capabilities_for, clock
        self._busy: Set[str] = set()
        self._last_attempt: Dict[str, float] = {}
        self._noted: Set[Tuple[str, str]] = set()

    def _note_once(self, peer_id: str, why: str, **context: Any) -> None:
        if (peer_id, why) not in self._noted:
            self._noted.add((peer_id, why))
            logger.info("pack_rollup_skipped", peer=peer_id[:8], reason=why, **context)

    def _read_state(self, peer_id: str) -> Optional[store.State]:
        with closing(self._open_db()) as conn:
            return store.get_state(conn, peer_id)

    def _purge(self, peer_id: str) -> None:
        with closing(self._open_db()) as conn, transaction(conn):
            store.purge_peer(conn, peer_id)

    def _reset(self, peer_id: str, digest: str) -> bool:
        with closing(self._open_db()) as conn:
            return store.reset_peer(conn, peer_id, digest, self._clock())

    def _apply(self, peer_id: str, groups: List[Any]) -> Optional[int]:
        with closing(self._open_db()) as conn:
            return store.apply_page(conn, peer_id, groups)

    def _finish(self, peer_id: str, revision: int, digest: str) -> bool:
        with closing(self._open_db()) as conn:
            return store.finish(conn, peer_id, revision, digest, self._clock())

    async def maybe_pull(self, peer_id: str, snapshot: Any) -> None:
        if peer_id in self._busy:
            return
        self._busy.add(peer_id)
        try:
            await self._maybe_pull(peer_id, snapshot)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("pack_rollup_pull_failed", peer=peer_id[:8], error_type=type(exc).__name__)
        finally:
            self._busy.discard(peer_id)

    async def _maybe_pull(self, peer_id: str, snapshot: Any) -> None:
        if direction.contained(peer_id):
            state = await asyncio.to_thread(self._read_state, peer_id)
            if state is not None:
                await asyncio.to_thread(self._purge, peer_id)
            self._note_once(peer_id, "one_way")
            return
        rev = advertised(snapshot)
        if rev is None:
            return
        if not caps_mod.has(self._caps_for(peer_id), caps_mod.CAP_PIPELINE_ROLLUP):
            self._note_once(peer_id, "no_capability")
            return
        state = await asyncio.to_thread(self._read_state, peer_id)
        if state is not None and state.revision == rev:
            return
        now = self._clock()
        if now - self._last_attempt.get(peer_id, float("-inf")) < MIN_INTERVAL_SECONDS:
            return
        post = self._post_for(peer_id)
        if post is None:
            return
        self._last_attempt[peer_id] = now
        await self._pull(peer_id, post, state)

    async def _page(self, post: PostFn, since: int, until: Optional[int], cursor: Optional[str]) -> Optional[Dict[str, Any]]:
        query: Dict[str, Any] = {"since_rev": since, "max_bytes": PAGE_BYTES}
        if until is not None:
            query["until_rev"] = until
        if cursor:
            query["cursor"] = cursor
        status, data = await post("GET", f"{ROLLUP_PATH}?{urlencode(query)}", None)
        return data if status == 200 and isinstance(data, dict) else None

    async def _pull(self, peer_id: str, post: PostFn, state: Optional[store.State]) -> None:
        since = state.revision if state is not None else 0
        known_digest = state.scope_digest if state is not None else ""
        until: Optional[int] = None
        cursor: Optional[str] = None
        started_digest = ""
        for _ in range(MAX_PAGES):
            page = await self._page(post, since, until, cursor)
            if page is None or page.get("available") is False:
                self._note_once(peer_id, "unavailable", reason=(page or {}).get("reason", "refused"))
                return
            digest, groups = page.get("scope_digest"), page.get("groups")
            page_until = page.get("until_revision")
            if not (isinstance(digest, str) and isinstance(groups, list) and isinstance(page_until, int)):
                self._note_once(peer_id, "malformed")
                return
            if until is None:
                moved = bool(known_digest) and digest != known_digest
                if page.get("reset") is True or moved:
                    if not await asyncio.to_thread(self._reset, peer_id, digest):
                        return
                    known_digest = digest
                    if page.get("reset") is not True and since != 0:
                        since, until, cursor = 0, None, None
                        continue
                until = page_until
                started_digest = digest
            applied = await asyncio.to_thread(self._apply, peer_id, groups)
            if applied is None:
                return  # nothing was written
            if page.get("complete") is True:
                await asyncio.to_thread(self._finish, peer_id, until, started_digest)
                logger.debug("pack_rollup_pulled", peer=peer_id[:8], revision=until)
                return
            nxt = page.get("next_cursor")
            if not isinstance(nxt, str) or not nxt or nxt == cursor:
                self._note_once(peer_id, "bad_cursor")
                return
            cursor = nxt
        self._note_once(peer_id, "too_many_pages")
