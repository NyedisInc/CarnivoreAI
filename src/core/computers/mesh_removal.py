
from __future__ import annotations

import asyncio
import sqlite3
import threading
import time
from contextlib import closing
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set, Tuple

import structlog

from src.core.federation import peer_hosts, peer_listing, peer_listing_push, shadow_rows
from src.core.pack.machines import capabilities
from src.core.pack.machines.roster_v2 import RosterV2
from src.core.pack.relay import approval, retire, target_side
from src.core.pack.rollup_import import ddl as rollup_ddl
from src.core.resource_push import topics


class MeshRemovalError(ValueError):
    pass


log = structlog.get_logger(__name__)

LISTED, REMOVED, PURGED = "listed", "removed", "purged"
RETRY_SECONDS = 60.0
SETTLE_SECONDS = 120.0
MIN_PASS_GAP = 30.0
STOP_WAIT = 5.0
_TOPICS = (topics.COMPUTERS, topics.PACK_MACHINES, topics.PACK_RELAY_OFFER)
_GUARDED = (sqlite3.Error, OSError, ValueError, target_side.RelayRefused)
_DDL = """CREATE TABLE IF NOT EXISTS pack_mesh_removal (
    install_id TEXT PRIMARY KEY,
    state      TEXT NOT NULL CHECK (state IN ('listed','removed','purged')),
    generation INTEGER NOT NULL,
    removed_at REAL,
    passes     INTEGER NOT NULL DEFAULT 0,
    last_pass  REAL,
    label      TEXT
)"""
_REFUSED_LOGGED: Set[Tuple[str, int]] = set()
_TABLE_LOCK = threading.Lock()
_REFUSED_CAP = 256


@dataclass(frozen=True)
class Row:

    state: str
    generation: int
    removed_at: Optional[float]
    passes: int
    last_pass: Optional[float]
    label: Optional[str] = None


@dataclass(frozen=True)
class Plan:

    insert: Dict[str, int]
    relist: Dict[str, int]
    remove: Dict[str, int]
    refused: Tuple[str, ...]


async def _no_revoke(_iid: str) -> str:
    return "none"


@dataclass(frozen=True)
class Steps:

    retire_from: Callable[[str], Awaitable[Optional[Dict[str, str]]]]
    end_jobs: Callable[[str], Awaitable[int]]
    records: Callable[[], None]
    notify: Callable[[str], None]
    revoke_delegates: Callable[[str], Awaitable[str]] = _no_revoke


def plan(rows: Dict[str, Row], lst: RosterV2, self_iid: str) -> Plan:
    ids = [c.install_id for c in lst.computers]
    gen = lst.generation
    insert: Dict[str, int] = {}
    relist: Dict[str, int] = {}
    remove: Dict[str, int] = {}
    refused: List[str] = []
    for iid in ids:
        row = rows.get(iid)
        if row is None:
            insert[iid] = gen
        elif row.state == LISTED:
            insert[iid] = max(row.generation, gen)
        elif gen > row.generation:
            relist[iid] = gen
        else:
            refused.append(iid)
    if not rows:
        return Plan(insert, {}, {}, ())
    for iid, row in rows.items():
        if iid in ids or row.state != LISTED:
            continue
        if iid == self_iid:
            log.info("mesh_removal_self_absent", iid=iid[:8])
        elif gen > row.generation:
            remove[iid] = gen
    return Plan(insert, relist, remove, tuple(refused))


def _ensure(conn: sqlite3.Connection) -> None:
    conn.execute(_DDL)
    if "label" not in {r[1] for r in conn.execute("PRAGMA table_info(pack_mesh_removal)")}:
        conn.execute("ALTER TABLE pack_mesh_removal ADD COLUMN label TEXT")


