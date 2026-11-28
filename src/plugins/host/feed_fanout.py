
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

import structlog

from src.core import session_change_notice
from src.core.session_output.tap import TAP
from src.plugins.runtime.guards import SESSION_FIELDS
from src.plugins.runtime.process import FEED_GRANTS

logger = structlog.get_logger()

FEED_META = "feed.meta"
FEED_SCRUBBED = "feed.scrubbed"
FEED_RAW = "feed.raw"
OUTPUT_FAMILIES = frozenset({FEED_SCRUBBED, FEED_RAW})
ALL_FEED_FAMILIES = frozenset({FEED_META, FEED_SCRUBBED, FEED_RAW})

DeliverFn = Callable[[str, str, int, Any], Awaitable[bool]]
SubscribersFn = Callable[[str], List[str]]


class FeedFanout:

    def __init__(self, deliver: DeliverFn, subscribers: SubscribersFn, *, queue_size: int = 256) -> None:
        self._deliver = deliver
        self._subscribers = subscribers
        self._queue_size = max(16, int(queue_size))
        self._queue: Optional[asyncio.Queue[Tuple[str, Any]]] = None
        self._worker: Optional[asyncio.Task[Any]] = None
        self._tap_attached = False
        self._notice_attached = False
        self._seq: Dict[str, int] = {}
        self._stopped = False

    def _ensure_worker(self) -> None:
        if self._stopped or (self._worker is not None and not self._worker.done()):
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if self._queue is None:
            self._queue = asyncio.Queue(maxsize=self._queue_size)
        self._worker = loop.create_task(self._drain_loop())

    def refresh(self) -> None:
        if self._stopped:
            return
        want_meta = bool(self._subscribers(FEED_META))
        want_output = bool(self._subscribers(FEED_SCRUBBED) or self._subscribers(FEED_RAW))
        if want_meta or want_output:
            self._ensure_worker()
        if want_output and not self._tap_attached:
            TAP.add(self._on_chunk)
            self._tap_attached = True
        elif not want_output and self._tap_attached:
            TAP.remove(self._on_chunk)
            self._tap_attached = False
        if want_meta and not self._notice_attached:
            session_change_notice.add_frame_listener(self._on_notice)
            self._notice_attached = True
        elif not want_meta and self._notice_attached:
            session_change_notice.remove_frame_listener(self._on_notice)
            self._notice_attached = False

    def _enqueue(self, kind: str, item: Any) -> None:
        if self._stopped or self._queue is None:
            return
        try:
            self._queue.put_nowait((kind, item))
        except asyncio.QueueFull:
            logger.debug("cplug_feed_queue_full", kind=kind)

    def _on_chunk(self, session_id: str, data: bytes) -> None:
        if data:
            self._enqueue("chunk", (session_id, data))

    def _on_notice(self, frame: Dict[str, Any]) -> None:
        if isinstance(frame, dict):
            self._enqueue("meta", dict(frame))

    def _next_seq(self, plugin_id: str) -> int:
        nxt = self._seq.get(plugin_id, 0) + 1
        self._seq[plugin_id] = nxt
        return nxt

    async def _drain_loop(self) -> None:
        assert self._queue is not None
        try:
            while not self._stopped:
                kind, item = await self._queue.get()
                if kind == "meta":
                    await self._handle_meta(item)
                elif kind == "chunk":
                    session_id, data = item
                    await self._handle_chunk(session_id, data)
        except asyncio.CancelledError:
            return

    async def _handle_meta(self, frame: Dict[str, Any]) -> None:
        targets = self._subscribers(FEED_META)
        if not targets:
            return
        allowed_keys = ("type", "session_id", "activity_status", "reason", "startup_gate", *SESSION_FIELDS)
        payload = {
            k: frame[k]
            for k in allowed_keys
            if k in frame and frame[k] is not None
        }
        for plugin_id in targets:
            try:
                await self._deliver(plugin_id, FEED_META, self._next_seq(plugin_id), payload)
            except Exception as exc:  # noqa: BLE001
                logger.warning("cplug_feed_deliver_failed", cplug=plugin_id, family=FEED_META, error_type=type(exc).__name__)

    async def _handle_chunk(self, session_id: str, data: bytes) -> None:
        scrub_targets = self._subscribers(FEED_SCRUBBED)
        raw_targets = self._subscribers(FEED_RAW)
        if not scrub_targets and not raw_targets:
            return
        text = data.decode("utf-8", errors="replace")
        if raw_targets:
            raw_payload = {"session_id": session_id, "text": text}
            for plugin_id in raw_targets:
                try:
                    await self._deliver(plugin_id, FEED_RAW, self._next_seq(plugin_id), raw_payload)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("cplug_feed_deliver_failed", cplug=plugin_id, family=FEED_RAW, error_type=type(exc).__name__)
        if scrub_targets:
            from src.core.mcp import tools as mcp_tools  # noqa: PLC0415

            scrubbed_text = mcp_tools.redact_text(mcp_tools.strip_ansi(text))
            scrub_payload = {"session_id": session_id, "text": scrubbed_text}
            for plugin_id in scrub_targets:
                try:
                    await self._deliver(plugin_id, FEED_SCRUBBED, self._next_seq(plugin_id), scrub_payload)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("cplug_feed_deliver_failed", cplug=plugin_id, family=FEED_SCRUBBED, error_type=type(exc).__name__)

    async def stop(self) -> None:
        self._stopped = True
        if self._tap_attached:
            TAP.remove(self._on_chunk)
            self._tap_attached = False
        if self._notice_attached:
            session_change_notice.remove_frame_listener(self._on_notice)
            self._notice_attached = False
        if self._worker is not None:
            self._worker.cancel()
            await asyncio.gather(self._worker, return_exceptions=True)
            self._worker = None


def feed_subscribers_for(host: Any, definitions: List[Any], family: str) -> List[str]:
    needed = FEED_GRANTS.get(family, ())
    out: List[str] = []
    for d in definitions:
        if not host.enabled(d.id):
            continue
        subs = getattr(d.manifest, "subscriptions", ()) or ()
        if family not in subs:
            continue
        if needed and not any(g in host._live_grants(d.manifest) for g in needed):
            continue
        out.append(d.id)
    return out
