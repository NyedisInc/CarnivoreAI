
from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

import structlog

from src.core.swarm import switch
from src.core.swarm.cards import lease

logger = structlog.get_logger()

_bodies: Dict[str, int] = {}
_epochs: Dict[str, Optional[int]] = {}
_unsettled: set = set()
_inflight: set = set()
_tasks: set = set()
_app_state: Optional[Any] = None


def register(app_state: Any, tmux_name: Optional[str], agent_id: int, tmux_epoch: Optional[int] = None) -> None:
    global _app_state
    _app_state = app_state if app_state is not None else _app_state
    if tmux_name:
        _bodies[str(tmux_name)] = agent_id
        _epochs[str(tmux_name)] = tmux_epoch
        _unsettled.add(str(tmux_name))


def agent_for_instance(tmux_name: Optional[str], tmux_epoch: Optional[int]) -> Optional[int]:
    if not tmux_name or tmux_epoch is None:
        return None
    name = str(tmux_name)
    registered = _epochs.get(name)
    return _bodies.get(name) if registered is not None and registered == tmux_epoch else None


def split_instance_key(key: Any) -> tuple:
    from src.core.unread_store import UnreadStore

    text = str(key)
    name = UnreadStore.name_of(text)
    return name, (int(text[len(name) + 1:]) if name != text else None)


def _agent_for_reading(name: str, epoch: Optional[int]) -> Optional[int]:
    agent_id = _bodies.get(name)
    registered = _epochs.get(name)
    if agent_id is None or (registered is not None and registered != epoch):
        return None
    return agent_id


def forget(tmux_name: Optional[str]) -> None:
    if tmux_name:
        _bodies.pop(str(tmux_name), None)
        _epochs.pop(str(tmux_name), None)
        _unsettled.discard(str(tmux_name))


def reset() -> None:
    global _app_state
    _bodies.clear()
    _epochs.clear()
    _unsettled.clear()
    _inflight.clear()
    _app_state = None


def _spawn(agent_id: int, work: Any) -> None:
    if agent_id in _inflight or _app_state is None:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    async def guarded() -> None:
        try:
            await work(_app_state, agent_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("swarm_watch_job_failed", agent_id=agent_id, error_type=type(exc).__name__, error=str(exc)[:300])
        finally:
            _inflight.discard(agent_id)

    _inflight.add(agent_id)
    task = loop.create_task(guarded())
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def _reconcile(app_state: Any, agent_id: int) -> None:
    from src.core.swarm import body, store

    agent = await body.run_db(lambda c: store.get_agent(c, agent_id))
    if agent is not None:
        await body.detect_death(app_state, agent)


async def _settle(app_state: Any, agent_id: int) -> None:
    from src.core.swarm import delivery

    if await delivery.settle_wake(app_state, agent_id):
        _unsettled.difference_update([name for name, owner in _bodies.items() if owner == agent_id])


async def _close_dialog_cards(app_state: Any, agent_id: int) -> None:
    from src.core.swarm import body, delivery, store

    agent = await body.run_db(lambda c: store.get_agent(c, agent_id))
    if agent is not None:
        await delivery.close_gone_dialog_cards(agent)


async def boot(app_state: Any) -> int:
    import sqlite3

    from src.core import db
    from src.core.swarm import body, reply_mirror, store

    if not switch.is_on():
        logger.info("swarm_watch_boot_skipped_off")
        return 0

    def read(conn: sqlite3.Connection) -> list:
        rows = conn.execute("SELECT a.id, s.tmux_name, s.tmux_created_epoch FROM swarm_agents a JOIN sessions s ON s.id = a.session_row_id "
                            "WHERE a.state IN ('awake', 'waking') AND a.torn_down_at IS NULL AND s.tmux_name IS NOT NULL").fetchall()
        return [(int(r[0]), str(r[1]), None if r[2] is None else int(r[2])) for r in rows]

    try:
        found = await body.run_db(read)
    except (sqlite3.Error, db.DatastoreUnreadableError, OSError) as exc:
        logger.warning("swarm_watch_boot_unreadable", error_type=type(exc).__name__)
        return 0
    await reply_mirror.boot()
    try:
        from src.config import settings as app_settings
        from src.core.swarm import body_create

        await asyncio.to_thread(body_create.rewrite_definitions, app_settings.get_state_dir())
    except (sqlite3.Error, db.DatastoreUnreadableError, OSError) as exc:
        logger.warning("swarm_definitions_rewrite_unreadable", error_type=type(exc).__name__)
    for agent_id, name, epoch in found:
        register(app_state, name, agent_id, epoch)
        try:
            agent = await body.run_db(lambda c: store.get_agent(c, agent_id))
            if agent is not None and not await body.detect_death(app_state, agent):
                await _settle(app_state, agent_id)
        except (sqlite3.Error, db.DatastoreUnreadableError, OSError, RuntimeError, body.BodyError) as exc:
            logger.warning("swarm_watch_boot_agent_failed", agent_id=agent_id, error_type=type(exc).__name__)
    return len(found)


def schedule_boot(app_state: Any) -> None:
    try:
        task = asyncio.get_running_loop().create_task(boot(app_state))
    except RuntimeError:
        return
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


def on_observation(target: Any, observation: Any) -> None:
    from src.core.attention.evidence import REASON_PANE_DEAD
    from src.core.swarm import reply_mirror

    name, epoch = split_instance_key(target.key)
    agent_id = _agent_for_reading(name, epoch)
    if agent_id is None:
        return
    lease.observe(agent_id, observation)
    if not switch.is_on():
        return
    if reply_mirror.on_reading(agent_id, observation):
        reply_mirror.schedule(agent_id)
    if observation.verdict.reason == REASON_PANE_DEAD:
        _spawn(agent_id, _reconcile)
    elif observation.evidence.dialog is None and name in _unsettled:
        _spawn(agent_id, _settle)
    elif observation.evidence.dialog is None:
        from src.core.swarm import delivery

        if delivery.has_dialog_cards(agent_id):
            _spawn(agent_id, _close_dialog_cards)
