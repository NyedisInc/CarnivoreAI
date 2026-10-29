
import asyncio
from typing import AsyncGenerator, Set
from datetime import datetime
import structlog

from src.config import settings
from src.models import LogEntry, WSLogMessage
from src.utils.patterns import PatternDetector, PatternMatch

logger = structlog.get_logger()


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
                logger.error("broadcast_error", error=str(e))

    def _detect_patterns(self, content: str):
        lines = content.split("\n")

        for i, line in enumerate(lines):
            if line.strip():
                matches = self.pattern_detector.detect_patterns(line, i)

                for match in matches:
                    logger.info(
                        "pattern_detected_in_output",
                        pattern=match.pattern_name,
                        length=len(match.matched_text),
                    )

    def register_pattern_callback(self, pattern_name: str, callback):
        self.pattern_detector.register_callback(pattern_name, callback)
        logger.info("pattern_callback_registered", pattern=pattern_name)

    async def start_monitoring(self):
        if self.is_monitoring:
            logger.warning("monitoring_already_active")
            return
        self.is_monitoring = True
        logger.info("log_monitoring_started")

    async def stop_monitoring(self):
        if not self.is_monitoring:
            return
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
