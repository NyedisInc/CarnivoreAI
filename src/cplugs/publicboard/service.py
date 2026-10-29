
from __future__ import annotations

import asyncio
from typing import Any, Mapping, Optional

import structlog

from src.cplugs.publicboard.edge import EdgeConfig, PublicEdge
from src.cplugs.publicboard.settings import PublicBoardSettings, SettingsError, parse_settings
from src.cplugs.sdk.public_listener import ListenerSpec, PublicListener, PublicListenerError, canonical_ip

logger = structlog.get_logger()


class PublicBoardService:

    def __init__(self) -> None:
        self._listener: Optional[PublicListener] = None
        self._lock = asyncio.Lock()
        self._starting: Optional["asyncio.Future[bool]"] = None

    @property
    def listener(self) -> Optional[PublicListener]:
        return self._listener

    async def apply(self, raw_settings: Mapping[str, Any]) -> bool:
        async with self._lock:
            await self._close()
            try:
                settings = parse_settings(raw_settings)
            except SettingsError as exc:
                logger.warning("publicboard_not_started", reason="invalid_settings", detail=str(exc))
                return False
            if not settings.configured:
                logger.info("publicboard_not_started", reason="no_hostname_or_proxy")
                return False
            self._starting = asyncio.ensure_future(self._start(settings))
            try:
                return await self._starting
            except asyncio.CancelledError:
                if asyncio.current_task().cancelling():  # type: ignore[union-attr]
                    raise
                logger.info("publicboard_start_cancelled")
                return False
            finally:
                self._starting = None

    async def _start(self, settings: PublicBoardSettings) -> bool:
        edge = PublicEdge(EdgeConfig.of(settings.trusted_proxies, settings.hostnames))
        proxies = frozenset(settings.trusted_proxies)
        spec = ListenerSpec(host=settings.bind, port=settings.port, peer_allowed=lambda host: canonical_ip(host) in proxies)
        listener = PublicListener(edge, spec)
        try:
            await listener.start()
        except PublicListenerError as exc:
            logger.error("publicboard_not_started", reason="bind_failed", detail=str(exc))
            return False
        self._listener = listener
        return True

    async def _close(self) -> None:
        listener, self._listener = self._listener, None
        if listener is not None:
            await listener.stop()

    async def stop(self) -> None:
        starting = self._starting
        if starting is not None and not starting.done():
            starting.cancel()
        async with self._lock:
            await self._close()


SERVICE = PublicBoardService()
