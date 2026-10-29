
from __future__ import annotations

import asyncio
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import structlog

from src.core.resource_push import topics as topics_module
from src.core.resource_push.topics import all_topics, family_of
from src.models.websocket import WSMessageType

logger = structlog.get_logger()

DEFAULT_WINDOW_SECONDS = 0.25


class ResourceNotifier:

    def __init__(
        self,
        publish: Callable[[Dict[str, Any]], int],
        loop: asyncio.AbstractEventLoop,
        *,
        window_seconds: float = DEFAULT_WINDOW_SECONDS,
    ) -> None:
        self._publish = publish
        self._loop = loop
        self.window_seconds = window_seconds
        self._pending: Set[str] = set()
        self._handle: Optional[asyncio.TimerHandle] = None
        self.seq = 0
        self._last_sent: Dict[Tuple[str, str], float] = {}
        self._trailing: Dict[Tuple[str, str], asyncio.TimerHandle] = {}

    def notify(self, topic: str) -> None:
        if family_of(topic) not in all_topics():
            logger.warning("resource_push_unknown_topic", topic=topic)
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is self._loop:
            self._add(topic)
            return
        try:
            self._loop.call_soon_threadsafe(self._add, topic)
        except RuntimeError as exc:
            logger.debug("resource_push_loop_closed", topic=topic, error=str(exc))

    def notify_coalesced(self, topic: str, key: str, min_interval: float) -> None:
        try:
            self._loop.call_soon_threadsafe(self._coalesce, topic, key, min_interval)
        except RuntimeError as exc:
            logger.debug("resource_push_loop_closed", topic=topic, error=str(exc))

    def _coalesce(self, topic: str, key: str, min_interval: float) -> None:
        slot = (topic, key)
        if slot in self._trailing:
            return
        now = self._loop.time()
        wait = self._last_sent.get(slot, float("-inf")) + min_interval - now
        if wait <= 0:
            self._last_sent[slot] = now
            self.notify(topic)
            return
        self._trailing[slot] = self._loop.call_later(wait, self._send_trailing, slot)

    def _send_trailing(self, slot: Tuple[str, str]) -> None:
        self._trailing.pop(slot, None)
        self._last_sent[slot] = self._loop.time()
        self.notify(slot[0])

    def _add(self, topic: str) -> None:
        self._pending.add(topic)
        if self._handle is None:
            self._handle = self._loop.call_later(self.window_seconds, self.flush)

    def flush(self) -> Optional[Dict[str, Any]]:
        if self._handle is not None:
            self._handle.cancel()
        self._handle = None
        if not self._pending:
            return None
        topics = sorted(self._pending)
        self._pending.clear()
        self.seq += 1
        frame = {"type": WSMessageType.RESOURCES_CHANGED.value, "topics": topics, "seq": self.seq}
        try:
            self._publish(frame)
        except (RuntimeError, ValueError, TypeError) as exc:
            logger.warning("resource_push_publish_failed", topics=topics, error=str(exc))
        _run_topic_listeners(topics)
        return frame

    def publish(self, frame: Dict[str, Any]) -> int:
        return self._publish(frame)

    def close(self) -> None:
        if self._handle is not None:
            self._handle.cancel()
        self._handle = None
        self._pending.clear()
        for handle in self._trailing.values():
            handle.cancel()
        self._trailing.clear()


SESSION_SET_FRAME_TYPES = frozenset({"sessions.changed", "session.renamed"})
SESSION_SET_TOPICS = (topics_module.AUTO_SLEEP, topics_module.PROJECTS, topics_module.RESTORE_OFFER)


def on_hub_publish(frame_type: Optional[str]) -> None:
    if frame_type in SESSION_SET_FRAME_TYPES:
        for topic in SESSION_SET_TOPICS:
            notify(topic)


_active: Optional[ResourceNotifier] = None

_topic_listeners: List[Tuple[str, Callable[[], None]]] = []


def add_topic_listener(topic: str, listener: Callable[[], None]) -> Callable[[], None]:
    entry = (topic, listener)
    _topic_listeners.append(entry)
    return lambda: _topic_listeners.remove(entry) if entry in _topic_listeners else None


_family_listeners: List[Tuple[str, Callable[[List[str]], None]]] = []


def add_family_listener(family: str, listener: Callable[[List[str]], None]) -> Callable[[], None]:
    entry = (family, listener)
    _family_listeners.append(entry)
    return lambda: _family_listeners.remove(entry) if entry in _family_listeners else None


def _run_topic_listeners(named: List[str]) -> None:
    for topic, listener in list(_topic_listeners):
        if topic in named:
            try:
                listener()
            except (RuntimeError, ValueError, TypeError, AttributeError) as exc:
                logger.warning("resource_push_listener_failed", topic=topic, error=str(exc))
    for family, family_listener in list(_family_listeners):
        members = [topic for topic in named if family_of(topic) == family]
        if members:
            try:
                family_listener(members)
            except (RuntimeError, ValueError, TypeError, AttributeError) as exc:
                logger.warning("resource_push_listener_failed", topic=family, error=str(exc))


def publish_frame(frame: Dict[str, Any]) -> bool:
    notifier = _active
    if notifier is None:
        return False
    try:
        notifier.publish(frame)
    except (RuntimeError, ValueError, TypeError) as exc:
        logger.warning("resource_push_frame_publish_failed", frame_type=frame.get("type"), error=str(exc))
        return False
    return True


def install(
    publish: Callable[[Dict[str, Any]], int],
    *,
    loop: Optional[asyncio.AbstractEventLoop] = None,
    window_seconds: float = DEFAULT_WINDOW_SECONDS,
) -> ResourceNotifier:
    global _active
    if _active is not None:
        _active.close()
    _active = ResourceNotifier(
        publish, loop or asyncio.get_running_loop(), window_seconds=window_seconds
    )
    return _active


def uninstall() -> None:
    global _active
    if _active is not None:
        _active.close()
    _active = None


def notify(topic: str) -> None:
    notifier = _active
    if notifier is not None:
        notifier.notify(topic)


def notify_coalesced(topic: str, key: str, min_interval: float) -> None:
    notifier = _active
    if notifier is not None:
        notifier.notify_coalesced(topic, key, min_interval)
