
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import asyncio
import structlog

from src.core.swarm import alerts, delivery, store, switch, thread_port

logger = structlog.get_logger()

WAKING_GRACE_S = 300


async def _pane_dead(name: str, socket: str) -> bool:
    from src.core.tmux_backend import TmuxBackend

    probe = TmuxBackend.for_external(session_name=name, working_dir=Path.home(), on_output=None, socket_name=socket)
    rc, out, _err = await probe._run_tmux("display-message", "-t", f"={name}:", "-p", "#{pane_dead}", check=False)
    return rc == 0 and out.decode("utf-8", errors="replace").strip() == "1"


async def measure(row: Dict[str, Any]) -> Optional[str]:
    from src.api import recreate_routes as rr
    from src.core.session_recreate_presence import TMUX_GONE, TMUX_PRESENT

    if row.get("lifecycle") == "stopped":
        return "stopped"
    if not row.get("tmux_name"):
        return None
    name, socket = rr._safe(str(row["tmux_name"])), str(row.get("tmux_socket") or rr._socket_name())
    presence = await asyncio.to_thread(rr._measure_presence, name, socket)
    if presence.outcome == TMUX_GONE:
        return "gone"
    return "pane_dead" if presence.outcome == TMUX_PRESENT and await _pane_dead(name, socket) else None


async def _close_dialog_cards(agent: Dict[str, Any]) -> None:
    port = thread_port.get()
    if port is None:
        return
    for prefix in (delivery.HELD_PREFIX, delivery.IMPORT_PREFIX, delivery.CHOICE_PREFIX, delivery.STUCK_PREFIX):
        await port.close_open_cards(agent["thread_key"], prefix)


async def detect(app_state: Any, agent: Dict[str, Any]) -> bool:
    from src.core.swarm import body, watch
    from src.core import session_sleep

    if agent["state"] not in ("awake", "waking") or agent["session_row_id"] is None:
        return False

    def read(conn: sqlite3.Connection) -> tuple:
        row = conn.execute("SELECT lifecycle, tmux_name, tmux_socket FROM sessions WHERE id = ?", (agent["session_row_id"],)).fetchone()
        return (dict(row) if row else None), store.get_open_wake(conn, agent["id"])

    row, wake = await body.run_db(read)
    if row is None or wake is None:
        return False
    if agent["state"] == "waking":
        started = delivery._parse(wake.get("started_at"))
        if started is None or (datetime.now(timezone.utc) - started).total_seconds() < WAKING_GRACE_S:
            return False
    remote = agent.get("host_key", "local") != "local"
    how = ("stopped" if row.get("lifecycle") == "stopped" else None) if remote else await measure(row)
    if how is None:
        return False
    if not await body.run_db(lambda c: store.cas_state(c, agent["id"], agent["state"], "sleeping")):
        return False
    try:
        if how != "gone" and row.get("tmux_name") and not remote:
            manager = app_state.session_manager
            await session_sleep.close_for_sleep(manager, name=str(row["tmux_name"]), socket=str(row.get("tmux_socket") or manager.tmux_socket_name()))
    except RuntimeError:
        await body.run_db(lambda c: store.cas_state(c, agent["id"], "sleeping", agent["state"]))
        raise

    def bury(conn: sqlite3.Connection) -> bool:
        store.close_wake(conn, wake["id"], "died")
        store.stamp_last_conversation(conn, agent["id"])
        return body._has_open_work(conn, agent)

    open_work = await body.run_db(bury)
    watch.forget(wake.get("tmux_name") or row.get("tmux_name"))
    await delivery.wake_ended(agent, wake["id"])
    await _close_dialog_cards(agent)
    await body._refresh_index(agent)
    await body._commit(app_state, agent)
    await body.run_db(lambda c: store.cas_state(c, agent["id"], "sleeping", "asleep"))
    logger.warning("swarm_body_died", agent_id=agent["id"], how=how, open_work=open_work)
    if open_work and switch.is_on():  # nothing waiting
        await alerts.post_dead_card(agent, wake["id"])
    return True
