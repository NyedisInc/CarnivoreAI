
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import AsyncIterator, Callable, Dict, List, Mapping, Optional

import structlog

from src.config import settings
from src.config.mcp_launch import CHANNEL_HEADER, CHANNEL_HEADER_VALUE

logger = structlog.get_logger()

CAPABILITY = "claude/channel"
METHOD = "notifications/claude/channel"
TOOLS_CHANGED_METHOD = "notifications/tools/list_changed"
STREAM_MAX_S = 600.0
KEEPALIVE_S = 15.0
RETRY_MS = 1000
MAX_QUEUED = 64
GRACEFUL_SHUTDOWN_S = 2


def channels_enabled() -> bool:
    try:
        return bool(settings.load_auth_config().mcp.channels)
    except (ValueError, OSError) as exc:
        logger.warning("mcp_channels_config_unreadable", error=type(exc).__name__)
        return False


def channel_requested(headers: Mapping[str, str]) -> bool:
    return headers.get(CHANNEL_HEADER.lower()) == CHANNEL_HEADER_VALUE


def notification(content: str, meta: Mapping[str, str]) -> dict:
    clean = {k: str(v) for k, v in meta.items() if k.isidentifier() and k.isascii()}
    return {"jsonrpc": "2.0", "method": METHOD, "params": {"content": content, "meta": clean}}


_END: object = object()


@dataclass
class Stream:

    tmux_name: str
    session_id: str
    opened_at: float = field(default_factory=time.monotonic)
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=MAX_QUEUED))


class ChannelRegistry:

    def __init__(self) -> None:
        self._streams: Dict[str, List[Stream]] = {}

    def open(self, tmux_name: str, session_id: str) -> Stream:
        stream = Stream(tmux_name, session_id)
        self._streams.setdefault(tmux_name, []).append(stream)
        logger.info("mcp_channel_opened", tmux_session=tmux_name, session_id=session_id,
                    streams=len(self._streams[tmux_name]))
        return stream

    def close(self, stream: Stream) -> None:
        rows = self._streams.get(stream.tmux_name, [])
        if stream in rows:
            rows.remove(stream)
        if not rows:
            self._streams.pop(stream.tmux_name, None)
        dropped = stream.queue.qsize()
        if dropped:
            logger.warning("mcp_channel_events_dropped", tmux_session=stream.tmux_name, dropped=dropped)
        logger.info("mcp_channel_closed", tmux_session=stream.tmux_name, session_id=stream.session_id,
                    lived_s=round(time.monotonic() - stream.opened_at, 1))

    def end_all(self) -> int:
        count = 0
        for rows in list(self._streams.values()):
            for stream in rows:
                while True:
                    try:
                        stream.queue.put_nowait(_END)
                        break
                    except asyncio.QueueFull:
                        stream.queue.get_nowait()
                count += 1
        return count

    def is_open(self, tmux_name: Optional[str]) -> bool:
        return bool(tmux_name and self._streams.get(tmux_name))

    def count(self) -> int:
        return sum(len(rows) for rows in self._streams.values())

    def push(self, tmux_name: Optional[str], content: str, meta: Mapping[str, str]) -> bool:
        rows = self._streams.get(tmux_name or "")
        if not rows:
            return False
        try:
            rows[-1].queue.put_nowait(notification(content, meta))
        except asyncio.QueueFull:
            logger.warning("mcp_channel_queue_full", tmux_session=tmux_name)
            return False
        return True


REGISTRY = ChannelRegistry()


def _sse(message: dict) -> str:
    return "event: message\ndata: " + json.dumps(message, separators=(",", ":")) + "\n\n"


async def stream_events(tmux_name: str, session_id: str, registry: Optional[ChannelRegistry] = None,
                        max_s: Optional[float] = None, keepalive_s: Optional[float] = None,
                        fingerprint: Optional[Callable[[], str]] = None) -> AsyncIterator[str]:
    registry = REGISTRY if registry is None else registry
    max_s = STREAM_MAX_S if max_s is None else max_s
    keepalive_s = KEEPALIVE_S if keepalive_s is None else keepalive_s
    stream = registry.open(tmux_name, session_id)
    seen = fingerprint() if fingerprint else ""
    deadline = time.monotonic() + max_s
    try:
        yield f"retry: {RETRY_MS}\n\n"
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                while not stream.queue.empty():
                    message = stream.queue.get_nowait()
                    if message is not _END:
                        yield _sse(message)
                return
            try:
                message = await asyncio.wait_for(stream.queue.get(), timeout=min(keepalive_s, left))
            except asyncio.TimeoutError:
                now = fingerprint() if fingerprint else seen
                if now != seen:
                    seen = now
                    yield _sse({"jsonrpc": "2.0", "method": TOOLS_CHANGED_METHOD})
                else:
                    yield ": keepalive\n\n"
                continue
            if message is _END:
                return
            yield _sse(message)
    finally:
        registry.close(stream)
