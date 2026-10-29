
from __future__ import annotations

import asyncio
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TypeVar

import fastapi
import structlog

from src.core import db, session_change_notice
from src.core.db_reuse import datastore_pool
from src.core.swarm import admission, alerts, body_create, conflicts, delivery, profiles, push, settings as swarm_settings, promotion_store, store, switch, thread_port, wake_prompt, watch  # noqa: F401
from src.core.swarm.body_create import BodyIdentity
from src.core.pack.identity import home as project_home
from src.core.swarm.memory import SwarmFileError
from src.cplugs.sdk.swarm import SwarmError

logger = structlog.get_logger()
T = TypeVar("T")

START_ERRORS = (body_create.CreateRefused, SwarmFileError, fastapi.HTTPException, OSError, RuntimeError, ValueError,
                sqlite3.Error, db.DatastoreUnreadableError, asyncio.TimeoutError)
END_REASONS = ("sleep", "auto_sleep", "teardown", "failed")
WAKE_REFUSED_PREFIX = "wake_refused:"
WAKE_FAILED_PREFIX = "wake_failed:"


class BodyError(SwarmError):
    pass


class SwarmSwitchedOff(BodyError):
    pass


@dataclass(frozen=True)
class WakeResult:

    wake_id: int
    started: bool
    state: str


@dataclass(frozen=True)
class SleepResult:

    state: str
    commit: Optional[Dict[str, Any]] = None


async def run_db(work: Callable[[sqlite3.Connection], T]) -> T:
    from src.config import settings as app_settings

    def go() -> T:
        with closing(datastore_pool.lend(db.db_path_for(app_settings.get_state_dir()))) as conn:
            return work(conn)

    return await asyncio.to_thread(go)


async def live_info(app_state: Any, agent: Dict[str, Any]) -> Optional[Any]:
    row_id, manager = agent.get("session_row_id"), getattr(app_state, "session_manager", None)
    if row_id is None or manager is None:
        return None
    found = next((i for i in await manager.list_session_infos() if getattr(i, "session_row_id", None) == row_id), None)
    if found is None and agent.get("host_key", "local") != "local":
        from src.core.mcp import federated

        found = next((i for i in await federated.peer_infos() if getattr(i, "session_row_id", None) == row_id), None)
    return found


def _has_open_work(conn: sqlite3.Connection, agent: Dict[str, Any]) -> bool:
    asked = conn.execute("SELECT 1 FROM swarm_question_askers k JOIN swarm_questions q ON q.id = k.question_id "
                         "WHERE k.agent_id = ? AND q.state IN ('routing', 'reopened') LIMIT 1", (agent["id"],)).fetchone()
    return store.live_body_count(conn, agent["id"]) > 0 or bool(store.list_reports(conn, parent_id=agent["id"])) or asked is not None


def _resolve_mode(conn: sqlite3.Connection, agent: Dict[str, Any], mode: str) -> str:
    row = conn.execute("SELECT claude_session_uuid FROM sessions WHERE id = ?", (agent["session_row_id"],)).fetchone() \
        if agent["session_row_id"] is not None else None
    has_conversation = bool(row and row[0])
    if mode == "fresh" or not has_conversation or (mode != "resume" and promotion_store.reshaped_since_last_wake(conn, agent["id"])):
        return "fresh"
    return "resume" if mode == "resume" or store.is_member(agent) or _has_open_work(conn, agent) else "fresh"


def _compute_reserve() -> Optional[admission.Reserve]:
    from src.core.pack.reserve import local

    try:
        active = local.active_reserve()
    except (OSError, ValueError) as exc:
        logger.info("swarm_admission_reserve_unreadable", error=type(exc).__name__)
        return None
    return admission.Reserve(active["cpu_pct"], active["mem_pct"], active["level"]) if active else None


