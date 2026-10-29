
from __future__ import annotations

import asyncio
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import structlog

from src.core.resource_push import bodies as bodies_module
from src.core.resource_push import topics as topics_module
from src.core.resource_push.topics import all_topics, family_of
from src.models.websocket import WSMessageType

logger = structlog.get_logger()

DEFAULT_WINDOW_SECONDS = 0.25
PRUNE_ABOVE = 64


class ResourceNotifier:

    def __init__(
        self,
        publish: Callable[[Dict[str, Any]], int],
        loop: asyncio.AbstractEventLoop,
        *,
        window_seconds: float = DEFAULT_WINDOW_SECONDS,
        with_bodies: bool = False,
        wants_bodies: Optional[Callable[[], bool]] = None,
    ) -> None:
        self._publish = publish
        self._loop = loop
        self.window_seconds = window_seconds
        self._with_bodies = with_bodies
        self._wants_bodies = wants_bodies
        self._body_tickets = 0
        self._body_published = 0
        self._body_tasks: Set["asyncio.Task[None]"] = set()
        self._pending: Set[str] = set()
        self._handle: Optional[asyncio.TimerHandle] = None
        self.seq = 0
        self._last_sent: Dict[Tuple[str, str], Tuple[float, float]] = {}
        self._trailing: Dict[Tuple[str, str], asyncio.TimerHandle] = {}
        self._detail: Dict[Tuple[str, str], str] = {}

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

    def notify_coalesced(self, topic: str, key: str, min_interval: float, detail: Optional[str] = None) -> None:
        try:
            self._loop.call_soon_threadsafe(self._coalesce, topic, key, min_interval, detail)
        except RuntimeError as exc:
            logger.debug("resource_push_loop_closed", topic=topic, error=str(exc))

    def _coalesce(self, topic: str, key: str, min_interval: float, detail: Optional[str] = None) -> None:
        slot = (topic, key)
        named = detail or topic
        if slot in self._trailing:
            if self._detail.get(slot, named) != named:
                self._detail[slot] = topic
            return
        now = self._loop.time()
        sent = self._last_sent.get(slot, (float("-inf"), 0.0))[0]
        wait = sent + min_interval - now
        if wait <= 0:
            self._sweep(now)
            self._last_sent[slot] = (now, min_interval)
            self.notify(named)
            return
        self._detail[slot] = named
        self._trailing[slot] = self._loop.call_later(wait, self._send_trailing, slot, min_interval)

    def _sweep(self, now: float) -> None:
        if len(self._last_sent) <= PRUNE_ABOVE:
            return
        for slot in [s for s, (sent, interval) in self._last_sent.items() if sent + interval <= now and s not in self._trailing]:
            del self._last_sent[slot]

    def _send_trailing(self, slot: Tuple[str, str], min_interval: float) -> None:
        self._trailing.pop(slot, None)
        now = self._loop.time()
        self._sweep(now)
        self._last_sent[slot] = (now, min_interval)
        self.notify(self._detail.pop(slot, slot[0]))

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
        providers = bodies_module.matching(topics) if self._with_bodies and (self._wants_bodies is None or self._wants_bodies()) else []
        if providers:
            held = [t for t in topics if family_of(t) in bodies_module.trigger_topics()]
            topics = [t for t in topics if t not in held]
            self._body_tickets += 1
            task = self._loop.create_task(self._flush_with_bodies(held, providers, self._body_tickets))
            self._body_tasks.add(task)
            task.add_done_callback(self._body_tasks.discard)
            if not topics:
                return None
        self.seq += 1
        frame = {"type": WSMessageType.RESOURCES_CHANGED.value, "topics": topics, "seq": self.seq}
        try:
            self._publish(frame)
        except (RuntimeError, ValueError, TypeError) as exc:
            logger.warning("resource_push_publish_failed", topics=topics, error=str(exc))
        _run_topic_listeners(topics)
        return frame

    async def _flush_with_bodies(self, held: List[str], providers: List[bodies_module.BodyProvider], ticket: int) -> None:
        built = await bodies_module.collect(providers)
        if ticket < self._body_published:
            built = {}
        else:
            self._body_published = ticket
        self.seq += 1
        frame: Dict[str, Any] = {"type": WSMessageType.RESOURCES_CHANGED.value, "topics": held, "seq": self.seq}
        try:
            if built:
                self._publish({**frame, "bodies": built}, reduced=frame)
            else:
                self._publish(frame)
        except (RuntimeError, ValueError, TypeError) as exc:
            logger.warning("resource_push_publish_failed", topics=held, error=str(exc))
        _run_topic_listeners(held)

    def publish(self, frame: Dict[str, Any]) -> int:
        return self._publish(frame)

    def close(self) -> None:
        if self._handle is not None:
            self._handle.cancel()
        self._handle = None
        self._pending.clear()
        for task in list(self._body_tasks):
            task.cancel()
        for handle in self._trailing.values():
            handle.cancel()
        self._trailing.clear()
        self._detail.clear()


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
    with_bodies: bool = False,
    wants_bodies: Optional[Callable[[], bool]] = None,
) -> ResourceNotifier:
    global _active
    if _active is not None:
        _active.close()
    _active = ResourceNotifier(
        publish, loop or asyncio.get_running_loop(), window_seconds=window_seconds, with_bodies=with_bodies,
        wants_bodies=wants_bodies,
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


def notify_coalesced(topic: str, key: str, min_interval: float, detail: Optional[str] = None) -> None:
    notifier = _active
    if notifier is not None:
        notifier.notify_coalesced(topic, key, min_interval, detail)
