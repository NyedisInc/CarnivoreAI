
from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Mapping, Tuple

import structlog

from src.core.notifications.destinations import secrets as secret_store
from src.core.notifications.settings_doc.store import SettingsDocStore
from src.core.notifications.sync import merge as merge_mod

log = structlog.get_logger(__name__)

WIRE_VERSION = 1
SOFT_LIMIT_BYTES = 40 * 1024
MAX_BUCKETS = 64
STATUS_OK, STATUS_NO_CHANGE, STATUS_SPLIT = "ok", "no_change", "split"
RESULT_OK, RESULT_NO_CHANGE = "ok", "no_change"

Entries = Dict[str, Dict[str, Any]]
Call = Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]


class ExchangeError(Exception):
    pass


def digest(global_map: Mapping[str, Any]) -> str:
    raw = json.dumps(global_map, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def bucket_of(path: str, buckets: int) -> int:
    return int(hashlib.sha256(path.encode("utf-8")).hexdigest()[:8], 16) % buckets


def split_map(global_map: Mapping[str, Any], buckets: int) -> List[Entries]:
    parts: List[Entries] = [{} for _ in range(buckets)]
    for path, entry in global_map.items():
        parts[bucket_of(path, buckets)][path] = entry  # type: ignore[assignment]
    return parts


def body_size(obj: Any) -> int:
    return len(json.dumps(obj, separators=(",", ":")).encode("utf-8"))


def plan_buckets(global_map: Mapping[str, Any], minimum: int = 1) -> int:
    buckets = max(1, minimum)
    while buckets < MAX_BUCKETS and max(body_size(p) for p in split_map(global_map, buckets)) > SOFT_LIMIT_BYTES:
        buckets *= 2
    return buckets


def handle_exchange(store: SettingsDocStore, body: Mapping[str, Any], now: float) -> Tuple[Dict[str, Any], Tuple[str, ...]]:
    buckets, bucket = body.get("buckets"), body.get("bucket")
    if (not isinstance(buckets, int) or isinstance(buckets, bool) or not 1 <= buckets <= MAX_BUCKETS
            or not isinstance(bucket, int) or isinstance(bucket, bool) or not 0 <= bucket < buckets
            or not isinstance(body.get("digest"), str) or body.get("v") != WIRE_VERSION):
        raise ValueError("bad exchange body")
    if digest(store.snapshot()["global"]) == body["digest"]:
        return {"status": STATUS_NO_CHANGE}, ()
    outcome = merge_mod.merge_into(store, body.get("entries"), now)
    after = store.snapshot()["global"]
    answer: Entries = {
        p: e for p, e in after.items()
        if bucket_of(p, buckets) == bucket and outcome.incoming.get(p) != e
    }
    if body_size(answer) > SOFT_LIMIT_BYTES and buckets < MAX_BUCKETS:
        return {"status": STATUS_SPLIT, "buckets": buckets * 2}, outcome.deleted_dests
    return {"status": STATUS_OK, "entries": answer}, outcome.deleted_dests


async def serve_exchange(store: SettingsDocStore, secrets: secret_store.DestinationSecrets, body: Mapping[str, Any],
                         now: float) -> Dict[str, Any]:
    answer, deleted = await asyncio.to_thread(handle_exchange, store, body, now)
    for dest_id in deleted:
        try:
            await secrets.delete(dest_id)
        except (secret_store.SecretError, OSError) as exc:
            log.warning("notification_sync_secret_cleanup_failed", dest_id=dest_id, error=type(exc).__name__)
    return answer


@dataclass(frozen=True)
class ExchangeResult:

    result: str
    changed: bool
    deleted_dests: tuple = ()


async def run_exchange(store: SettingsDocStore, call: Call, clock: Callable[[], float]) -> ExchangeResult:
    snapshot = dict(store.snapshot()["global"])
    mine_digest = digest(snapshot)
    buckets = plan_buckets(snapshot)
    changed, deleted = False, []
    for _ in range(4):
        parts = split_map(snapshot, buckets)
        restart = False
        for index, entries in enumerate(parts):
            reply = await call({"v": WIRE_VERSION, "digest": mine_digest, "buckets": buckets, "bucket": index,
                                "entries": entries})
            status = reply.get("status") if isinstance(reply, dict) else None
            if status == STATUS_NO_CHANGE:
                return ExchangeResult(RESULT_NO_CHANGE if not changed else RESULT_OK, changed, tuple(deleted))
            if status == STATUS_SPLIT:
                wanted = reply.get("buckets")
                if not isinstance(wanted, int) or isinstance(wanted, bool) or not buckets < wanted <= MAX_BUCKETS:
                    raise ExchangeError("bad split request")
                buckets, restart = wanted, True
                break
            if status != STATUS_OK or not isinstance(reply.get("entries"), dict):
                raise ExchangeError("unexpected answer")
            outcome = await asyncio.to_thread(merge_mod.merge_into, store, reply["entries"], clock())
            changed = changed or outcome.changed
            deleted.extend(outcome.deleted_dests)
        if not restart:
            return ExchangeResult(RESULT_OK, changed, tuple(deleted))
    raise ExchangeError("the peer kept asking to split")