def caps_refusal(conn: sqlite3.Connection, agent: Dict[str, Any], *, machine: bool = True,
                 workload: Optional[Dict[str, Any]] = None) -> Optional[str]:
    cfg = swarm_settings.read_current()
    cap = cfg.max_children_per_parent
    if cap is not None and agent.get("parent_id") is not None and store.live_body_count(conn, agent["parent_id"]) >= cap:
        return f"its parent already has {cap} live bodies (the per-parent cap in the Swarm settings)"
    live = store.live_body_count(conn)
    if cfg.max_live_bodies is not None and live >= cfg.max_live_bodies:
        return f"{cfg.max_live_bodies} Swarm bodies are live (the total cap in the Swarm settings)"
    throttle = conflicts.current(agent.get("project_id")) if agent.get("rank") != "project" else None
    if throttle is not None:
        from src.core.swarm.cards import capacity

        refused = conflicts.refusal(throttle, capacity.project_workers(conn, agent["project_id"]))
        if refused:
            return refused
    if not machine:
        return None
    work = workload or {}
    return admission.refusal(admission.measure(), live, cfg.spawn_load_per_core, reserve=_compute_reserve(),
                             est_cpu_cores=work.get("est_cpu_cores", 0.5), est_ram_gb=work.get("est_ram_gb", 0.6))