def _exists(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'pack_mesh_removal'").fetchone() is not None


def read_rows(conn: sqlite3.Connection) -> Dict[str, Row]:
    if not _exists(conn):
        return {}
    has_label = "label" in {r[1] for r in conn.execute("PRAGMA table_info(pack_mesh_removal)")}
    col = "label" if has_label else "NULL"
    return {r[0]: Row(r[1], r[2], r[3], r[4], r[5], r[6])
            for r in conn.execute(f"SELECT install_id, state, generation, removed_at, passes, last_pass, {col} FROM pack_mesh_removal")}


def pending_ids(conn: sqlite3.Connection) -> List[str]:
    return [i for i, r in read_rows(conn).items() if r.state == REMOVED]


def clear(conn: sqlite3.Connection) -> None:
    conn.commit()
    with _TABLE_LOCK:
        if _exists(conn):
            conn.execute("DELETE FROM pack_mesh_removal")
            conn.commit()


def purge_local(conn: sqlite3.Connection, iid: str) -> bool:
    if peer_hosts.get(conn, iid) is not None:
        log.info("mesh_removal_star_kept", iid=iid[:8])
        return False
    left = peer_hosts.get(conn, iid, include_mesh=True)
    if left is not None:
        shadow_rows.remove_peer(conn, left.key)
        peer_hosts.delete_mesh(conn, iid)
    with conn:
        rollup_ddl.purge_rows(conn, iid, keep_floor=True)
    approval.forget(conn, iid)
    return True


def leave_mesh_rows(open_db: Callable[[], sqlite3.Connection]) -> List[str]:
    gone: List[str] = []
    with closing(open_db()) as conn:
        for row in peer_hosts.list_peers(conn, include_mesh=True):
            if row.back_kind != peer_hosts.MESH_BACK_KIND:
                continue
            shadow_rows.remove_peer(conn, row.key)
            peer_hosts.delete_mesh(conn, row.peer_install_id)
            if peer_hosts.get(conn, row.peer_install_id) is None:
                with conn:
                    rollup_ddl.purge_rows(conn, row.peer_install_id, keep_floor=True)
            gone.append(row.peer_install_id)
        clear(conn)
    for iid in gone:
        peer_listing.forget(iid)
    return gone


class Removal:

    def __init__(self, open_db: Callable[[], sqlite3.Connection], self_iid: str, steps: Steps, held: Callable[[], Optional[RosterV2]],
                 clock: Callable[[], float] = time.time) -> None:
        self._open_db, self._self, self._steps, self._held, self._clock = open_db, self_iid, steps, held, clock
        self._lock = asyncio.Lock()
        self._timer: Optional[asyncio.TimerHandle] = None
        self._task: Optional[asyncio.Task] = None
        self._want = False
        self._stopped = False
        self._relay_logged: Set[str] = set()
        self._swept: Set[str] = set()

    async def list_changed(self, lst: Any, in_grace: bool) -> None:
        if not capabilities.mesh_on() or in_grace or not isinstance(lst, RosterV2) or self._stopped:
            return
        self._want = True
        self._kick()

    def _kick(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.get_running_loop().create_task(self._run(), name="mesh-removal")

    async def _run(self) -> None:
        while self._want and not self._stopped:
            self._want = False
            try:
                await asyncio.to_thread(self._write_plan)
                await self.pass_once()
            except _GUARDED as exc:
                log.warning("mesh_removal_failed", error=type(exc).__name__)
                self._schedule()

    def _write_plan(self) -> None:
        with _TABLE_LOCK:
            cur = self._held()
            if not isinstance(cur, RosterV2):
                return
            with closing(self._open_db()) as conn:
                _ensure(conn)
                rows = read_rows(conn)
                made = plan(rows, cur, self._self)
                for iid in made.refused:
                    if (iid, cur.generation) not in _REFUSED_LOGGED:
                        if len(_REFUSED_LOGGED) >= _REFUSED_CAP:
                            _REFUSED_LOGGED.clear()
                        _REFUSED_LOGGED.add((iid, cur.generation))
                        log.warning("mesh_removal_relist_refused", iid=iid[:8], generation=cur.generation, held=rows[iid].generation)
                now = self._clock()
                labels = {c.install_id: c.label for c in cur.computers}
                with conn:
                    for iid, gen in {**made.insert, **made.relist}.items():
                        conn.execute("INSERT INTO pack_mesh_removal (install_id, state, generation, label) VALUES (?, 'listed', ?, ?) "
                                     "ON CONFLICT(install_id) DO UPDATE SET state = 'listed', generation = excluded.generation, "
                                     "removed_at = NULL, passes = 0, last_pass = NULL, label = COALESCE(excluded.label, pack_mesh_removal.label)", (iid, gen, labels.get(iid) or None))
                    for iid, gen in made.remove.items():
                        conn.execute("UPDATE pack_mesh_removal SET state = 'removed', generation = ?, removed_at = ?, passes = 0, last_pass = NULL "
                                     "WHERE install_id = ?", (gen, now, iid))
                if made.remove or made.relist:
                    log.info("mesh_removal_planned", removed=[i[:8] for i in made.remove], relisted=[i[:8] for i in made.relist])

    def _read(self) -> Dict[str, Row]:
        with closing(self._open_db()) as conn:
            return read_rows(conn)

    def _purge(self, iid: str) -> bool:
        with closing(self._open_db()) as conn:
            return purge_local(conn, iid)

    def _mark_purged(self, iid: str) -> None:
        with closing(self._open_db()) as conn, conn:
            conn.execute("UPDATE pack_mesh_removal SET state = 'purged', last_pass = ? WHERE install_id = ? AND state = 'removed'", (self._clock(), iid))

    def _settle(self, iid: str) -> None:
        now = self._clock()
        with closing(self._open_db()) as conn, conn:
            conn.execute("UPDATE pack_mesh_removal SET passes = passes + 1, last_pass = ?, "
                         "state = CASE WHEN passes + 1 >= 2 AND ? - COALESCE(removed_at, ?) >= ? THEN 'purged' ELSE state END "
                         "WHERE install_id = ? AND state = 'removed' AND (last_pass IS NULL OR ? - last_pass >= ?)", (now, now, now, SETTLE_SECONDS, iid, now, MIN_PASS_GAP))

    async def pass_once(self) -> bool:
        changed = False
        fresh = False
        pending = True
        async with self._lock:
            try:
                rows = await asyncio.to_thread(self._read)
                records_done = False
                for iid, row in rows.items():
                    if row.state != REMOVED:
                        continue
                    cur = await asyncio.to_thread(self._held)
                    if not isinstance(cur, RosterV2):
                        break
                    if iid == self._self or iid == cur.alpha or cur.entry(iid):
                        continue
                    try:
                        if not await asyncio.to_thread(self._purge, iid):
                            await asyncio.to_thread(self._mark_purged, iid)
                            changed = True
                            continue
                        if not records_done:
                            await asyncio.to_thread(self._steps.records)
                            records_done = True
                        if iid not in self._swept:
                            self._swept.add(iid)
                            fresh = True
                        peer_listing.forget(iid)
                        peer_listing_push.drop(iid)
                        await self._steps.revoke_delegates(iid)
                        outcomes = await self._steps.retire_from(iid)
                        await self._steps.end_jobs(iid)
                        changed = True
                        if outcomes is None:
                            if iid not in self._relay_logged:
                                self._relay_logged.add(iid)
                                log.warning("mesh_removal_relay_not_started", iid=iid[:8])
                        elif retire.DEFERRED not in outcomes.values():
                            await asyncio.to_thread(self._settle, iid)
                    except _GUARDED as exc:
                        log.warning("mesh_removal_step_failed", iid=iid[:8], error=type(exc).__name__, detail=str(exc)[:80])
                after = await asyncio.to_thread(self._read)
                pending = any(r.state == REMOVED for r in after.values())
                if fresh or any(after.get(i) is None or after[i].state != r.state for i, r in rows.items()):
                    for topic in _TOPICS:
                        self._steps.notify(topic)
            except _GUARDED as exc:
                log.warning("mesh_removal_read_failed", error=type(exc).__name__)
        if pending and not self._stopped:
            self._schedule()
        return changed

    def _pending(self) -> List[str]:
        with closing(self._open_db()) as conn:
            return pending_ids(conn)

    def _schedule(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
        self._timer = asyncio.get_running_loop().call_later(RETRY_SECONDS, self._retry)

    def _retry(self) -> None:
        self._timer = None
        if not self._stopped:
            self._want = True
            self._kick()

    def pending(self) -> List[str]:
        return self._pending()

    def forget(self) -> None:
        with closing(self._open_db()) as conn:
            clear(conn)

    async def stop(self) -> None:
        self._stopped = True
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        task = self._task
        if task is not None and not task.done():
            await asyncio.wait({task}, timeout=STOP_WAIT)
            if not task.done():
                task.cancel()
                await asyncio.wait({task})


REMOVAL: Optional[Removal] = None


def forget_pack() -> bool:
    removal = REMOVAL
    if removal is not None:
        removal.forget()
        return True
    from src.core.pack.machines import runtime as machines_runtime

    wired = machines_runtime.wiring()
    if wired is None:
        return False
    with closing(wired.open_db()) as conn:
        clear(conn)
    return True


def production_steps(notify: Callable[[str], None], held: Callable[[], Optional[RosterV2]]) -> Steps:
    async def retire_from(iid: str) -> Optional[Dict[str, str]]:
        from src.core.pack.relay import runtime as relay_runtime

        return await relay_runtime.retire_removed(iid)

    async def end_jobs(iid: str) -> int:
        from src.core.pack.jobs import boot
        from src.core.pack.jobs.types import JobError

        try:
            host = boot.host()
        except JobError:
            return 0
        try:
            return await host.end_for_removed(iid)
        except JobError as exc:
            raise MeshRemovalError(exc.code) from exc

    def records() -> None:
        from src.core.pack.meshdata import gossip

        active = gossip.ACTIVE
        if active is None:
            return
        gen = active.store.generation
        lst = held()
        if lst is not None:
            active.store.reconcile(lst, gen=gen)

    async def revoke_delegates(iid: str) -> str:
        from src.core.argent import pair_sync

        if pair_sync.PAIR is None:
            return "not_started"
        try:
            return await pair_sync.PAIR.revoke_removed(iid)
        except Exception as exc:  # noqa: BLE001
            log.warning("mesh_removal_argent_failed", error=type(exc).__name__)
            return "failed"

    return Steps(retire_from=retire_from, end_jobs=end_jobs, records=records, notify=notify, revoke_delegates=revoke_delegates)
