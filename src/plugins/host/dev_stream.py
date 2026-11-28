
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, AsyncIterator, Deque, Dict, List, Optional, Set

MAX_HISTORY = 200
KEEPALIVE_SECONDS = 15.0


class DevEventStream:

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._seq = 0
        self._history: Dict[str, Deque[Dict[str, Any]]] = {}
        self._subs: Dict[str, Set[tuple[asyncio.AbstractEventLoop, asyncio.Queue[Dict[str, Any]]]]] = {}

    def publish(self, plugin_id: str, event_type: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        with self._lock:
            self._seq += 1
            entry = {
                "seq": self._seq,
                "ts": time.time(),
                "type": event_type,
                "plugin_id": plugin_id,
                "data": dict(data or {}),
            }
            ring = self._history.setdefault(plugin_id, deque(maxlen=MAX_HISTORY))
            ring.append(entry)
            subs = list(self._subs.get(plugin_id, ()))
        for loop, queue in subs:
            with contextlib.suppress(RuntimeError):
                loop.call_soon_threadsafe(self._offer, queue, entry)
        return entry

    @staticmethod
    def _offer(queue: asyncio.Queue[Dict[str, Any]], entry: Dict[str, Any]) -> None:
        if queue.full():
            with contextlib.suppress(asyncio.QueueEmpty):
                queue.get_nowait()
        with contextlib.suppress(asyncio.QueueFull):
            queue.put_nowait(entry)

    def recent(self, plugin_id: str, after_seq: int = 0) -> List[Dict[str, Any]]:
        with self._lock:
            ring = self._history.get(plugin_id)
            if not ring:
                return []
            return [dict(item) for item in ring if item["seq"] > after_seq]

    async def subscribe(
        self,
        plugin_id: str,
        *,
        after_seq: int = 0,
        replay_only: bool = False,
    ) -> AsyncIterator[str]:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue(maxsize=256)
        sub = (loop, queue)
        with self._lock:
            backlog = [dict(item) for item in self._history.get(plugin_id, ()) if item["seq"] > after_seq]
            if not replay_only:
                self._subs.setdefault(plugin_id, set()).add(sub)
        try:
            for item in backlog:
                yield format_sse(item)
            if replay_only:
                return
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=KEEPALIVE_SECONDS)
                    yield format_sse(item)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            if not replay_only:
                with self._lock:
                    bucket = self._subs.get(plugin_id)
                    if bucket is not None:
                        bucket.discard(sub)


def format_sse(entry: Dict[str, Any]) -> str:
    payload = json.dumps(entry, separators=(",", ":"), default=str)
    return f"id: {entry['seq']}\nevent: {entry['type']}\ndata: {payload}\n\n"


_LOCK = threading.RLock()
_STREAMS: Dict[str, DevEventStream] = {}


def stream_for(state_dir: Path) -> DevEventStream:
    key = os.path.realpath(state_dir)
    with _LOCK:
        stream = _STREAMS.get(key)
        if stream is None:
            stream = DevEventStream()
            _STREAMS[key] = stream
        return stream
