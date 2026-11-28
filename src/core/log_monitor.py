
import asyncio
from typing import AsyncGenerator, Set
from datetime import datetime
import structlog

from src.config import settings
from src.core.session_output import tap as output_tap
from src.models import LogEntry, WSLogMessage
from src.utils.patterns import PatternDetector, PatternMatch

logger = structlog.get_logger()

_PORT_PATTERN_NAMES: frozenset[str] = frozenset({
    "localhost_server",
    "url_with_port",
    "listening_on_port",
    "port_keyword",
    "server_ready",
})
_PORT_INDICATORS: tuple[str, ...] = (
    ":",
    "port",
    "http",
    "localhost",
    "0.0.0.0",
    "127.0.0.1",
    "listening",
    "serving",
    "bound",
    "bind",
    "server",
)
_PORT_INDICATORS_BYTES: tuple[bytes, ...] = tuple(tok.encode("ascii") for tok in _PORT_INDICATORS)


class LogMonitor:

    def __init__(self, session_manager):
        self.session_manager = session_manager
        self.pattern_detector = PatternDetector()
        self.is_monitoring = False
        self._subscribers: Set[asyncio.Queue] = set()

    def subscribe(self) -> asyncio.Queue:
        queue = asyncio.Queue(maxsize=100)
        self._subscribers.add(queue)
        logger.debug("log_subscriber_added", total_subscribers=len(self._subscribers))
        return queue

    def unsubscribe(self, queue: asyncio.Queue):
        self._subscribers.discard(queue)
        logger.debug("log_subscriber_removed", total_subscribers=len(self._subscribers))

    async def _broadcast_log(self, content: str, log_type: str = "stdout"):
        if not self._subscribers:
            return

        message = WSLogMessage(
            timestamp=datetime.utcnow(),
            content=content,
            log_type=log_type
        )

        for queue in self._subscribers.copy():
            try:
                queue.put_nowait(message.model_dump_json())
            except asyncio.QueueFull:
                logger.warning("subscriber_queue_full")
            except Exception as e:
                logger.error("broadcast_error", error=str(e), error_type=type(e).__name__, exc_info=True)

    def _active_pattern_names(self) -> list[str]:
        return [name for name, cbs in self.pattern_detector.callbacks.items() if cbs]

    def _on_session_output(self, session_id: str, data: bytes) -> None:
        active = self._active_pattern_names()
        if not active:
            return
        if self.session_manager is not None:
            registry = getattr(self.session_manager, "_registry", None)
            backend = registry.get_backend(session_id) if registry is not None else None
            if backend is not None and getattr(backend, "replay_in_progress", False):
                return
        if all(name in _PORT_PATTERN_NAMES for name in active):
            lowered = data.lower()
            if not any(tok in lowered for tok in _PORT_INDICATORS_BYTES):
                return
        try:
            matches = self.scan_chunk(data.decode("utf-8", errors="replace"))
            if matches:
                self.dispatch_chunk_matches(matches)
        except Exception as exc:  # noqa: BLE001
            logger.debug("pattern_detection_error", error=str(exc))

    def scan_chunk(self, content: str) -> list:
        active = self._active_pattern_names()
        if not active:
            return []
        if all(name in _PORT_PATTERN_NAMES for name in active):
            lowered = content.lower()
            if not any(tok in lowered for tok in _PORT_INDICATORS):
                return []
        found = []
        for i, line in enumerate(content.split("\n")):
            if line.strip():
                matches = self.pattern_detector.scan_patterns(line, i, only_names=active)
                for match in matches:
                    logger.debug(
                        "pattern_detected_in_output",
                        pattern=match.pattern_name,
                        length=len(match.matched_text),
                    )
                found.extend(matches)
        return found

    def dispatch_chunk_matches(self, matches: list) -> None:
        self.pattern_detector.dispatch_matches(matches)

    def _detect_patterns(self, content: str):
        self.dispatch_chunk_matches(self.scan_chunk(content))

    def register_pattern_callback(self, pattern_name: str, callback):
        self.pattern_detector.register_callback(pattern_name, callback)
        logger.info("pattern_callback_registered", pattern=pattern_name)

    async def start_monitoring(self):
        if self.is_monitoring:
            logger.warning("monitoring_already_active")
            return
        self.is_monitoring = True
        output_tap.TAP.add(self._on_session_output)
        logger.info("log_monitoring_started")

    async def stop_monitoring(self):
        if not self.is_monitoring:
            return
        output_tap.TAP.remove(self._on_session_output)
        self.is_monitoring = False
        logger.info("log_monitoring_stopped")

    async def get_log_stream(self) -> AsyncGenerator[str, None]:
        queue = self.subscribe()

        try:
            while True:
                log_entry = await queue.get()
                yield log_entry
        finally:
            self.unsubscribe(queue)
