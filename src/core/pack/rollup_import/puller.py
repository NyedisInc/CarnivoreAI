
from __future__ import annotations

import asyncio
import sqlite3
import time
from contextlib import closing
from typing import Any, Awaitable, Callable, Dict, FrozenSet, List, Optional, Set, Tuple
from urllib.parse import urlencode

import structlog

from src.core.computers import direction
from src.core.db import transaction
from src.core.pack.machines import capabilities as caps_mod
from src.core.pack.machines.roster_v2 import RosterV2
from src.core.pack.rollup_import import relay_pull, relay_store, signed, store, v2_export, v2_store

logger = structlog.get_logger()

ROLLUP_PATH = "/federation/pack/rollup"
MIN_INTERVAL_SECONDS = 15.0
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
                 capabilities_for: Callable[[str], List[str]], clock: Callable[[], float] = time.time, self_id: str = "",
                 held_list: Callable[[], Any] = lambda: None) -> None:
        self._open_db, self._post_for, self._caps_for, self._clock = open_db, post_for, capabilities_for, clock
        self.held_list = held_list
        self._self_id = self_id
        self._busy: Set[str] = set()
        self._last_attempt: Dict[str, float] = {}
        self._noted: Set[Tuple[str, str]] = set()
        self.members: FrozenSet[str] = frozenset()
        self.member_caps: Dict[str, List[str]] = {}
        self.live: Optional[FrozenSet[str]] = None
        self.behind: Dict[str, Tuple[float, int]] = {}

    def _caps(self, peer_id: str) -> List[str]:
        return self._caps_for(peer_id) or self.member_caps.get(peer_id, [])

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
            return store.reset_peer(conn, peer_id, digest, self._clock(), members=self.members)

    def _apply(self, peer_id: str, groups: List[Any], verified: Optional[signed.Verified] = None) -> Optional[int]:
        with closing(self._open_db()) as conn:
            proofs = None if verified is None else {(cid, hour): proof for (_origin, cid, hour), proof in verified.items()}
            return store.apply_page(conn, peer_id, groups, signed=proofs, members=self.members)

    def signed_mode(self, peer_id: str) -> bool:
        return caps_mod.mesh_on() and caps_mod.has(self._caps(peer_id), caps_mod.CAP_MESH)

    def _verify_page(
        self, peer_id: str, page: Dict[str, Any], first: bool
    ) -> Optional[Tuple[signed.Verified, Optional[signed.Proof], Optional[signed.Proof]]]:
        lst = self.held_list()
        if not isinstance(lst, RosterV2):
            return None
        verified = signed.verify_groups(page["groups"], lambda _group: peer_id, lst, relay=False)
        if verified is None:
            return None
        proof = None
        if first and "project_names" in page:
            proof = signed.verify_names(peer_id, page.get("project_names"), page.get("project_homes", {}), page.get("until_revision"), page.get("names_sig"), lst,
                                        page.get("names_epoch"))
            if proof is None:
                return None
        v2_proof = None
        if first and any(key in page for key in ("v2", "v2_rev", "v2_epoch", "v2_sig")):
            v2_proof = v2_export.verify_v2(
                peer_id, page.get("v2"), page.get("v2_rev"), page.get("v2_sig"), lst, page.get("v2_epoch")
            )
            if v2_proof is None:
                return None
        return verified, proof, v2_proof

    def _names_signed(self, peer_id: str, names: Any, homes: Any, proof: signed.Proof) -> None:
        with closing(self._open_db()) as conn, transaction(conn):
            relay_store.replace_names_signed(conn, peer_id, names, homes, *proof)

    def _v2_signed(self, peer_id: str, payload: Any, proof: signed.Proof) -> None:
        with closing(self._open_db()) as conn, transaction(conn):
            v2_store.apply_v2_signed(conn, peer_id, payload, *proof, now=self._clock())

    def _v2_unsigned(self, peer_id: str, payload: Any, rev: int) -> None:
        with closing(self._open_db()) as conn, transaction(conn):
            v2_store.apply_v2(conn, peer_id, payload, rev=rev, now=self._clock())

    def _finish(self, peer_id: str, revision: int, digest: str, one_way: Optional[List[str]] = None) -> bool:
        with closing(self._open_db()) as conn:
            return store.finish(conn, peer_id, revision, digest, self._clock(), one_way=one_way, members=self.members)

    def _names(self, peer_id: str, names: Any, homes: Any) -> None:
        with closing(self._open_db()) as conn, transaction(conn):
            relay_store.replace_names(conn, peer_id, names, homes)

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

    async def maybe_pull_member(self, peer_id: str, post: PostFn) -> None:
        if peer_id == self._self_id or direction.contained(peer_id):
            return
        caps = self._caps(peer_id)
        if not (caps_mod.mesh_on() and caps_mod.has(caps, caps_mod.CAP_MESH) and caps_mod.has(caps, caps_mod.CAP_PIPELINE_ROLLUP)):
            self._note_once(peer_id, "member_unsigned")
            return
        if peer_id in self._busy:
            return
        self._busy.add(peer_id)
        try:
            now = self._clock()
            if now - self._last_attempt.get(peer_id, float("-inf")) >= MIN_INTERVAL_SECONDS:
                self._last_attempt[peer_id] = now
                await self._pull(peer_id, post, await asyncio.to_thread(self._read_state, peer_id))
            relay_key = peer_id + "#relay"
            if caps_mod.has(caps, caps_mod.CAP_ROLLUP_RELAY) and self._clock() - self._last_attempt.get(relay_key, float("-inf")) >= MIN_INTERVAL_SECONDS:
                self._last_attempt[relay_key] = self._clock()
                await relay_pull.pull_relay(self, peer_id, post)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("pack_rollup_member_pull_failed", peer=peer_id[:8], error_type=type(exc).__name__)
        finally:
            self._busy.discard(peer_id)

    async def _maybe_pull(self, peer_id: str, snapshot: Any) -> None:
        if peer_id == self._self_id:
            return
        if direction.contained(peer_id):
            state = await asyncio.to_thread(self._read_state, peer_id)
            if state is not None:
                await asyncio.to_thread(self._purge, peer_id)
            self._note_once(peer_id, "one_way")
            return
        if not caps_mod.has(self._caps(peer_id), caps_mod.CAP_PIPELINE_ROLLUP):
            if advertised(snapshot) is not None:
                self._note_once(peer_id, "no_capability")
            return
        rev = advertised(snapshot)
        state = await asyncio.to_thread(self._read_state, peer_id) if rev is not None else None
        want_v2 = caps_mod.has(self._caps(peer_id), caps_mod.CAP_ROLLUP_V2)
        own_due = rev is not None and (
            state is None or state.via != "" or state.revision != rev or (want_v2 and state.v2_rev is None)
        )
        relay_rev = relay_pull.advertised(snapshot) if caps_mod.has(self._caps(peer_id), caps_mod.CAP_ROLLUP_RELAY) else None
        if relay_rev is not None and caps_mod.mesh_on() and not self.signed_mode(peer_id):
            self._note_once(peer_id, "relay_unsigned")
            relay_rev = None
        relay_due = relay_rev is not None and relay_rev != await asyncio.to_thread(self._relay_cursor, peer_id)
        if not (own_due or relay_due):
            return
        post = self._post_for(peer_id)
        if post is None:
            return
        now = self._clock()
        if own_due and now - self._last_attempt.get(peer_id, float("-inf")) >= MIN_INTERVAL_SECONDS:
            self._last_attempt[peer_id] = now
            await self._pull(peer_id, post, state)
        relay_key = peer_id + "#relay"
        if relay_due and now - self._last_attempt.get(relay_key, float("-inf")) >= MIN_INTERVAL_SECONDS:
            self._last_attempt[relay_key] = now
            await relay_pull.pull_relay(self, peer_id, post)

    def _relay_cursor(self, peer_id: str) -> int:
        with closing(self._open_db()) as conn:
            return relay_store.get_relay_state(conn, peer_id)[0]

    async def _page(self, post: PostFn, since: int, until: Optional[int], cursor: Optional[str],
                    stream: Optional[str] = None, v2: bool = False) -> Optional[Dict[str, Any]]:
        query: Dict[str, Any] = {"since_rev": since, "max_bytes": PAGE_BYTES}
        if stream:
            query["stream"] = stream
        if v2:
            query["v2"] = 1
        if until is not None:
            query["until_rev"] = until
        if cursor:
            query["cursor"] = cursor
        status, data = await post("GET", f"{ROLLUP_PATH}?{urlencode(query)}", None)
        return data if status == 200 and isinstance(data, dict) else None

    async def _pull(self, peer_id: str, post: PostFn, state: Optional[store.State]) -> None:
        if state is not None and state.via != "":
            if not await asyncio.to_thread(self._reset, peer_id, ""):
                return
            state = None
        since = state.revision if state is not None else 0
        known_digest = state.scope_digest if state is not None else ""
        caps = self._caps(peer_id)
        stream = "own" if caps_mod.has(caps, caps_mod.CAP_ROLLUP_RELAY) else None
        want_v2 = caps_mod.has(caps, caps_mod.CAP_ROLLUP_V2)
        one_way: Optional[List[str]] = None
        until: Optional[int] = None
        cursor: Optional[str] = None
        signed_mode = self.signed_mode(peer_id)
        names_later: Optional[Tuple[Any, Any, signed.Proof]] = None
        v2_later: Optional[Tuple[Any, signed.Proof]] = None
        v2_unsigned: Optional[Any] = None
        started_digest = ""
        for _ in range(MAX_PAGES):
            page = await self._page(post, since, until, cursor, stream, v2=want_v2)
            if page is None or page.get("available") is False:
                self._note_once(peer_id, "unavailable", reason=(page or {}).get("reason", "refused"))
                return
            digest, groups = page.get("scope_digest"), page.get("groups")
            page_until = page.get("until_revision")
            if not (isinstance(digest, str) and isinstance(groups, list) and isinstance(page_until, int)):
                self._note_once(peer_id, "malformed")
                return
            verified: Optional[signed.Verified] = None
            if signed_mode:
                checked = await asyncio.to_thread(self._verify_page, peer_id, page, until is None) if all(isinstance(g, dict) for g in groups) else None
                if checked is None:
                    self._note_once(peer_id, "forged")
                    return
                verified = checked[0]
                if checked[1] is not None:
                    names_later = (page.get("project_names"), page.get("project_homes", {}), checked[1])
                if checked[2] is not None:
                    v2_later = (page.get("v2"), checked[2])
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
                if stream and page.get("stream") == "own":
                    one_way = relay_store.id_list(page.get("one_way")) if "one_way" in page else None
                    if "project_names" in page and not signed_mode:
                        await asyncio.to_thread(self._names, peer_id, page.get("project_names"), page.get("project_homes"))
                if not signed_mode and "v2" in page:
                    v2_unsigned = page.get("v2")
            applied = await asyncio.to_thread(self._apply, peer_id, groups, verified)
            if applied is None:
                return
            if page.get("complete") is True:
                if await asyncio.to_thread(self._finish, peer_id, until, started_digest, one_way):
                    if names_later is not None:
                        await asyncio.to_thread(self._names_signed, peer_id, *names_later)
                    if v2_later is not None:
                        await asyncio.to_thread(self._v2_signed, peer_id, *v2_later)
                    elif v2_unsigned is not None:
                        await asyncio.to_thread(self._v2_unsigned, peer_id, v2_unsigned, until)
                logger.debug("pack_rollup_pulled", peer=peer_id[:8], revision=until)
                return
            nxt = page.get("next_cursor")
            if not isinstance(nxt, str) or not nxt or nxt == cursor:
                self._note_once(peer_id, "bad_cursor")
                return
            cursor = nxt
        self._note_once(peer_id, "too_many_pages")
