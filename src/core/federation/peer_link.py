
from __future__ import annotations

import asyncio
import contextlib
from typing import Awaitable, Callable, Optional

import structlog

from src.core.computers import direction
from src.core.federation import peer_client
from src.core.federation.peer_client import PeerClient, PeerRefused, PeerUnreachable, Route
from src.core.hosts.ssh_master import backoff_delay

logger = structlog.get_logger()

CONNECTING, CONNECTED, DISCONNECTED = "connecting", "connected", "disconnected"
INCOMPATIBLE, UNPAIRED, IDENTITY_CHANGED = "incompatible", "unpaired", "identity_changed"
REFUSED = "refused"
HEARTBEAT_SECONDS = 10.0
MISSES_BEFORE_LOSS = 2
SLOW_RECHECK_SECONDS = 60.0
RENEW_EVERY = 6


class LinkDown(Exception):
    """``establish`` could not bring the route up. The message is safe to log."""


class LinkRefused(LinkDown):
    pass


class PeerLink:

    def __init__(self, *, peer_install_id: str, establish: Callable[[], Awaitable[Route]],
                 make_client: Callable[[Route], PeerClient],
                 on_state: Optional[Callable[[str, Optional[int]], None]] = None,
                 heartbeat: float = HEARTBEAT_SECONDS, delay: Callable[[int], float] = backoff_delay,
                 renew: Optional[Callable[[PeerClient], Awaitable[None]]] = None,
                 settle: Optional[Callable[[], Awaitable[None]]] = None,
                 on_beat: Optional[Callable[[PeerClient], Awaitable[None]]] = None) -> None:
        self.peer_install_id = peer_install_id
        self._establish, self._make_client, self._on_state = establish, make_client, on_state
        self._heartbeat, self._delay, self._renew, self._settle = heartbeat, delay, renew, settle
        self._on_beat = on_beat
        self.capabilities: list = []
        self.state = DISCONNECTED
        self.protocol: Optional[int] = None
        self.minor = 0
        self.client: Optional[PeerClient] = None
        self._task: Optional["asyncio.Task[None]"] = None

    def live_client(self) -> Optional[PeerClient]:
        return self.client if self.state == CONNECTED else None

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name=f"peer-link-{self.peer_install_id[:8]}")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._set(DISCONNECTED)

    def _set(self, state: str, protocol: Optional[int] = None) -> None:
        if protocol is not None:
            self.protocol = protocol
        if state == self.state and protocol is None:
            return
        changed = state != self.state
        self.state = state
        if changed:
            logger.info("peer_link_state", peer=self.peer_install_id[:8], state=state)
        if self._on_state is not None:
            try:
                self._on_state(state, self.protocol)
            except Exception:  # noqa: BLE001
                logger.exception("peer_link_on_state_failed")

    async def _hello(self, client: PeerClient) -> Optional[str]:
        response = await client.request("GET", "/federation/hello")
        if response.status_code != 200:
            raise PeerRefused(f"http_{response.status_code}")
        data = response.json()
        verdict = peer_client.hello_ok(data, self.peer_install_id)
        self.minor = data.get("protocol_minor") if isinstance(data.get("protocol_minor"), int) else 0
        caps = data.get("capabilities")
        self.capabilities = [c for c in caps if isinstance(c, str)][:64] if isinstance(caps, list) else []
        direction.note_restrictions(self.peer_install_id, data.get("restrictions_for_caller"))
        self._set(verdict or CONNECTED, data.get("protocol") if isinstance(data.get("protocol"), int) else None)
        return verdict

    async def _exchange(self, client: PeerClient) -> None:
        if self._on_beat is None:
            return
        try:
            await self._on_beat(client)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("peer_link_on_beat_failed")

    async def _run(self) -> None:
        attempt = 0
        while True:
            wait = self._delay(attempt)
            try:
                if self._settle is not None:
                    await self._settle()
                self._set(CONNECTING)
                client = self.client = self._make_client(await self._establish())
                verdict = await self._hello(client)
                if verdict is None:
                    attempt = 0
                    await self._exchange(client)
                    await self._beat(client)
                else:
                    wait = SLOW_RECHECK_SECONDS
            except PeerRefused as exc:
                logger.warning("peer_link_refused", peer=self.peer_install_id[:8], code=exc.code)
                self._set(UNPAIRED if exc.code == "grant_invalid" else IDENTITY_CHANGED
                          if exc.code == "identity_changed" else DISCONNECTED)
                wait = SLOW_RECHECK_SECONDS
            except LinkRefused as exc:
                logger.warning("peer_link_tls_refused", peer=self.peer_install_id[:8], reason=str(exc)[:120])
                self._set(REFUSED)
                wait = SLOW_RECHECK_SECONDS
            except (PeerUnreachable, LinkDown) as exc:
                logger.info("peer_link_down", peer=self.peer_install_id[:8], reason=str(exc)[:120])
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.exception("peer_link_failed", peer=self.peer_install_id[:8])
            if self.state not in (UNPAIRED, INCOMPATIBLE, IDENTITY_CHANGED, REFUSED):
                self._set(DISCONNECTED)
            attempt += 1
            await asyncio.sleep(wait)

    async def _beat(self, client: PeerClient) -> None:
        misses = beats = 0
        while True:
            await asyncio.sleep(self._heartbeat)
            try:
                if await self._hello(client) is not None:
                    return
                misses = 0
                beats += 1
                await self._exchange(client)
                if self._renew is not None and beats % RENEW_EVERY == 0:
                    await self._renew(client)
            except PeerUnreachable as exc:
                misses += 1
                if exc.hard or misses >= MISSES_BEFORE_LOSS:
                    self._set(DISCONNECTED)
                    return
