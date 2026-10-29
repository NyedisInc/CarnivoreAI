
from __future__ import annotations

import asyncio
import dataclasses
import sqlite3
from contextlib import closing
from typing import Any, Callable

import structlog

from src.core.db_reuse.kept_read import hot_read
from src.core.pack.placement import queue as spawn_queue
from src.core.pack.reserve import throttle as throttle_mod
from src.core.swarm import switch as swarm_switch

logger = structlog.get_logger()


async def drain(app_state: Any, open_db: Callable[[], sqlite3.Connection]) -> int:
    from src.core.swarm import body, spawn, store

    def load():
        with closing(open_db()) as conn:
            expired = spawn_queue.expire_old(conn)
            return expired, spawn_queue.list_queue(conn)

    expired, waiting = await asyncio.to_thread(load)
    for row in expired:
        parent_id = row["request"].get("parent_id")
        parent = await body.run_db(lambda c, pid=parent_id: store.get_agent(c, pid)) if parent_id else None
        if parent is not None:
            await body._card(parent, "spawn dropped", f"{row['request'].get('args', {}).get('job', 'a spawn')} waited an hour for a "
                             "computer with room and was dropped.", f"spawn_queue_expired:{row['id']}")
    started = 0
    for row in waiting:
        request = row["request"]

        def note(state: str, reason: str, queue_id: int = row["id"]) -> None:
            with closing(open_db()) as conn:
                (spawn_queue.mark_placed if state == "placed" else spawn_queue.note_attempt)(conn, queue_id, reason)

        try:
            parent = await body.run_db(lambda c: store.get_agent(c, request["parent_id"]))
            if parent is None or parent["torn_down_at"] is not None:
                await asyncio.to_thread(_cancel, open_db, row["id"], "its parent agent is gone")
                continue
            plan = dataclasses.replace(await spawn.prepare_for(parent, request["args"]), queue_id=row["id"])
            await spawn.run_for(app_state, plan)
            await asyncio.to_thread(note, "placed", "started from the queue")
            started += 1
        except spawn.SpawnQueued as exc:
            await asyncio.to_thread(note, "queued", str(exc))
        except spawn.SpawnRefused as exc:
            await asyncio.to_thread(_cancel, open_db, row["id"], f"refused: {exc}"[:500])
        except (sqlite3.Error, KeyError, TypeError, OSError) as exc:
            logger.warning("pack_queue_retry_failed", queue_id=row["id"], error=type(exc).__name__)
    return started


def _count_waiting(open_db: Callable[[], sqlite3.Connection]) -> int:
    return hot_read(open_db, ("spawn_queue_waiting",), spawn_queue.count_queued)


def _cancel(open_db: Callable[[], sqlite3.Connection], queue_id: int, reason: str) -> None:
    with closing(open_db()) as conn:
        spawn_queue.cancel(conn, queue_id)
        with conn:
            conn.execute("UPDATE pack_spawn_queue SET last_reason = ? WHERE id = ?", (reason, queue_id))


async def run(app_state: Any, wired: Any, throttle: throttle_mod.Throttle, *, tick: float = throttle_mod.TICK_SECONDS) -> None:
    await asyncio.to_thread(throttle.boot_clear)
    while True:
        await asyncio.sleep(tick)
        try:
            await asyncio.to_thread(throttle.tick)
            waiting = await asyncio.to_thread(_count_waiting, wired.open_db)
            if waiting and swarm_switch.is_on():
                await drain(app_state, wired.open_db)
        except Exception as exc:  # noqa: BLE001
            logger.warning("pack_maintenance_beat_failed", error=type(exc).__name__)


def start(app: Any, wired: Any) -> "asyncio.Task[None]":
    throttle = throttle_mod.Throttle(measure=lambda: throttle_mod.measure_local(wired),
                                     roots=lambda: throttle_mod.agent_pane_pids(wired.open_db))
    return asyncio.create_task(run(app.state, wired, throttle), name="pack-reserve-maintenance")
