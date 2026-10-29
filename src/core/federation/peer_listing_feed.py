
from __future__ import annotations

import asyncio
import json
import secrets
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set, Tuple

import structlog

from src.core.bounded_stream import BoundedStream
from src.core.listing_push.diff import KeyedRows, diff, keyed
from src.models import WSMessageType

logger = structlog.get_logger()

FRAME_TYPE = WSMessageType.PEER_LISTING.value
COALESCE_SECONDS = 0.25
RESYNC_SECONDS = 60.0
MAX_FRAME_BYTES = 512 * 1024

View = Callable[[], Awaitable[Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]]]


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
        self._streams: Set[BoundedStream] = set()
        self._wake = asyncio.Event()
        self._task: Optional["asyncio.Task[None]"] = None

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

    def _offer_all(self, text: str, targets: Optional[List[BoundedStream]] = None) -> None:
        for stream in (list(self._streams) if targets is None else [s for s in targets if s in self._streams]):
            stream.offer(text, len(text))

    def _drop_all(self) -> None:
        logger.warning("peer_listing_feed_oversize", sockets=len(self._streams))
        self._offer_all(json.dumps({"type": FRAME_TYPE, "stream": self.stream, "seq": self.seq, "resync": True}))
        self._streams.clear()
        self._list = self._asleep = None

    async def attach(self, stream: BoundedStream) -> None:
        if self._list is None or not self._streams:
            self._list = self._asleep = None
            await self._refresh()
        _, text = await self._full()
        if len(text) > MAX_FRAME_BYTES:
            logger.warning("peer_listing_feed_oversize", sockets=len(self._streams) + 1, attached=False)
            return
        stream.offer(text, len(text))
        self._streams.add(stream)
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="peer-listing-feed")

    def detach(self, stream: BoundedStream) -> None:
        self._streams.discard(stream)
        if not self._streams and self._task is not None:
            self._task.cancel()
            self._task = None
            self._list = self._asleep = None

    async def _run(self) -> None:
        while True:
            try:
                await asyncio.wait_for(self._wake.wait(), RESYNC_SECONDS)
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
            if len(text) > MAX_FRAME_BYTES:
                self._drop_all()
                continue
            self._offer_all(text, targets)
