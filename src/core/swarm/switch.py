
from __future__ import annotations

import asyncio
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Set, TypeVar

import structlog

from src.config import settings
from src.config.swarm_switch import SWARM_SWITCH_KEY
from src.core import config_writer, db, resource_push
from src.core.resource_push import topics

logger = structlog.get_logger()

CODE = "swarm_off"
OFF_MESSAGE = "the swarm is off on this computer; the owner turns it back on in the sysop menu"

_T = TypeVar("_T")


class BodyHeld(ValueError):
    pass


toggle_lock = asyncio.Lock()
_warned_unreadable = False


def is_on() -> bool:
    global _warned_unreadable
    try:
        return bool(settings.load_auth_config().swarm_switch.enabled)
    except (FileNotFoundError, ValueError, OSError) as exc:
        if not _warned_unreadable:
            _warned_unreadable = True
            logger.warning("swarm_switch_unreadable_reads_on", error_type=type(exc).__name__)
        return True


def require_on() -> None:
    if is_on():
        return
    from src.core.swarm.body import SwarmSwitchedOff

    raise SwarmSwitchedOff(OFF_MESSAGE)


def refusal() -> Dict[str, str]:
    return {"code": CODE, "message": OFF_MESSAGE}


def status() -> Dict[str, Any]:
    return {"enabled": is_on()}


def guards_body(session_uuid: str) -> bool:
    if is_on():
        return False
    from src.core.swarm import store

    agent = _read(lambda conn: store.get_agent_by_session_uuid(conn, session_uuid), None)
    return agent is not None and agent.get("torn_down_at") is None


def held_row_ids() -> Set[int]:
    if is_on():
        return set()
    sql = "SELECT session_row_id FROM swarm_agents WHERE torn_down_at IS NULL AND session_row_id IS NOT NULL"
    return _read(lambda conn: {int(r[0]) for r in conn.execute(sql).fetchall()}, set())


def _read(query: Callable[[sqlite3.Connection], _T], unreadable: _T) -> _T:
    try:
        with closing(db.connect(db.db_path_for(settings.get_state_dir()), create=False)) as conn:
            return query(conn)
    except (sqlite3.Error, db.DatastoreUnreadableError, OSError) as exc:
        logger.warning("swarm_switch_body_check_unreadable", error_type=type(exc).__name__)
        return unreadable


def hold_launch(is_swarm_body: bool, what: Optional[str] = None) -> None:
    if is_swarm_body and not is_on():
        logger.info("swarm_body_launch_held_off", target=what)
        raise BodyHeld(OFF_MESSAGE)


async def set_enabled(app_state: Any, enabled: bool) -> Dict[str, Any]:
    async with toggle_lock:
        was_on = is_on()

        def mutate(doc: dict) -> dict:
            block = doc.get(SWARM_SWITCH_KEY)
            block = dict(block) if isinstance(block, dict) else {}
            block["enabled"] = bool(enabled)
            return {**doc, SWARM_SWITCH_KEY: block}

        await asyncio.to_thread(config_writer.commit, Path(settings.auth_config_file).expanduser(), mutate)
        settings.drop_auth_config_cache()
    resource_push.notify(topics.SWARM_SWITCH)
    from src.core.swarm import push

    push.notify_roster()
    logger.info("swarm_switch_changed", enabled=bool(enabled), was_on=was_on)
    if enabled and not was_on:
        resume(app_state)
    return status()


def resume(app_state: Any) -> None:
    from src.core.swarm import alpha, thread_port, watch

    if thread_port.get() is None:
        return
    alpha.schedule_ensure()
    if app_state is not None:
        watch.schedule_boot(app_state)
