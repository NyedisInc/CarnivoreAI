
from __future__ import annotations

import asyncio
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

import httpx
import structlog

from src.core.web_push import vapid
from src.core.web_push.encrypt import encrypt_payload
from src.core.web_push.endpoints import endpoint_allowed, host_of
from src.core.web_push.store import SubscriptionStore

logger = structlog.get_logger()

FIXED_PAYLOAD: bytes = json.dumps({"title": "carnivore", "body": "approval needed"}, separators=(",", ":")).encode()
MIN_INTERVAL_SECONDS = 60.0
TTL_SECONDS = 3600
TOPIC = "approval"
REQUEST_TIMEOUT_SECONDS = 10.0
TEST_COOLDOWN_SECONDS = 5.0
_GONE = (404, 410)
COALESCE_SECONDS = 10.0
_COALESCE_KEYS_MAX = 2048


class PushSender:

    def __init__(self, state_dir: Path, config_path: Path, *, transport: Optional[httpx.AsyncBaseTransport] = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.store = SubscriptionStore(state_dir)
        self._state_dir = Path(state_dir)
        self._config_path = Path(config_path)
        self._transport = transport
        self._clock = clock
        self._last_sent: Dict[str, float] = {}
        self._seeded: Set[str] = set()
        self._typed_last: Dict[tuple, float] = {}
        self._last_test = -1e12
        self._lock = asyncio.Lock()

    async def _send_one(self, client: httpx.AsyncClient, row: Dict[str, Any], key: Any, subject: str,
                        payload: bytes = FIXED_PAYLOAD, topic: str = TOPIC) -> Optional[int]:
        endpoint = row["endpoint"]
        if not endpoint_allowed(endpoint):
            logger.warning("web_push_endpoint_refused", host=host_of(endpoint))
            await asyncio.to_thread(self.store.remove, row["id"])
            return None
        try:
            body = encrypt_payload(payload, vapid.b64url_decode(row["p256dh"]), vapid.b64url_decode(row["auth"]))
        except ValueError as exc:
            logger.warning("web_push_bad_subscription_keys", error_type=type(exc).__name__)
            await asyncio.to_thread(self.store.remove, row["id"])
            return None
        headers = {
            "Authorization": vapid.authorization_header(key, endpoint, subject),
            "Content-Encoding": "aes128gcm", "Content-Type": "application/octet-stream",
            "TTL": str(TTL_SECONDS), "Urgency": "high", "Topic": topic,
        }
        try:
            response = await client.post(endpoint, content=body, headers=headers)
            status = response.status_code
        except httpx.InvalidURL:
            logger.warning("web_push_endpoint_invalid", host=host_of(endpoint))
            await asyncio.to_thread(self.store.remove, row["id"])
            return None
        except httpx.HTTPError as exc:
            logger.info("web_push_send_failed", host=host_of(endpoint), error_type=type(exc).__name__)
            status = 0
        if status in _GONE:
            await asyncio.to_thread(self.store.remove, row["id"])
            logger.info("web_push_subscription_gone", host=host_of(endpoint), status=status)
        else:
            await asyncio.to_thread(self.store.record_result, row["id"], status)
        return status

    def _seed_floor(self, row: Dict[str, Any]) -> None:
        if row["id"] in self._seeded:
            return
        self._seeded.add(row["id"])
        try:
            at = datetime.fromisoformat((row.get("last_result") or {})["at"])
            age = (datetime.now(timezone.utc) - at).total_seconds()
        except (KeyError, TypeError, ValueError):
            return
        if 0 <= age < MIN_INTERVAL_SECONDS:
            self._last_sent.setdefault(row["id"], self._clock() - age)

    async def notify(self, *, force: bool = False) -> List[Dict[str, Any]]:
        async with self._lock:
            rows = await asyncio.to_thread(self.store.list)
            for row in rows:
                self._seed_floor(row)
            due = [r for r in rows
                   if force or self._clock() - self._last_sent.get(r["id"], -1e12) >= MIN_INTERVAL_SECONDS]
            if not due:
                return []
            for row in due:
                self._last_sent[row["id"]] = self._clock()
            key = await asyncio.to_thread(vapid.load_or_create_key, self._state_dir)
            subject = await asyncio.to_thread(vapid.subject_from_config, self._config_path)
            async with httpx.AsyncClient(transport=self._transport, timeout=REQUEST_TIMEOUT_SECONDS,
                                         follow_redirects=False) as client:
                statuses = await asyncio.gather(*(self._send_one(client, r, key, subject) for r in due))
        return [{"id": r["id"], "status": s} for r, s in zip(due, statuses) if s is not None]

    def _coalesced(self, sub_id: str, type_id: str, instance: str = "") -> bool:
        last = self._typed_last.get((sub_id, type_id, instance))
        return last is not None and 0 <= self._clock() - last < COALESCE_SECONDS

    def _record_delivered(self, sub_id: str, type_id: str, instance: str) -> None:
        if len(self._typed_last) >= _COALESCE_KEYS_MAX:
            self._typed_last.pop(next(iter(self._typed_last)))
        self._typed_last[(sub_id, type_id, instance)] = self._clock()

    async def send_typed(self, sub_id: str, type_id: str, payload: Dict[str, str], instance: str = "") -> Optional[int]:
        rows = await asyncio.to_thread(self.store.list)
        row = next((r for r in rows if r.get("id") == sub_id), None)
        if row is None:
            return None
        if self._coalesced(sub_id, type_id, instance):
            return 200
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        topic = hashlib.sha256(f"{type_id}\0{instance}".encode("utf-8")).hexdigest()[:24]
        key = await asyncio.to_thread(vapid.load_or_create_key, self._state_dir)
        subject = await asyncio.to_thread(vapid.subject_from_config, self._config_path)
        async with httpx.AsyncClient(transport=self._transport, timeout=REQUEST_TIMEOUT_SECONDS,
                                     follow_redirects=False) as client:
            status = await self._send_one(client, row, key, subject, body, topic)
        if status is not None and 200 <= status < 300:
            self._record_delivered(sub_id, type_id, instance)
        return status

    async def notify_test(self) -> Optional[List[Dict[str, Any]]]:
        if self._clock() - self._last_test < TEST_COOLDOWN_SECONDS:
            return None
        self._last_test = self._clock()
        return await self.notify(force=True)
