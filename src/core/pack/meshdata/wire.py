
from __future__ import annotations

import asyncio
import collections
import hashlib
import json
import random
import threading
from typing import Any, Awaitable, Callable, Dict, List, Mapping, Optional, Tuple

import structlog

from src.core.pack.machines.roster_v2 import RosterV2
from src.core.pack.meshdata import envelope, hlc
from src.core.pack.meshdata.store import RecordStore


class WireError(ValueError):
    pass


log = structlog.get_logger(__name__)

WIRE_VERSION = 1
SOFT_LIMIT_BYTES = 40 * 1024
HARD_LIMIT_BYTES = 60 * 1024
MAX_BUCKETS = 512
MAX_ENTRIES_PER_REQUEST = 512
STATUS_OK, STATUS_NO_CHANGE, STATUS_SPLIT = "ok", "no_change", "split"
RESULT_OK, RESULT_NO_CHANGE = "ok", "no_change"

Records = Dict[str, Dict[str, Any]]
Call = Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]


class ExchangeError(Exception):
    pass


def bucket_of(name: str, buckets: int) -> int:
    return int(hashlib.sha256(name.encode("utf-8")).hexdigest()[:8], 16) % buckets


def split_map(records: Mapping[str, Any], buckets: int) -> List[Records]:
    parts: List[Records] = [{} for _ in range(buckets)]
    for name, entry in records.items():
        parts[bucket_of(name, buckets)][name] = entry
    return parts


_SPLIT_KEEP = 4
_SPLITS: "collections.OrderedDict[Tuple[int, int], Tuple[Any, List[Records]]]" = collections.OrderedDict()
_SPLIT_LOCK = threading.Lock()


def split_cached(records: Records, buckets: int) -> List[Records]:
    key = (id(records), buckets)
    with _SPLIT_LOCK:
        held = _SPLITS.get(key)
        if held is not None and held[0] is records:
            _SPLITS.move_to_end(key)
            return held[1]
    parts = split_map(records, buckets)
    with _SPLIT_LOCK:
        _SPLITS[key] = (records, parts)
        _SPLITS.move_to_end(key)
        while len(_SPLITS) > _SPLIT_KEEP:
            _SPLITS.popitem(last=False)
    return parts


def body_size(obj: Any) -> int:
    return len(json.dumps(obj, separators=(",", ":")).encode("utf-8"))


def plan_buckets(records: Mapping[str, Any], minimum: int = 1) -> int:
    buckets = max(1, minimum)
    sizes = {name: body_size({name: entry}) + 1 for name, entry in records.items()}
    while buckets < MAX_BUCKETS:
        parts = [0] * buckets
        counts = [0] * buckets
        for name, size in sizes.items():
            index = bucket_of(name, buckets)
            parts[index] += size
            counts[index] += 1
        if max(parts) + 2 <= SOFT_LIMIT_BYTES and max(counts) <= MAX_ENTRIES_PER_REQUEST:
            break
        buckets *= 2
    return buckets


def fit(records: Records, limit: int = HARD_LIMIT_BYTES - 1024) -> Records:
    if body_size(records) <= limit:
        return records
    names = list(records)
    random.shuffle(names)
    kept: Records = {}
    used = 2
    for name in names:
        add = body_size({name: records[name]}) + 1
        if used + add <= limit:
            kept[name] = records[name]
            used += add
    log.warning("meshdata_answer_trimmed", kept=len(kept), wanted=len(records))
    return kept


def _lower_or_absent(sent: Any, mine: Mapping[str, Any]) -> bool:
    stamp = hlc.parse_stamp(sent.get("s")) if isinstance(sent, dict) else None
    held = hlc.parse_stamp(mine["s"])
    if stamp is None or held is None or stamp != held:
        return stamp is None or held is None or stamp < held
    try:
        return envelope.body_hash(mine["v"]) > envelope.body_hash(sent.get("v"))
    except (ValueError, TypeError, RecursionError):
        return True


def handle_sync(store: RecordStore, body: Mapping[str, Any], caller_iid: str, lst: Any, now_ms: int, gen: Optional[int] = None) -> Tuple[Dict[str, Any], int]:
    buckets, bucket, records = body.get("buckets"), body.get("bucket"), body.get("records")
    if (not isinstance(buckets, int) or isinstance(buckets, bool) or not 1 <= buckets <= MAX_BUCKETS
            or not isinstance(bucket, int) or isinstance(bucket, bool) or not 0 <= bucket < buckets
            or not isinstance(body.get("digest"), str) or body.get("v") != WIRE_VERSION
            or not isinstance(records, dict) or len(records) > MAX_ENTRIES_PER_REQUEST):
        raise WireError("bad sync body")
    if not isinstance(lst, RosterV2) or lst.entry(caller_iid) is None:
        return {"status": STATUS_NO_CHANGE}, 0
    store.prune(lst, gen=gen)
    if store.view(lst, caller_iid)[1] == body["digest"]:
        return {"status": STATUS_NO_CHANGE}, 0
    store.reconcile(lst, gen=gen)
    outcome = store.offer_batch(records, caller_iid, lst, now_ms, gen=gen)
    answer: Records = {n: e for n, e in split_cached(store.servable(lst, caller_iid), buckets)[bucket].items() if _lower_or_absent(records.get(n), e)}
    if body_size(answer) > SOFT_LIMIT_BYTES and buckets < MAX_BUCKETS:
        return {"status": STATUS_SPLIT, "buckets": buckets * 2}, outcome.accepted
    return {"status": STATUS_OK, "records": fit(answer)}, outcome.accepted


async def run_sync(store: RecordStore, call: Call, lst: Any, peer_iid: str, wall: Callable[[], int] = hlc.wall_ms, *, gen: Optional[int] = None) -> Tuple[str, int]:
    mine, mine_digest = await asyncio.to_thread(store.view, lst, peer_iid)
    buckets, accepted = plan_buckets(mine), 0
    for _ in range(MAX_BUCKETS.bit_length() + 1):
        restart = False
        for index, part in enumerate(split_map(mine, buckets)):
            reply = await call({"v": WIRE_VERSION, "digest": mine_digest, "buckets": buckets, "bucket": index, "records": fit(part)})
            status = reply.get("status") if isinstance(reply, dict) else None
            if status == STATUS_NO_CHANGE:
                return (RESULT_OK if accepted else RESULT_NO_CHANGE), accepted
            if status == STATUS_SPLIT:
                wanted = reply.get("buckets")
                if not isinstance(wanted, int) or isinstance(wanted, bool) or not buckets < wanted <= MAX_BUCKETS:
                    raise ExchangeError("bad split request")
                buckets, restart = wanted, True
                break
            if status != STATUS_OK or not isinstance(reply.get("records"), dict) or len(reply["records"]) > MAX_ENTRIES_PER_REQUEST:
                raise ExchangeError("unexpected answer")
            outcome = await asyncio.to_thread(store.offer_batch, reply["records"], peer_iid, lst, wall(), gen)
            accepted += outcome.accepted
        if not restart:
            return RESULT_OK, accepted
    raise ExchangeError("the peer kept asking to split")
