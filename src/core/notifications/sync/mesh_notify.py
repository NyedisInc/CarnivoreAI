
from __future__ import annotations

import asyncio
import sqlite3
import time
from typing import Any, Dict, List, Optional, Tuple

import structlog

from src.core.notifications import doc_model
from src.core.notifications.settings_doc.store import Doc, SettingsDocStore
from src.core.notifications.sync import merge, status, wire
from src.core.pack.machines import capabilities
from src.core.pack.machines.roster_v2 import RosterV2
from src.core.pack.meshdata import gossip, notify_kind
from src.core.pack.meshdata.store import canonical

log = structlog.get_logger(__name__)

KIND = notify_kind.KIND


def _off_ids(doc: Doc) -> List[str]:
    raw = doc["local"].get(status.OFF_KEY)
    return sorted(i for i in raw if isinstance(i, str)) if isinstance(raw, list) else []


def attach(docs: SettingsDocStore) -> None:
    state: Dict[str, Any] = {"wake": None, "memo": None, "beat": {}, "gen": None}

    def _on_write(doc: Doc) -> None:
        mark = (wire.digest(doc["global"]), tuple(_off_ids(doc)))
        if mark != state["wake"]:
            state["wake"] = mark
            gossip.wake()

    def _publish(service: Any, lst: RosterV2, doc: Doc, rows: Dict[str, Tuple[Any, Any]], gen: Optional[int], now: float) -> int:
        own, me = service.store.own_iid, docs.install_id()
        beat: Dict[str, str] = state["beat"]
        wins: Dict[str, str] = {}
        items: List[Tuple[str, Any, None]] = []
        skipped = 0
        for path, entry in doc_model.prune_tombstones(doc["global"], now).items():
            if not notify_kind.valid(path, entry):
                skipped += path.partition("/")[0] in notify_kind.ALLOWED
                continue
            held = rows.get(path)
            if held is not None and (canonical(held[0]) == canonical(entry) or doc_model.pick_winner(entry, held[0]) is not entry):
                continue
            mark = canonical(entry)
            wins[path] = mark
            if entry["ver"][1] == me or lst.alpha == own or beat.get(path) == mark:
                items.append((path, entry, None))
                del wins[path]
        state["beat"] = wins
        written = 0
        if items:
            written = service.store.put_many(KIND, items, service.signing, lst, gen=gen)[0]
        if skipped:
            log.info("mesh_notify_unpublishable", count=skipped)
        return written

    def _gate_now(service: Any, lst: Any) -> bool:
        own = service.store.own_iid
        try:
            doc = docs.snapshot()
            out = not (lst.alpha == own or status.is_enabled(doc, lst.alpha))
            notify_kind.set_gate(own, out, frozenset(_off_ids(doc)))
        except Exception:  # noqa: BLE001
            notify_kind.mark_failed(own)
            raise
        return out

    def _prepare(service: Any, lst: Any) -> None:
        if capabilities.mesh_on() and isinstance(lst, RosterV2):
            _gate_now(service, lst)

    def _work(service: Any, lst: Any, gen: Optional[int]) -> None:
        if not capabilities.mesh_on() or not isinstance(lst, RosterV2):
            return
        store, own = service.store, service.store.own_iid
        out = _gate_now(service, lst)
        doc = docs.snapshot()
        off = frozenset(_off_ids(doc))
        if out or store.generation != gen:
            return
        if state["gen"] != gen:
            state["gen"], state["beat"], state["memo"] = gen, {}, None
        rows = store.kind_rows(lst, KIND)
        memo = (store.kind_digest(lst, KIND), wire.digest(doc["global"]), tuple(sorted(off)))
        if memo == state["memo"] and not state["beat"]:
            return
        now = time.time()
        theirs = {path: entry for path, (entry, stamp) in rows.items() if stamp.iid != own and stamp.iid not in off}
        if theirs:
            outcome = merge.merge_into(docs, theirs, now)
            if outcome.deleted_dests:
                log.warning("mesh_notify_destination_deleted", count=len(outcome.deleted_dests))
            if outcome.changed:
                doc = docs.snapshot()
        written = _publish(service, lst, doc, rows, gen, now)
        if written:
            gossip.wake()
        state["memo"] = None if written else (store.kind_digest(lst, KIND), wire.digest(doc["global"]), tuple(sorted(off)))

    async def step(service: Any, lst: Any) -> None:
        try:
            await asyncio.to_thread(_work, service, lst, service.pass_gen)
        except (sqlite3.Error, OSError, ValueError, RuntimeError) as exc:
            log.warning("mesh_notify_step_failed", error=type(exc).__name__)

    gossip.add_prepare(_prepare)
    gossip.add_step(step)
    docs.add_listener(_on_write)
