
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional, Set

import structlog

from src.config import settings
from src.core.graceful_shutdown.task_stop import cancel_and_await
from src.core.auto_sleep.port_owner import MeasureError, find_port_owner
from src.core.tmux_backend import DEFAULT_SOCKET_NAME
from src.models import LocalServerInfo
from src.models.utc_time import utc_now
from src.utils.patterns import (
    PatternMatch,
    is_valid_dev_port,
    port_is_listening,
)

logger = structlog.get_logger()


JANITOR_INTERVAL_SECONDS = 30.0

PROBE_TIMEOUT_MS = 250


def _resolve_lan_host() -> str:
    host = (getattr(settings, "host", None) or "").strip()
    if not host or host in ("0.0.0.0", "::"):
        return "127.0.0.1"
    return host


def _build_url(port: int) -> str:
    return f"http://{_resolve_lan_host()}:{port}"


class LocalServersTracker:

    def __init__(
        self,
        loop: Optional[asyncio.AbstractEventLoop] = None,
        socket_name: str = DEFAULT_SOCKET_NAME,
    ):
        self._loop = loop
        self._socket_name = socket_name
        self._state: Dict[str, Dict[int, LocalServerInfo]] = {}
        self._subscribers: Set[asyncio.Queue] = set()
        self._janitor_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        self._pattern_tasks: "Set[asyncio.Task[None]]" = set()
        self._log_monitor: Optional[Any] = None
        self._session_manager: Optional[Any] = None


    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=50)
        self._subscribers.add(queue)
        logger.debug(
            "local_server_subscriber_added", total=len(self._subscribers)
        )
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)
        logger.debug(
            "local_server_subscriber_removed", total=len(self._subscribers)
        )

    def _broadcast(self, payload: Dict[str, Any]) -> None:
        if not self._subscribers:
            return
        message = json.dumps(payload)
        for queue in tuple(self._subscribers):
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                logger.warning(
                    "local_server_subscriber_full",
                    type=payload.get("type"),
                )
            except Exception as exc:
                logger.error(
                    "local_server_broadcast_error", error=str(exc)
                )


    async def record(self, session_name: str, port: int) -> Optional[LocalServerInfo]:
        if not session_name or not is_valid_dev_port(port):
            return None

        bucket = self._state.get(session_name)
        if bucket and port in bucket:
            existing = bucket[port]
            existing.last_seen = utc_now()
            return existing

        if not port_is_listening(port, timeout_ms=PROBE_TIMEOUT_MS):
            logger.debug(
                "local_server_probe_negative",
                session=session_name,
                port=port,
            )
            return None

        now = utc_now()
        info = LocalServerInfo(
            port=port,
            url=_build_url(port),
            first_seen=now,
            last_seen=now,
        )
        async with self._lock:
            self._state.setdefault(session_name, {})[port] = info

        logger.info(
            "local_server_detected",
            session=session_name,
            port=port,
            url=info.url,
        )
        self._broadcast(
            {
                "type": "local_server_detected",
                "session": session_name,
                "port": port,
                "url": info.url,
            }
        )
        return info

    async def forget(self, session_name: str, port: int) -> bool:
        bucket = self._state.get(session_name)
        if not bucket or port not in bucket:
            return False

        async with self._lock:
            bucket = self._state.get(session_name)
            if not bucket or port not in bucket:
                return False
            bucket.pop(port, None)
            if not bucket:
                self._state.pop(session_name, None)

        logger.info(
            "local_server_lost", session=session_name, port=port
        )
        self._broadcast(
            {
                "type": "local_server_lost",
                "session": session_name,
                "port": port,
            }
        )
        return True

    async def clear_session(self, session_name: str) -> None:
        bucket = self._state.get(session_name)
        if not bucket:
            return
        ports = list(bucket.keys())
        for port in ports:
            await self.forget(session_name, port)

    def list_for_session(self, session_name: str) -> List[LocalServerInfo]:
        bucket = self._state.get(session_name)
        if not bucket:
            return []
        return [bucket[p] for p in sorted(bucket.keys())]

    def snapshot(self) -> Dict[str, List[LocalServerInfo]]:
        return {
            name: [bucket[p] for p in sorted(bucket.keys())]
            for name, bucket in self._state.items()
        }


    def attach(self, log_monitor: Any, session_manager: Any) -> None:
        self._log_monitor = log_monitor
        self._session_manager = session_manager

        for pattern_name in (
            "localhost_server",
            "url_with_port",
            "listening_on_port",
            "port_keyword",
            "server_ready",
        ):
            log_monitor.register_pattern_callback(
                pattern_name, self._spawn_pattern_task
            )

        logger.info("local_servers_attached_to_log_monitor")

    def _spawn_pattern_task(self, match: PatternMatch) -> None:
        task = asyncio.create_task(self._on_pattern_match(match))
        self._pattern_tasks.add(task)
        task.add_done_callback(self._pattern_tasks.discard)

    def _refresh_if_tracked(self, port: int) -> bool:
        tracked = [bucket[port] for bucket in self._state.values() if port in bucket]
        for info in tracked:
            info.last_seen = utc_now()
        return bool(tracked)

    async def _on_pattern_match(self, match: PatternMatch) -> None:
        if self._log_monitor is None or self._session_manager is None:
            return

        port = self._log_monitor.pattern_detector.extract_port(
            match.matched_text
        )
        if not port:
            return
        if self._refresh_if_tracked(port):
            return

        try:
            session_name = await asyncio.to_thread(
                find_port_owner, port, self._socket_name
            )
        except MeasureError as exc:
            logger.debug("local_server_owner_unmeasured", port=port, error=str(exc))
            return
        if not session_name:
            return

        try:
            await self.record(session_name, port)
        except Exception as exc:
            logger.debug(
                "local_server_record_error",
                session=session_name,
                port=port,
                error=str(exc),
            )

    async def start(self) -> None:
        if self._janitor_task is not None and not self._janitor_task.done():
            return
        if self._loop is None:
            self._loop = asyncio.get_running_loop()
        self._janitor_task = asyncio.create_task(self._janitor_loop())
        logger.info("local_servers_janitor_started")

    async def stop(self) -> None:
        await cancel_and_await(self._janitor_task, "local_servers_janitor_crashed")
        self._janitor_task = None
        self._subscribers.clear()
        logger.info("local_servers_janitor_stopped")

    async def _janitor_loop(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            try:
                await asyncio.sleep(JANITOR_INTERVAL_SECONDS)

                pairs: List[tuple] = []
                for session_name, bucket in self._state.items():
                    for port in bucket.keys():
                        pairs.append((session_name, port))

                for session_name, port in pairs:
                    try:
                        alive = await loop.run_in_executor(
                            None,
                            port_is_listening,
                            port,
                            PROBE_TIMEOUT_MS,
                        )
                    except Exception as exc:
                        logger.debug(
                            "local_server_probe_error",
                            session=session_name,
                            port=port,
                            error=str(exc),
                        )
                        continue
                    if not alive:
                        await self.forget(session_name, port)

            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("local_servers_janitor_error", error=str(exc))
                await asyncio.sleep(min(JANITOR_INTERVAL_SECONDS, 5.0))
