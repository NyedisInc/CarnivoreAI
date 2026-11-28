
from __future__ import annotations

import asyncio
import json
import random
import secrets
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set, Tuple

import structlog

from src.core.bounded_stream import BoundedStream
from src.core.federation import shadow_rows
from src.core.listing_push.diff import KeyedRows, diff, keyed
from src.core.pack.machines import capabilities
from src.models import WSMessageType

logger = structlog.get_logger()

FRAME_TYPE = WSMessageType.PEER_LISTING.value
COALESCE_SECONDS = 0.25
RESYNC_SECONDS = 60.0
MAX_FRAME_BYTES = 512 * 1024
RESYNC_JITTER = 0.5
MESH_FRAME_BYTES = 2 * 1024 * 1024
MESH_QUEUE_BYTES = 2 * MESH_FRAME_BYTES

View = Callable[[], Awaitable[Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]]]


def jittered_resync() -> float:
    return random.uniform(RESYNC_SECONDS * RESYNC_JITTER, RESYNC_SECONDS)


def resync_wait(member_attached: bool) -> float:
    return jittered_resync() if capabilities.mesh_on() and member_attached else RESYNC_SECONDS


def frame_cap(mesh: bool) -> int:
    return MESH_FRAME_BYTES if mesh else MAX_FRAME_BYTES


def member_caps(peer: bool, grant: Any) -> Optional[Tuple[int, int]]:
    if not peer or not capabilities.mesh_on():
        return None
    from src.core.federation.mesh_grants import MeshGrant
    if isinstance(grant, MeshGrant):
        return MESH_QUEUE_BYTES, MESH_FRAME_BYTES
    return None


def row_key(row: Dict[str, Any]) -> Optional[str]:
    if row.get("session_uuid"):
        return str(row["session_uuid"])
    session = row.get("session")
    return str(session["id"]) if isinstance(session, dict) and session.get("id") else None


class PeerListingFeed:

    def __init__(self, view: View) -> None:
        self._view = view
        self.stream = secrets.token_hex(6)
        self.seq = 0
        self._list: Optional[KeyedRows] = None
        self._asleep: Optional[KeyedRows] = None
        self._streams: Dict[BoundedStream, Optional[int]] = {}
        self._wake = asyncio.Event()
        self._task: Optional["asyncio.Task[None]"] = None
        self._owners: Set[str] = set()

    def claim(self, owner: str) -> bool:
        if owner in self._owners:
            return False
        self._owners.add(owner)
        return True

    def release(self, owner: str) -> None:
        self._owners.discard(owner)

    def on_hub_publish(self, frame_type: Optional[str]) -> None:
        if frame_type == WSMessageType.LISTING_DELTA.value and self._streams:
            self._wake.set()

    @staticmethod
    def _compute(rows: List[Dict[str, Any]], asleep: List[Dict[str, Any]], old_list: Optional[KeyedRows],
                 old_asleep: Optional[KeyedRows]) -> Tuple[KeyedRows, KeyedRows, Any, Any]:
        new_list, new_asleep = keyed(rows, row_key), keyed(asleep, row_key)
        return new_list, new_asleep, diff(old_list, new_list), diff(old_asleep, new_asleep)

    async def _refresh(self) -> Optional[Dict[str, Any]]:
        rows, asleep = await self._view()
        new_list, new_asleep, change_list, change_asleep = await asyncio.to_thread(
            self._compute, rows, asleep, self._list, self._asleep)
        first = self._list is None
        self._list, self._asleep = new_list, new_asleep
        if first or not (change_list or change_asleep):
            return None
        self.seq += 1
        return {"type": FRAME_TYPE, "stream": self.stream, "seq": self.seq, "full": False,
                "list": change_list, "asleep": change_asleep}

    def _full_text(self) -> Tuple[int, str]:
        seq, rows, asleep = self.seq, self._list or [], self._asleep or []
        return seq, json.dumps({"type": FRAME_TYPE, "stream": self.stream, "seq": seq, "full": True,
                                "list": diff(None, rows), "asleep": diff(None, asleep)})

    async def _full(self) -> Tuple[int, str]:
        while True:
            at = self.seq
            seq, text = await asyncio.to_thread(self._full_text)
            if seq == at == self.seq:
                return seq, text

    def _member_attached(self) -> bool:
        return any(cap is not None for cap in self._streams.values())

    def _offer_all(self, text: str, targets: Optional[List[BoundedStream]] = None) -> None:
        for stream in (list(self._streams) if targets is None else [s for s in targets if s in self._streams]):
            stream.offer(text, len(text))

    def _resync_frame(self) -> str:
        return json.dumps({"type": FRAME_TYPE, "stream": self.stream, "seq": self.seq, "resync": True})

    def _drop_all(self) -> None:
        logger.warning("peer_listing_feed_oversize", sockets=len(self._streams))
        self._offer_all(self._resync_frame())
        self._streams.clear()
        self._list = self._asleep = None

    def _over_cap(self, stream: BoundedStream, size: int) -> bool:
        cap = self._streams.get(stream)
        if cap is None:
            return size > frame_cap(False)
        return size > cap or max(len(self._list or ()), len(self._asleep or ())) > shadow_rows.MAX_ROWS

    def _send_sized(self, text: str, targets: List[BoundedStream]) -> None:
        if not self._member_attached():
            if len(text) > frame_cap(False):
                self._drop_all()
                return
            self._offer_all(text, targets)
            return
        fits = [s for s in targets if s in self._streams and not self._over_cap(s, len(text))]
        for stream in [s for s in targets if s in self._streams and s not in fits]:
            logger.warning("peer_listing_feed_oversize", sockets=len(self._streams), member=True)
            self._offer_all(self._resync_frame(), [stream])
            self._streams.pop(stream, None)
        if not self._streams:
            self._list = self._asleep = None
            return
        self._offer_all(text, fits)

    async def attach(self, stream: BoundedStream, cap: Optional[int] = None) -> None:
        if self._list is None or not self._streams:
            self._list = self._asleep = None
            await self._refresh()
        _, text = await self._full()
        too_many = cap is not None and max(len(self._list or ()), len(self._asleep or ())) > shadow_rows.MAX_ROWS
        if len(text) > (frame_cap(False) if cap is None else cap) or too_many:
            logger.warning("peer_listing_feed_oversize", sockets=len(self._streams) + 1, attached=False)
            return
        stream.offer(text, len(text))
        self._streams[stream] = cap
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="peer-listing-feed")

    def detach(self, stream: BoundedStream) -> None:
        self._streams.pop(stream, None)
        if not self._streams and self._task is not None:
            self._task.cancel()
            self._task = None
            self._list = self._asleep = None

    async def _run(self) -> None:
        while True:
            try:
                await asyncio.wait_for(self._wake.wait(), resync_wait(self._member_attached()))
                resync = False
            except asyncio.TimeoutError:
                resync = True
            self._wake.clear()
            if not resync:
                await asyncio.sleep(COALESCE_SECONDS)
            try:
                frame = await self._refresh()
                targets = list(self._streams)
                if not targets:
                    continue
                if resync:
                    _, text = await self._full()
                elif frame is not None:
                    text = await asyncio.to_thread(json.dumps, frame)
                else:
                    continue
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.exception("peer_listing_feed_failed")
                continue
            self._send_sized(text, targets)
