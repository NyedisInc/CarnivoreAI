"""The TUI's copy of the pushed session listing (mirror of web/src/lib/listing-push/store.ts).

THE SERVER COMPUTES, THIS FILE ONLY APPLIES. A snapshot (``GET /sessions/listing``)
seeds the store; ``listing.delta`` frames then arrive with a stream id and a
sequence. A frame in order is applied, a gap or a new stream resyncs, a frame
that arrives during a resync is buffered and replayed after it. A row keeps the
two levels the route answers with (wrapper fields on the wrapper, ``.session``
nested) and a null the server sent stays null: nothing here defaults a field.
"""

from __future__ import annotations

import asyncio
import copy
from typing import Any, Awaitable, Callable, Optional

import structlog

logger = structlog.get_logger(__name__)

LIVENESS = "$live"

Snapshot = dict[str, Any]
Row = dict[str, Any]
FetchSnapshot = Callable[[], Awaitable[Snapshot]]


def _key_of(name: str, row: Row) -> Optional[str]:
    if name == "list":
        session = row.get("session")
        key = session.get("id") if isinstance(session, dict) else None
    elif name == "attachable":
        key = row.get("name")
    else:
        key = row.get("session_uuid")
    return key if isinstance(key, str) else None


class _Held:

    def __init__(self) -> None:
        self.by_key: dict[str, Row] = {}
        self.order: list[str] = []
        self.status: dict[str, Any] = {"ok": True, "status": None, "detail": None, "meta": {}}


class ListingStore:

    def __init__(self, fetch_snapshot: FetchSnapshot) -> None:
        self._fetch = fetch_snapshot
        self._stream: Optional[str] = None
        self._seq = 0
        self._live = False
        self._syncing: Optional[asyncio.Task[None]] = None
        self._buffered: list[dict[str, Any]] = []
        self._cols: dict[str, _Held] = {}
        self._listeners: list[Callable[[list[str]], None]] = []

    def is_live(self) -> bool:
        return self._live

    def rows(self, name: str) -> Optional[list[Row]]:
        held = self._cols.get(name)
        if held is None or not held.status["ok"]:
            return None
        return copy.deepcopy([held.by_key[k] for k in held.order if k in held.by_key])

    def on_change(self, fn: Callable[[list[str]], None]) -> Callable[[], None]:
        self._listeners.append(fn)
        return lambda: self._listeners.remove(fn) if fn in self._listeners else None

    def hello(self) -> Optional[asyncio.Task[None]]:
        return self.resync()

    def closed(self) -> None:
        if self._syncing is not None:
            self._syncing.cancel()
            self._syncing = None
        self._buffered = []
        self._set_live(False)

    def frame(self, frame: dict[str, Any]) -> None:
        seq = frame.get("seq")
        if not isinstance(seq, int) or not isinstance(frame.get("changes"), dict):
            return
        if self._syncing is not None:
            self._buffered.append(frame)
            return
        if not self._live:
            return
        if frame.get("stream") != self._stream or seq > self._seq + 1:
            self.resync()
            return
        if seq <= self._seq:
            return
        self._apply(frame)
        self._notify(list(frame["changes"]))

    def resync(self) -> asyncio.Task[None]:
        if self._syncing is not None:
            return self._syncing
        self._buffered = []
        self._syncing = asyncio.ensure_future(self._resync())
        return self._syncing

    async def _resync(self) -> None:
        me = self._syncing
        try:
            snap = await self._fetch()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.info("tui_listing_snapshot_failed", error=type(exc).__name__)
            if self._syncing is me:
                self._syncing = None
            self._set_live(False)
            return
        self._load(snap)
        pending = sorted(
            (f for f in self._buffered if f.get("stream") == snap.get("stream") and f["seq"] > snap["seq"]),
            key=lambda f: f["seq"],
        )
        self._buffered = []
        self._syncing = None
        for f in pending:
            if f["seq"] != self._seq + 1:
                self.resync()
                return
            self._apply(f)
        self._live = True
        self._notify([LIVENESS, *self._cols])

    async def poll(self) -> None:
        snap = await self._fetch()
        if self._live:
            return
        self._load(snap)
        self._notify(list(self._cols))

    def _load(self, snap: Snapshot) -> None:
        self._stream, self._seq = snap.get("stream"), int(snap.get("seq", 0))
        self._cols.clear()
        for name, col in (snap.get("collections") or {}).items():
            held = _Held()
            for row in col.get("rows") or []:
                key = _key_of(name, row)
                if key is None or key in held.by_key:
                    continue
                held.by_key[key] = row
                held.order.append(key)
            held.status = {"ok": col.get("ok") is not False, "status": col.get("status"),
                           "detail": col.get("detail"), "meta": col.get("meta") or {}}
            self._cols[name] = held

    def _apply(self, frame: dict[str, Any]) -> None:
        for name, change in frame["changes"].items():
            held = self._cols.setdefault(name, _Held())
            for up in change.get("upsert") or []:
                row = held.by_key.get(up["key"])
                if row is None:
                    row = held.by_key[up["key"]] = {}
                    held.order.append(up["key"])
                row.update(up.get("fields") or {})
                for field, part in (up.get("nested") or {}).items():
                    inner = row.get(field)
                    row[field] = {**(inner if isinstance(inner, dict) else {}), **part}
                for field in up.get("drop") or []:
                    row.pop(field, None)
            for key in change.get("remove") or []:
                held.by_key.pop(key, None)
            held.order = [k for k in (change.get("order") or held.order) if k in held.by_key]
            status = change.get("status")
            if status:
                held.status = {"ok": status.get("ok") is not False, "status": status.get("status"),
                               "detail": status.get("detail"), "meta": status.get("meta") or {}}
        self._seq = frame["seq"]

    def _set_live(self, on: bool) -> None:
        if self._live != on:
            self._live = on
            self._notify([LIVENESS])

    def _notify(self, names: list[str]) -> None:
        for fn in list(self._listeners):
            try:
                fn(names)
            except Exception as exc:
                logger.warning("tui_listing_listener_failed", error=type(exc).__name__)
