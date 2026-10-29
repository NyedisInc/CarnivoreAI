
from __future__ import annotations

import itertools
import json
from typing import Any, Callable, Dict, List, Optional

import structlog

from src.core.bounded_stream import (
    OFFER_ACCEPTED,
    OFFER_OVERFLOWED,
    OVERFLOW_CLOSE_CODE,
    REASON_DONE,
    BoundedStream,
)

logger = structlog.get_logger()


MAX_EVENT_QUEUE_ITEMS = 256
MAX_EVENT_QUEUE_BYTES = 1 * 1024 * 1024

EVENTS_OVERFLOW_CLOSE_CODE = OVERFLOW_CLOSE_CODE


class EventClient:

    def __init__(self, client_id: str, stream: BoundedStream, reduced: bool = False) -> None:
        self.client_id = client_id
        self.stream = stream
        self.reduced = reduced


class EventHub:

    def __init__(
        self,
        *,
        max_items: int = MAX_EVENT_QUEUE_ITEMS,
        max_bytes: int = MAX_EVENT_QUEUE_BYTES,
    ) -> None:
        self._clients: Dict[str, EventClient] = {}
        self._ids = itertools.count(1)
        self._max_items = max_items
        self._max_bytes = max_bytes
        self._listeners: List[Callable[[Optional[str]], None]] = []


    def register(self, reduced: bool = False) -> EventClient:
        client_id = f"evt_{next(self._ids)}"
        stream = BoundedStream(
            max_items=self._max_items,
            max_bytes=self._max_bytes,
            label=f"events {client_id}",
        )
        client = EventClient(client_id, stream, reduced)
        self._clients[client_id] = client
        logger.info("event_client_registered", client_id=client_id,
                    total_clients=len(self._clients))
        return client

    def unregister(self, client: EventClient) -> None:
        self._clients.pop(client.client_id, None)
        client.stream.close(REASON_DONE)
        logger.info("event_client_unregistered", client_id=client.client_id,
                    total_clients=len(self._clients))

    @property
    def client_count(self) -> int:
        return len(self._clients)


    def add_listener(self, listener: Callable[[Optional[str]], None]) -> None:
        self._listeners.append(listener)

    def _notify_listeners(self, frame: Dict[str, Any]) -> None:
        frame_type = frame.get("type") if isinstance(frame, dict) else None
        for listener in list(self._listeners):
            try:
                listener(frame_type)
            except Exception as exc:  # noqa: BLE001
                logger.warning("event_listener_failed", frame_type=frame_type,
                               error=str(exc), error_type=type(exc).__name__)

    def has_owner_client(self) -> bool:
        return any(not c.reduced for c in self._clients.values())


    def publish(self, frame: Dict[str, Any], reduced: Optional[Dict[str, Any]] = None) -> int:
        if self._listeners:
            self._notify_listeners(frame)
        if not self._clients:
            return 0
        try:
            try:
                encoded = json.dumps(frame, allow_nan=False)
            except ValueError:
                if reduced is None:
                    raise
                logger.warning("event_frame_body_unencodable", frame_type=frame.get("type"))
                frame, encoded = reduced, json.dumps(reduced, allow_nan=False)
            encoded_reduced = json.dumps(reduced, allow_nan=False) if reduced is not None else encoded
        except (TypeError, ValueError) as exc:
            logger.error(
                "event_frame_unencodable",
                frame_type=frame.get("type") if isinstance(frame, dict) else None,
                error=str(exc),
            )
            return 0

        size = len(encoded.encode("utf-8"))
        size_reduced = len(encoded_reduced.encode("utf-8")) if reduced is not None else size
        delivered = 0
        for client in list(self._clients.values()):
            result = client.stream.offer(encoded_reduced, size_reduced) if client.reduced else client.stream.offer(encoded, size)
            if result == OFFER_ACCEPTED:
                delivered += 1
                continue
            if result == OFFER_OVERFLOWED:
                logger.warning(
                    "event_client_overflowed",
                    client_id=client.client_id,
                    frame_type=frame.get("type"),
                    max_items=client.stream.max_items,
                    max_bytes=client.stream.max_bytes,
                )
            self._clients.pop(client.client_id, None)
        return delivered


def get_hub(app_state: Any) -> Optional[EventHub]:
    hub = getattr(app_state, "event_hub", None)
    return hub if isinstance(hub, EventHub) else None
