
from __future__ import annotations

import asyncio
import random
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional

import structlog

from src.core.notifications.destinations import secrets as secret_store
from src.core.notifications.settings_doc.store import Doc, SettingsDocStore
from src.core.notifications.sync import secrets_sync, status as st, wire
from src.core.notifications.sync.peers import PeerCallError, PeerGateway, PeerInfo

log = structlog.get_logger(__name__)

EXCHANGE_PATH = "/federation/notify-sync/exchange"
SECRETS_PATH = "/federation/notify-sync/secrets"
DEBOUNCE_SECONDS = 2.0
PERIODIC_SECONDS = 600.0
JITTER_FRACTION = 0.2
MAX_CONCURRENT_PEERS = 2
RETRY_SECONDS = 30.0
MAX_RETRIES = 3


def _http_result(status: int) -> str:
    if status in (401, 403):
        return st.R_REFUSED
    return st.R_RATE_LIMITED if status == 429 else st.R_ERROR


class SyncManager:

    def __init__(self, store: SettingsDocStore, secrets: secret_store.DestinationSecrets, gateway: PeerGateway,
                 *, clock: Callable[[], float] = time.time,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> None:
        self.store, self._secrets, self.gateway = store, secrets, gateway
        self._clock, self._sleep = clock, sleep
        self.status = st.SyncStatus()
        self._wake: Optional[asyncio.Event] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._run_lock: Optional[asyncio.Lock] = None
        self._last_digest = ""


    def attach(self, loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
        if self._loop is not None:
            return
        self._loop = loop or asyncio.get_running_loop()
        self._wake = self._wake or asyncio.Event()
        self._run_lock = self._run_lock or asyncio.Lock()
        self._last_digest = wire.digest(self.store.snapshot()["global"])
        self.store.add_listener(self._on_local_write)

    def _on_local_write(self, doc: Doc) -> None:
        digest = wire.digest(doc["global"])
        if digest != self._last_digest:
            self._last_digest = digest
            self.request_sync()

    def request_sync(self) -> None:
        if self._loop is not None and self._wake is not None:
            self._loop.call_soon_threadsafe(self._wake.set)


    async def sync_peer(self, peer: PeerInfo) -> str:
        result = await self._pass(peer)
        self.status.record(peer.install_id, result, self._clock())
        log.info("notification_sync_pass", peer=peer.label, result=result)
        return result

    async def _pass(self, peer: PeerInfo) -> str:
        doc = await asyncio.to_thread(self.store.snapshot)
        if not st.is_enabled(doc, peer.install_id):
            await self.gateway.set_scope(peer.install_id, False)
            return st.R_OFF
        if not peer.connected:
            return st.R_DISCONNECTED
        if not peer.speaks_sync:
            return st.R_OLDER
        await self.gateway.set_scope(peer.install_id, True)
        try:
            outcome = await wire.run_exchange(self.store, self._caller(peer, EXCHANGE_PATH), self._clock)
        except PeerCallError as exc:
            return st.R_REFUSED if exc.reason == "refused" else st.R_DISCONNECTED
        except _HttpFailure as exc:
            return _http_result(exc.status)
        except wire.ExchangeError:
            return st.R_ERROR
        for dest_id in outcome.deleted_dests:
            await self._drop_secret(dest_id)
        try:
            await secrets_sync.pull_stale(self.store, self._secrets, self._secret_fetch(peer), peer.label)
        except PeerCallError as exc:
            return st.R_REFUSED if exc.reason == "refused" else st.R_DISCONNECTED
        except _HttpFailure as exc:
            return _http_result(exc.status)
        return st.R_NO_CHANGE if outcome.result == wire.RESULT_NO_CHANGE else st.R_OK

    def _caller(self, peer: PeerInfo, path: str) -> Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]:
        async def call(body: Dict[str, Any]) -> Dict[str, Any]:
            status, data = await self.gateway.post(peer.install_id, path, body)
            if status != 200 or not isinstance(data, dict):
                raise _HttpFailure(status)
            return data
        return call

    def _secret_fetch(self, peer: PeerInfo) -> Callable[[List[str]], Awaitable[Dict[str, Any]]]:
        call = self._caller(peer, SECRETS_PATH)

        async def fetch(ids: List[str]) -> Dict[str, Any]:
            return await call({"dest_ids": ids})
        return fetch

    async def _drop_secret(self, dest_id: str) -> None:
        try:
            await self._secrets.delete(dest_id)
        except (secret_store.SecretError, OSError) as exc:
            log.warning("notification_sync_secret_cleanup_failed", dest_id=dest_id, error=type(exc).__name__)


    async def sync_all(self) -> Dict[str, str]:
        roster = await self.gateway.roster()
        gate = asyncio.Semaphore(MAX_CONCURRENT_PEERS)
        results: Dict[str, str] = {}

        async def one(peer: PeerInfo) -> None:
            async with gate:
                try:
                    results[peer.install_id] = await self.sync_peer(peer)
                except Exception as exc:  # noqa: BLE001
                    log.warning("notification_sync_pass_failed", peer=peer.label, error=type(exc).__name__)
                    self.status.record(peer.install_id, st.R_ERROR, self._clock())
                    results[peer.install_id] = st.R_ERROR

        await asyncio.gather(*(one(p) for p in roster))
        return results

    async def peer_connected(self, install_id: str) -> None:
        self.request_sync()

    async def run(self) -> None:
        self.attach()
        assert self._wake is not None and self._run_lock is not None
        retries = 0
        while True:
            period = PERIODIC_SECONDS * (1 + random.uniform(-JITTER_FRACTION, JITTER_FRACTION))
            if retries:
                period = RETRY_SECONDS
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=period)
                await self._sleep(DEBOUNCE_SECONDS)
            except asyncio.TimeoutError:
                pass
            self._wake.clear()
            async with self._run_lock:
                results = await self.sync_all()
            retries = retries + 1 if st.R_REFUSED in results.values() and retries < MAX_RETRIES else 0


class _HttpFailure(Exception):

    def __init__(self, status: int) -> None:
        super().__init__(status)
        self.status = status