async def _card(agent: Dict[str, Any], title: str, text: str, ref: str) -> None:
    port = thread_port.get()
    if port is None:
        return
    try:
        key = agent["thread_key"]
        if agent["parent_id"] is not None:
            parent = await run_db(lambda c: store.get_agent(c, agent["parent_id"]))
            key = parent["thread_key"] if parent else key
        await port.post_card(key, "info", title, text, ref)
        await asyncio.to_thread(push.notify_thread, key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("swarm_card_failed", ref=ref, error_type=type(exc).__name__)


async def _resolve_wake_cards(agent_id: int) -> None:
    port = thread_port.get()
    if port is None:
        return
    try:
        await port.settle_cards(f"{WAKE_REFUSED_PREFIX}{agent_id}", resolve=True)
        await port.settle_cards(f"{WAKE_FAILED_PREFIX}{agent_id}:", prefix=True, resolve=True)
        await port.settle_cards(f"{alerts.DEAD_PREFIX}{agent_id}:", prefix=True, resolve=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("swarm_wake_cards_not_resolved", agent_id=agent_id, error_type=type(exc).__name__)


async def _posture_refusal(agent: Dict[str, Any]) -> Optional[str]:
    from src.config import settings as app_settings

    def launched_as(conn: sqlite3.Connection) -> Optional[str]:
        row = conn.execute("SELECT agent_type FROM sessions WHERE id = ?", (agent["session_row_id"],)).fetchone() \
            if agent["session_row_id"] is not None else None
        return str(row[0]) if row and row[0] else None

    reused = await run_db(launched_as)
    refusal = await asyncio.to_thread(profiles.posture_refusal, agent, Path(app_settings.auth_config_file).expanduser(), reused)
    if agent["rank"] in profiles.UPPER_RANKS:
        app_settings.drop_auth_config_cache()
    return refusal


async def _unwind(agent_id: int, wake_id: int, end_reason: str = "failed") -> None:
    def work(conn: sqlite3.Connection) -> Optional[Dict[str, Any]]:
        store.close_wake(conn, wake_id, end_reason)
        store.cas_state(conn, agent_id, "waking", "asleep")
        return store.get_agent(conn, agent_id)

    async def finish() -> None:
        agent = await run_db(work)
        if agent is not None:
            await delivery.wake_ended(agent, wake_id)
        else:
            delivery.forget_wake(wake_id)

    await asyncio.shield(finish())


async def detect_death(app_state: Any, agent: Dict[str, Any]) -> bool:
    from src.core.swarm import body_death

    return await body_death.detect(app_state, agent)


async def _require_resumable(agent: Dict[str, Any], conversation_uuid: str) -> None:
    from src.core.swarm import rewind

    if agent["state"] != "asleep":
        raise BodyError(f"{agent['display_name']} is {agent['state']}; put it to sleep first to resume an earlier conversation")
    try:
        await run_db(lambda c: rewind.require_resumable(c, agent, conversation_uuid))
    except rewind.RewindRefused as exc:
        raise BodyError(str(exc)) from None


_agent_locks: Dict[int, "asyncio.Lock"] = {}


def agent_lock(agent_id: int) -> "asyncio.Lock":
    return _agent_locks.setdefault(agent_id, asyncio.Lock())



async def wake(app_state: Any, agent_id: int, reason: str, authority: str, *, mode: str = "auto",
               conversation_uuid: Optional[str] = None, orders: str = "",
               owner_message_ref: Optional[str] = None) -> WakeResult:
    switch.require_on()
    async with agent_lock(agent_id):
        agent = await run_db(lambda c: store.get_agent(c, agent_id))
        if agent is None or agent["torn_down_at"] is not None:
            raise BodyError("that agent is torn down")
        if agent["state"] in ("awake", "waking") and await detect_death(app_state, agent):
            agent = await run_db(lambda c: store.get_agent(c, agent_id)) or agent
        if conversation_uuid:
            await _require_resumable(agent, conversation_uuid)
        if agent["state"] != "asleep":
            return await _join(agent)
        moved = await run_db(lambda c: project_home.moved_away_for(c, agent["repo_dir"]))
        if moved:
            refusal = f"its project {moved['display_name']!r} moved to {moved['moved_to_label'] or 'another machine'}"
            await _card(agent, "cannot wake: project moved away", f"{agent['display_name']} stays asleep: {refusal}.",
                        f"{WAKE_REFUSED_PREFIX}{agent_id}")
            raise BodyError(f"{agent['display_name']} stays asleep: {refusal}")
        refusal = await run_db(lambda c: caps_refusal(c, agent, machine=False))
        if refusal:
            await _card(agent, "cannot wake yet", f"{agent['display_name']} stays asleep: {refusal}.", f"{WAKE_REFUSED_PREFIX}{agent_id}")
            raise BodyError(f"{agent['display_name']} stays asleep: {refusal}")
        refusal = await _posture_refusal(agent)
        if refusal:
            await _card(agent, "cannot wake: unsafe launch posture", f"{agent['display_name']} stays asleep: {refusal}.",
                        f"{WAKE_REFUSED_PREFIX}{agent_id}")
            raise BodyError(f"{agent['display_name']} stays asleep: {refusal}")

        def claim(conn: sqlite3.Connection) -> Optional[tuple]:
            resolved = "resume" if conversation_uuid else _resolve_mode(conn, agent, mode)
            try:
                wake_id = store.open_wake(conn, agent_id, reason=reason, mode=resolved, authority=authority)
            except sqlite3.IntegrityError:
                return None
            if wake_id is not None and conversation_uuid:
                store.point_at_conversation(conn, agent_id, wake_id, conversation_uuid)
            return None if wake_id is None else (wake_id, resolved)

        won = await run_db(claim)
        if won is None:
            return await _join(await run_db(lambda c: store.get_agent(c, agent_id)) or agent)
    wake_id, resolved = won
    done = False
    try:
        try:
            ident = await _start(app_state, agent, resolved)
            await finish_start(app_state, agent, wake_id, ident)
        except START_ERRORS as exc:
            logger.warning("swarm_wake_failed", agent_id=agent_id, error_type=type(exc).__name__, error=str(exc)[:300])
            await _card(agent, "wake failed", f"{agent['display_name']} could not start: {exc}", f"{WAKE_FAILED_PREFIX}{agent_id}:{wake_id}")
            raise BodyError(f"{agent['display_name']} could not start: {exc}") from exc
        done = True
    finally:
        if not done:
            await _unwind(agent_id, wake_id)
    _changed(app_state, "swarm_woken")
    fresh = await run_db(lambda c: store.get_agent(c, agent_id)) or agent
    await _resolve_wake_cards(agent_id)
    await _refresh_index(fresh)
    delivery.send_wake_prompt(app_state, fresh, wake_id, resolved, reason, orders, authority, owner_message_ref)
    return WakeResult(wake_id, True, "awake")


def _changed(app_state: Any, reason: str) -> None:
    session_change_notice.publish(app_state, session_change_notice.build_structural_notice(reason))


async def wait_awake(agent_id: int, *, poll_s: float = 0.5) -> None:
    while True:
        agent = await run_db(lambda c: store.get_agent(c, agent_id))
        if agent is None or agent["torn_down_at"] is not None or agent["state"] == "asleep":
            raise BodyError("the agent did not wake")
        if agent["state"] == "awake":
            return
        await asyncio.sleep(poll_s)


async def _join(agent: Dict[str, Any]) -> WakeResult:
    if agent["state"] == "sleeping":
        raise BodyError(f"{agent['display_name']} is going to sleep; try again in a moment")
    open_wake = await run_db(lambda c: store.get_open_wake(c, agent["id"]))
    if open_wake is None:
        raise BodyError(f"{agent['display_name']} has no running wake to join")
    return WakeResult(open_wake["id"], False, agent["state"])


async def _start(app_state: Any, agent: Dict[str, Any], mode: str) -> BodyIdentity:
    if agent.get("host_key", "local") != "local":
        from src.core.pack.span import remote_body

        return await remote_body.start(app_state, agent, mode)
    if agent["session_row_id"] is None:
        return await body_create.create_body(app_state, agent)
    from src.api.recreate_action import recreate_by_uuid
    from src.core.swarm.launch import SwarmLaunchUnreadable  # noqa: F401
    from src.config import settings as app_settings

    await asyncio.to_thread(body_create.write_settings, app_settings.get_state_dir(), agent)
    parent = await run_db(lambda c: store.get_agent(c, agent["parent_id"])) if agent.get("parent_id") is not None else None
    await asyncio.to_thread(body_create.write_definition, agent, parent["display_name"] if parent else None)

    def read(conn: sqlite3.Connection) -> Optional[sqlite3.Row]:
        return conn.execute("SELECT session_uuid, agent_type FROM sessions WHERE id = ?", (agent["session_row_id"],)).fetchone()

    row = await run_db(read)
    if row is None or not row["session_uuid"]:
        raise body_create.CreateRefused("the agent's session row is gone")
    answer = await recreate_by_uuid(str(row["session_uuid"]), row["agent_type"] or profiles.effective_profile(agent) or agent["harness"],
                                    get_manager=lambda: app_state.session_manager, fresh=mode == "fresh")
    if answer.status != "started":
        raise body_create.CreateRefused(answer.detail or "the recreate was refused")
    from src.core.sessions.name_locks import hold_adopt

    async with hold_adopt(app_state.session_manager, answer.tmux_session):
        info = await app_state.session_manager.get_session_info(answer.session_id)
    if info is None or info.session_row_id != agent["session_row_id"]:
        await _kill_minted(app_state, info)
        raise body_create.CreateRefused("the new body is not on the agent's own session row")
    return BodyIdentity(answer.session_id, int(info.session_row_id), str(row["session_uuid"]),
                        str(info.tmux_session), info.session.tmux_created_epoch)


async def _kill_minted(app_state: Any, info: Optional[Any]) -> None:
    if info is None or not info.tmux_session:
        return
    from src.core import session_sleep

    manager = app_state.session_manager
    try:
        await session_sleep.close_for_sleep(manager, name=str(info.tmux_session), socket=manager.tmux_socket_name())
    except RuntimeError as exc:
        logger.error("swarm_minted_body_close_failed", tmux_name=info.tmux_session, error=str(exc)[:200])


async def finish_start(app_state: Any, agent: Dict[str, Any], wake_id: int, ident: BodyIdentity) -> None:
    from src.core.crosstalk import store as crosstalk_store

    def record(conn: sqlite3.Connection) -> None:
        store.update_wake(conn, wake_id, tmux_name=ident.tmux_name, tmux_epoch=ident.tmux_epoch)

    await run_db(record)
    counts = await asyncio.to_thread(crosstalk_store.repin, ident.session_uuid, ident.session_id, ident.tmux_epoch)
    logger.info("swarm_wake_repinned", agent_id=agent["id"], **counts)
    if not await run_db(lambda c: store.cas_state(c, agent["id"], "waking", "awake")):
        raise body_create.CreateRefused("the agent left the waking state while its body started")
    push.notify_roster()
    push.notify_agent(agent["id"])
    if agent.get("host_key", "local") == "local":
        watch.register(app_state, ident.tmux_name, agent["id"], ident.tmux_epoch)


async def sleep(app_state: Any, agent_id: int, end_reason: str = "sleep") -> SleepResult:
    if end_reason not in END_REASONS:
        raise ValueError(f"end_reason must be one of {END_REASONS}")
    from src.api.session_sleep_routes import sleep_by_uuid

    agent = await run_db(lambda c: store.get_agent(c, agent_id))
    if agent is None:
        raise BodyError("no such agent")
    if agent["state"] in ("awake", "waking") and await detect_death(app_state, agent):
        return SleepResult("asleep")
    if agent["state"] == "asleep":
        return SleepResult("asleep")
    if agent["state"] != "awake":
        raise BodyError(f"{agent['display_name']} is {agent['state']}; it cannot sleep yet")
    if not await run_db(lambda c: store.cas_state(c, agent_id, "awake", "sleeping")):
        raise BodyError(f"{agent['display_name']} changed state; try again")
    try:
        uuid = await run_db(lambda c: (c.execute("SELECT session_uuid FROM sessions WHERE id = ?", (agent["session_row_id"],)).fetchone() or [None])[0])
        if agent.get("host_key", "local") != "local":
            from src.core.pack.span import remote_body

            await remote_body.sleep(app_state, agent)
            answer = None
        else:
            answer = await sleep_by_uuid(app_state, str(uuid), fresh_ok=True) if uuid else None
        if answer is not None and answer.status != "asleep":
            raise BodyError(answer.detail or "the body would not close")
    except (BodyError, fastapi.HTTPException, OSError, RuntimeError, sqlite3.Error) as exc:
        await run_db(lambda c: store.cas_state(c, agent_id, "sleeping", "awake"))
        raise (exc if isinstance(exc, BodyError) else BodyError(f"{agent['display_name']} would not sleep: {exc}")) from None

    ended: List[int] = []

    def close(conn: sqlite3.Connection) -> None:
        wake_row = store.get_open_wake(conn, agent_id)
        if wake_row is not None:
            store.close_wake(conn, wake_row["id"], end_reason)
            store.stamp_last_conversation(conn, agent_id)
            watch.forget(wake_row.get("tmux_name"))
            ended.append(wake_row["id"])

    await run_db(close)
    for wake_id in ended:
        await delivery.wake_ended(agent, wake_id)
    await _refresh_index(agent)
    commit = await _commit(app_state, agent)
    await run_db(lambda c: store.cas_state(c, agent_id, "sleeping", "asleep"))
    _changed(app_state, "swarm_slept")
    return SleepResult("asleep", commit)


async def _refresh_index(agent: Dict[str, Any]) -> None:
    from src.core.swarm import fact_index, memory

    write_block = switch.is_on()
    try:
        await run_db(lambda c: fact_index.refresh_agent(c, agent, write_block=write_block))
    except (OSError, sqlite3.Error, memory.SwarmFileError, fact_index.Fts5Missing) as exc:
        logger.warning("swarm_index_refresh_failed", agent_id=agent.get("id"), error_type=type(exc).__name__)


async def _commit(app_state: Any, agent: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    from src.core.swarm import sleep_commit

    return await sleep_commit.run(agent)
