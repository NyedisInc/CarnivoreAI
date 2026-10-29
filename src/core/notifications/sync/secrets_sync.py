
from __future__ import annotations

import asyncio
import collections
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Deque, Dict, List, Mapping, Optional

import structlog

from src.core.notifications import doc_model, kind_specs
from src.core.notifications.destinations import secrets as secret_store
from src.core.notifications.destinations import validate
from src.core.notifications.settings_doc import view
from src.core.notifications.settings_doc.store import Doc, SettingsDocStore
from src.core.notifications.sync import seen

log = structlog.get_logger(__name__)

MAX_IDS_PER_REQUEST = 10
RATE_LIMIT = 30
RATE_WINDOW_SECONDS = 60.0
Fetch = Callable[[List[str]], Awaitable[Dict[str, Any]]]


class RateLimiter:

    def __init__(self, limit: int = RATE_LIMIT, window: float = RATE_WINDOW_SECONDS,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._limit, self._window, self._clock = limit, window, clock
        self._hits: Dict[str, Deque[float]] = {}

    def allow(self, key: str) -> bool:
        now = self._clock()
        hits = self._hits.setdefault(key, collections.deque())
        while hits and hits[0] <= now - self._window:
            hits.popleft()
        if len(hits) >= self._limit:
            return False
        hits.append(now)
        return True


async def serve(store: SettingsDocStore, secrets: secret_store.DestinationSecrets,
                dest_ids: List[Any]) -> Dict[str, Any]:
    doc = await asyncio.to_thread(store.snapshot)
    served: Dict[str, Any] = {}
    refused: List[str] = []
    unavailable: List[str] = []
    for dest_id in dest_ids[:MAX_IDS_PER_REQUEST]:
        if (not isinstance(dest_id, str) or not kind_specs.is_destination_id(dest_id)
                or view.dest_scope(doc, dest_id) != view.SRC_GLOBAL):
            refused.append(str(dest_id)[:32])
            continue
        rev = seen.seen_rev(doc, dest_id)
        try:
            fields = await secrets.get(dest_id) if rev else None
        except secret_store.SecretError:
            fields = None
        if fields is None:
            unavailable.append(dest_id)
        else:
            served[dest_id] = {"rev": rev, "fields": fields}
    return {"secrets": served, "refused": refused, "unavailable": unavailable}


@dataclass
class PullResult:

    stored: List[str] = field(default_factory=list)
    still_stale: List[str] = field(default_factory=list)


def _checked_fields(spec: kind_specs.KindSpec, raw: Any) -> Optional[Dict[str, str]]:
    if not isinstance(raw, Mapping) or not all(isinstance(v, str) for v in raw.values()):
        return None
    try:
        return validate.validate_fields(spec.secret_fields, raw, spec)
    except validate.InvalidDestination:
        return None


def _mark(dest_id: str, rev: int) -> Callable[[Doc, str], Optional[Doc]]:
    def mutate(doc: Doc, me: str) -> Optional[Doc]:
        if view.dest_scope(doc, dest_id) != view.SRC_GLOBAL or rev <= seen.seen_rev(doc, dest_id):
            return None
        return seen.mark_seen(doc, dest_id, rev)
    return mutate


async def pull_stale(store: SettingsDocStore, secrets: secret_store.DestinationSecrets, fetch: Fetch,
                     peer_label: str) -> PullResult:
    result = PullResult()
    doc = await asyncio.to_thread(store.snapshot)
    stale = seen.stale_destinations(doc)
    for start in range(0, len(stale), MAX_IDS_PER_REQUEST):
        ids = stale[start:start + MAX_IDS_PER_REQUEST]
        reply = await fetch(ids)
        served = reply.get("secrets") if isinstance(reply, dict) else None
        served = served if isinstance(served, dict) else {}
        for dest_id in ids:
            doc = await asyncio.to_thread(store.snapshot)
            entry = served.get(dest_id)
            record = doc["global"].get(doc_model.dest_path(dest_id))
            spec = kind_specs.get_kind(record["val"]["kind"]) if record and "val" in record else None
            rev = entry.get("rev") if isinstance(entry, dict) else None
            wanted = seen.record_rev(record["val"]) if spec is not None else 0
            fields = _checked_fields(spec, entry.get("fields")) if spec is not None and isinstance(entry, dict) else None
            if fields is None or not isinstance(rev, int) or isinstance(rev, bool) or rev < wanted:
                result.still_stale.append(dest_id)
                continue
            try:
                stored = await secrets.put_verified(dest_id, fields)
            except secret_store.SecretError as exc:
                log.warning("notification_sync_secret_rejected", dest_id=dest_id, peer=peer_label,
                            error_type=type(exc).__name__)
                result.still_stale.append(dest_id)
                continue
            if not stored:
                log.warning("notification_sync_secret_write_failed", dest_id=dest_id, peer=peer_label)
                result.still_stale.append(dest_id)
                continue
            await asyncio.to_thread(store.update, _mark(dest_id, rev))
            result.stored.append(dest_id)
            log.info("notification_sync_secret_stored", dest_id=dest_id, peer=peer_label)
    return result
