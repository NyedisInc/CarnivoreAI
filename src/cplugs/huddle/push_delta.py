
from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
import sqlite3
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Set, Tuple

import structlog

from src.cplugs.huddle import lane, lists_read, owner_read, service, slim
from src.cplugs.huddle.rules import TaskManagerError, TaskManagerNotFound, check_list_key
from src.cplugs.sdk import CapabilityMissing, CplugContext, CplugSchemaError

logger = structlog.get_logger()

LIST_TOPIC = "list"
DELTA_TOPIC = "delta"
MAX_ITEMS = 50
MAX_BYTES = 512 * 1024
READ_ERRORS = (sqlite3.Error, OSError, TaskManagerError, CplugSchemaError, CapabilityMissing)

ListState = Tuple[Dict[int, str], str]


def digest(value: Any) -> str:
    return hashlib.sha1(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def item_digest(item: Dict[str, Any]) -> str:
    return digest({k: v for k, v in item.items() if k != "number"})


def list_meta(body: Dict[str, Any]) -> Dict[str, Any]:
    items = body["items"]
    return {"list": body["list"], "revision": body["revision"], "groups": body.get("groups", []), "inbox": body.get("inbox"),
            "order": [i["id"] for i in items], "numbers": {str(i["id"]): i.get("number") for i in items},
            "swarm": [i["id"] for i in items if i.get("lane") == lane.SWARM],
            "done_count": body.get("done_count", 0), "done_swarm": body.get("done_swarm", 0)}


def diff_list(previous: Optional[ListState], body: Dict[str, Any],
              departed: Callable[[List[int]], List[Dict[str, Any]]] = lambda _ids: []) -> Tuple[Optional[Dict[str, Any]], ListState]:
    digests = {i["id"]: item_digest(i) for i in body["items"]}
    meta = list_meta(body)
    state: ListState = (digests, digest(meta))
    old_items, old_meta = previous or ({}, "")
    changed = [i for i in body["items"] if old_items.get(i["id"]) != digests[i["id"]]]
    deleted = sorted(set(old_items) - set(digests))
    if not changed and not deleted and state[1] == old_meta:
        return None, state
    completed = departed(deleted) if deleted else []
    return {**meta, "items": [slim.slim_item(i) for i in changed + completed], "deleted": deleted}, state


def is_empty(body: Dict[str, Any]) -> bool:
    return not body["items"] and not body.get("done_count") and not body.get("groups") and not body.get("inbox")


def keys_of(topics: Iterable[str]) -> Tuple[Set[str], bool]:
    keys: Set[str] = set()
    everything = False
    for topic in topics:
        _family, sep, key = topic.partition(":")
        if sep and key:
            keys.add(key)
        else:
            everything = True
    return keys, everything


def completed_rows(store: Any, key: str, ids: Iterable[int]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for item_id in ids:
        try:
            row = store.item(item_id)
        except TaskManagerNotFound:
            continue
        if row.get("list") == key:
            rows.append(row)
    return rows


class DeltaPublisher:

    def __init__(self, ctx: CplugContext, publish: Optional[Callable[[Dict[str, Any]], bool]] = None,
                 offload: Optional[Callable[[Callable[[], Any]], Awaitable[Any]]] = None) -> None:
        self._ctx = ctx
        self._publish = publish or (lambda data: ctx.push_data(DELTA_TOPIC, data))
        self._offload = offload or asyncio.to_thread
        self._states: Optional[Dict[str, ListState]] = None
        self._rows_digest = ""
        self._pending: Set[str] = set()
        self._everything = False
        self._task: Optional[asyncio.Task] = None
        self._closed = False
        self.seq = 0
        self.epoch = secrets.token_hex(6)

    def marker(self) -> Dict[str, Any]:
        return {"delta_seq": self.seq, "delta_epoch": self.epoch}

    def start(self) -> None:
        self._kick()

    def on_topics(self, topics: List[str]) -> None:
        keys, everything = keys_of(topics)
        self._pending |= keys
        self._everything = self._everything or everything
        self._kick()

    def close(self) -> None:
        self._closed = True
        if self._task is not None and not self._task.done():
            self._task.cancel()
        self._task = None
        self._states = None

    async def idle(self) -> None:
        while self._task is not None and not self._task.done():
            await asyncio.shield(self._task)

    def _kick(self) -> None:
        if self._closed or (self._task is not None and not self._task.done()):
            return
        self._task = asyncio.get_running_loop().create_task(self._drain())

    def _take(self) -> Tuple[Set[str], bool]:
        keys, everything = self._pending, self._everything
        self._pending, self._everything = set(), False
        return keys, everything

    async def _drain(self) -> None:
        while not self._closed:
            if self._states is None:
                missed = bool(self._pending) or self._everything
                self._take()
                try:
                    self._states, self._rows_digest = await self._offload(self._seed)
                except READ_ERRORS as exc:
                    logger.warning("task_manager_delta_seed_failed", error_type=type(exc).__name__, error=str(exc)[:200])
                    self._emit({"resync": True})
                    return
                if missed:
                    self._emit({"resync": True})
                continue
            if not self._pending and not self._everything:
                return
            frame = await self._build(*self._take())
            if frame is not None:
                self._emit(frame)

    def _seed(self) -> Tuple[Dict[str, ListState], str]:
        store = service.store(self._ctx)
        states = {group["list"]: diff_list(None, group)[1] for group in store.aggregate(live_only=True)["groups"]}
        return states, digest(lists_read.build_lists(self._ctx, hide_swarm=True)["lists"])

    def _diff(self, keys: Set[str], everything: bool) -> Tuple[List[Dict[str, Any]], Optional[List[Dict[str, Any]]]]:
        states = self._states if self._states is not None else {}
        store = service.store(self._ctx)
        if everything:
            keys = keys | set(states) | {group["list"] for group in store.aggregate(live_only=True)["groups"]}
        entries: List[Dict[str, Any]] = []
        for key in sorted(keys):
            try:
                check_list_key(key)
            except TaskManagerError:
                logger.warning("task_manager_delta_bad_key", list=key)
                continue
            body = store.list_items(key, live_only=True)
            entry, state = diff_list(states.get(key), body, lambda ids, key=key: completed_rows(store, key, ids))
            if is_empty(body):
                states.pop(key, None)
            else:
                states[key] = state
            if entry is not None:
                entries.append(entry)
        rows = lists_read.build_lists(self._ctx, hide_swarm=True)["lists"]
        rows_digest = digest(rows)
        moved = rows_digest != self._rows_digest
        self._rows_digest = rows_digest
        return entries, rows if moved else None

    async def _build(self, keys: Set[str], everything: bool) -> Optional[Dict[str, Any]]:
        try:
            entries, rows = await self._offload(lambda: self._diff(keys, everything))
            await owner_read.annotate_tagged(self._ctx, [item for entry in entries for item in entry["items"]])
        except READ_ERRORS as exc:
            logger.warning("task_manager_delta_read_failed", error_type=type(exc).__name__, error=str(exc)[:200])
            self._states = None
            return {"resync": True}
        if not entries and rows is None:
            return None
        frame: Dict[str, Any] = {"lists": entries, **({"list_rows": rows} if rows is not None else {})}
        changed = sum(len(entry["items"]) for entry in entries)
        size = len(json.dumps(frame, default=str))
        if changed > MAX_ITEMS or size > MAX_BYTES:
            logger.info("task_manager_delta_resync", changed=changed, bytes=size)
            return {"resync": True}
        return frame

    def _emit(self, body: Dict[str, Any]) -> None:
        self.seq += 1
        if not self._publish({"seq": self.seq, "epoch": self.epoch, **body}):
            logger.debug("task_manager_delta_unpublished", seq=self.seq)


_active: Optional[DeltaPublisher] = None
_remove_listener: Optional[Callable[[], None]] = None


def start(ctx: CplugContext) -> DeltaPublisher:
    global _active, _remove_listener
    stop()
    _active = DeltaPublisher(ctx)
    _remove_listener = ctx.follow(LIST_TOPIC, _active.on_topics)
    _active.start()
    return _active


def stop() -> None:
    global _active, _remove_listener
    if _remove_listener is not None:
        _remove_listener()
    _remove_listener = None
    if _active is not None:
        _active.close()
    _active = None


def marker() -> Dict[str, Any]:
    return _active.marker() if _active is not None else {}
