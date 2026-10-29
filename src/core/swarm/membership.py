
from __future__ import annotations

import asyncio
import os
import sqlite3
from typing import Any, Dict, Optional

import structlog
from fastapi import HTTPException

from src.core import db
from src.core.swarm import body, body_create, memory, project_agent, project_promote, push, routing, slugs, store, switch, thread_port
from src.core.swarm.names import shown_name
from src.core.trail_entry import utc_now

logger = structlog.get_logger()

BUSY_STATES = ("working", "working_subagent")
MEMBER_ORDERS = (
    "You just joined the Swarm as a feature agent under your project agent; this conversation continues unchanged. The owner is "
    "always in charge: what the owner tells you directly overrides any leader agent. If an owner instruction conflicts with your "
    "leader's, ask your leader; it asks the owner when it cannot settle it. Send your leader a one-line swarm_report at the end of "
    "each piece of work the owner gives you, and finish every card you hold with swarm_card_finish. Your leader deals you queue "
    "cards only while you are idle with nothing open from the owner. Your leader is about to put your current work on cards you hold.")
MEMBER_JOINED = (
    "member_joined: {name} (agent {agent_id}, session {session_uuid}) joined the Swarm under you. Inventory everything it is working "
    "on right now (its transcript, its terminal, its open tasks) and create a card for each piece of that work, dealt to and held by "
    "{name} (swarm_card_create, then swarm_card_deal with agent_id {agent_id}). From then on its work runs through the card workflow; "
    "deal it queue cards only while it is idle with nothing open from the owner, and never override what the owner told it directly.")


class MembershipRefused(project_agent.TurnOnError):

    def __init__(self, code: str, sentence: str, **extra: Any) -> None:
        super().__init__(sentence)
        self.code, self.sentence, self.extra = code, sentence, extra

    def body(self) -> Dict[str, Any]:
        return {"code": self.code, "sentence": self.sentence, **self.extra}


def _read(conn: sqlite3.Connection, session_uuid: str) -> Dict[str, Any]:
    row = conn.execute("SELECT id, session_uuid, archived_at, host_key, project_id, working_dir, agent_family, agent_type, "
                       "COALESCE(title, claude_title, tmux_name) AS label FROM sessions WHERE session_uuid = ?", (session_uuid,)).fetchone()
    session = dict(row) if row is not None else None
    if session is None:
        return {"session": None, "project": None, "leader": None, "owner": None, "parked": None}
    project = project_agent._project(conn, session["project_id"]) if session["project_id"] is not None else None
    parked = conn.execute("SELECT * FROM swarm_agents WHERE parked_row_id = ? ORDER BY id DESC LIMIT 1", (session["id"],)).fetchone()
    return {"session": session, "project": project,
            "leader": store.get_project_agent(conn, session["project_id"]) if project is not None else None,
            "owner": store.get_agent_by_session_row(conn, session["id"]), "parked": dict(parked) if parked else None}


def _host(session: Dict[str, Any]) -> str:
    return session.get("host_key") or "local"


async def _remote_peer(session: Dict[str, Any], joining: bool) -> Any:
    from src.core.pack.span import remote_body

    try:
        peer = await asyncio.to_thread(remote_body.peer_for, _host(session))
    except body_create.CreateRefused:
        peer = None
    if peer is None or not remote_body.adopts(peer):
        verb = "join" if joining else "leave"
        raise MembershipRefused("needs_update", f"{_host(session)} has to be updated before a session there can {verb} the swarm")
    return peer


def harness_of(session: Dict[str, Any]) -> Optional[str]:
    parts = f"{session.get('agent_family') or ''} {session.get('agent_type') or ''}".lower().split()
    if any(p.startswith("shell") for p in parts):
        return None
    return "codex" if any(p.startswith("codex") for p in parts) else "claude"


def join_refusal(found: Dict[str, Any]) -> Optional[str]:
    session, owner = found["session"], found["owner"]
    name = session.get("label") or session["session_uuid"]
    if session["archived_at"]:
        return f"{name} was deleted, so it cannot join the swarm"
    if found["project"] is None:
        return f"{name} belongs to no project, so it has no project agent to join under"
    if harness_of(session) is None:
        return f"{name} is a shell, not an agent, so it cannot join the swarm"
    if owner is not None:
        return f"{name} is already {shown_name(owner)}, a {owner['rank']} agent"
    return None


async def _busy(app_state: Any, session_row_id: int) -> tuple:
    info = await body.live_info(app_state, {"session_row_id": session_row_id})
    return info is not None, info is not None and getattr(info, "activity_status", None) in BUSY_STATES


def _restart_needed(name: str, busy: bool, joining: bool) -> MembershipRefused:
    verb = "joining the swarm" if joining else "leaving the swarm"
    return MembershipRefused("restart_needed", f"{verb} restarts {name} and stops whatever it is doing right now; its conversation is kept.",
                             name=name, busy=busy)


def _bind(conn: sqlite3.Connection, found: Dict[str, Any], specialty: Optional[str]) -> Dict[str, Any]:
    session, leader, parked = found["session"], found["leader"], found["parked"]
    try:
        if parked is not None:
            now = utc_now()
            with conn:
                conn.execute("UPDATE swarm_agents SET session_row_id = ?, parked_row_id = NULL, parent_id = ?, state = 'asleep', "
                             "torn_down_at = NULL, updated_at = ?, specialty = COALESCE(?, specialty), host_key = ? WHERE id = ?",
                             (session["id"], leader["id"], now, specialty, _host(session), parked["id"]))
            push.notify_roster()
            push.notify_agent(parked["id"])
            return store.get_agent(conn, parked["id"]) or parked
        remote = _host(session) != "local"
        repo = os.path.realpath(found["project"]["root"] if remote or not session["working_dir"] else session["working_dir"])
        taken = {r[0] for r in conn.execute("SELECT slug FROM swarm_agents WHERE repo_dir = ? AND torn_down_at IS NULL", (repo,))}
        name = session.get("label") or "member"
        extra: Dict[str, Any] = {"specialty": specialty} if specialty else {}
        if remote:
            extra["host_key"] = _host(session)
        return store.create_agent(conn, slug=slugs.mint_slug(name, taken.__contains__), rank="feature", job=f"{store.MEMBER_JOB_PREFIX}{name}",
                                  display_name=name, repo_dir=repo, effort="medium", parent_id=leader["id"],
                                  project_id=found["project"]["id"], company_id=leader.get("company_id"),
                                  harness=harness_of(session), session_row_id=session["id"], **extra)
    except sqlite3.IntegrityError as exc:
        raise MembershipRefused("refused", "another agent already holds that session, or the old agent's name is taken now") from exc


def _write_files(conn: sqlite3.Connection, agent: Dict[str, Any], leader: Dict[str, Any], state_dir: Any) -> None:
    try:
        body_create.write_files(state_dir, agent, leader["display_name"], leader["slug"])
    except (body_create.CreateRefused, memory.SwarmFileError, OSError) as exc:
        conn.execute("UPDATE swarm_agents SET session_row_id = NULL WHERE id = ?", (agent["id"],))
        store.tear_down(conn, agent["id"])
        raise MembershipRefused("refused", f"the agent's files could not be written: {exc}") from exc


async def join(app_state: Any, session_uuid: str, *, specialty: Optional[str] = None, confirm_restart: bool = False,
               create_project_agent: bool = False) -> Dict[str, Any]:
    from src.config import settings as app_settings

    switch.require_on()
    found = await body.run_db(lambda c: _read(c, session_uuid))
    session = found["session"]
    if session is None:
        raise MembershipRefused("not_found", "no such session")
    owner, leader = found["owner"], found["leader"]
    if owner is not None and leader is not None and owner.get("parent_id") == leader["id"] and owner["rank"] == "feature":
        return owner
    reason = join_refusal(found)
    if reason:
        raise MembershipRefused("refused", reason)
    name = session.get("label") or session_uuid
    remote = _host(session) != "local"
    if remote:
        await _remote_peer(session, True)
        if not os.path.isdir(found["project"]["root"] or ""):
            raise MembershipRefused("refused", f"{name}'s project has no folder on this computer, so it cannot join the swarm from here")
    if leader is None and not create_project_agent:
        raise MembershipRefused("no_project_agent", f"there is no project agent for {found['project']['display_name']}, so to make "
                                f"{name} a swarm agent the project agent has to be created first.")
    running, busy = await _busy(app_state, session["id"])
    if not confirm_restart:
        raise _restart_needed(name, busy, True)
    if leader is None:
        leader = await project_agent.turn_on(app_state, found["project"]["id"])
        found = {**found, "leader": leader}
    try:
        was_running = running if remote else await project_promote.stop_if_running(app_state, session)
    except project_promote.PromoteRefused as exc:
        raise MembershipRefused("refused", str(exc)) from exc
    state_dir = app_settings.get_state_dir()

    def bind(conn: sqlite3.Connection) -> Dict[str, Any]:
        agent = _bind(conn, found, specialty)
        _write_files(conn, agent, leader, state_dir)
        return agent

    agent = await body.run_db(bind)
    port = thread_port.get()
    if port is not None:
        await port.ensure_thread(agent["thread_key"], agent["display_name"])
    logger.info("swarm_member_joined", agent_id=agent["id"], leader_id=leader["id"], restored=found["parked"] is not None,
                was_running=was_running, busy=busy)
    if was_running:
        try:
            await body.wake(app_state, agent["id"], "manual", "owner", mode="resume", orders=MEMBER_ORDERS)
        except body.BodyError as exc:
            woke = await _roll_back(app_state, agent["id"], session, remote)
            raise MembershipRefused("refused", f"{name} could not join the swarm: {exc}. The join was undone"
                                    + (f" and {name} is running again as a plain session." if woke else ".")) from exc
    await routing.tell(app_state, leader["id"], MEMBER_JOINED.format(name=agent["display_name"], agent_id=agent["id"],
                                                                      session_uuid=session_uuid),
                       source="wake_prompt", authority="data", ref=f"member_joined:{agent['id']}", reason="crosstalk")
    return await body.run_db(lambda c: store.get_agent(c, agent["id"])) or agent


async def _roll_back(app_state: Any, agent_id: int, session: Dict[str, Any], remote: bool) -> bool:
    from src.api.session_sleep_routes import wake_by_uuid

    await body.run_db(lambda c: _park(c, agent_id, session["id"]))
    logger.warning("swarm_member_join_rolled_back", agent_id=agent_id, remote=remote)
    if remote:
        return False
    try:
        answer = await wake_by_uuid(app_state, session["session_uuid"])
    except HTTPException as exc:
        logger.error("swarm_member_join_plain_wake_failed", agent_id=agent_id, error=str(exc.detail)[:200])
        return False
    return answer.status == "started"


async def _release_cards(app_state: Any, agent_id: int) -> int:
    from src.core.swarm.cards import ops
    from src.core.swarm.cards.port import CardsOff

    try:
        held = await ops.held_cards(agent_id)
    except CardsOff:
        return 0
    for card in held:
        await ops.release(app_state, int(card["id"]), {"reason": "its agent left the swarm"}, by="owner")
    return len(held)


def _park(conn: sqlite3.Connection, agent_id: int, row_id: int) -> None:
    now = utc_now()
    with conn:
        cur = conn.execute("UPDATE swarm_agents SET parked_row_id = ?, session_row_id = NULL, state = 'torn_down', torn_down_at = ?, "
                           "updated_at = ? WHERE id = ? AND state = 'asleep' AND torn_down_at IS NULL", (row_id, now, now, agent_id))
    if cur.rowcount != 1:
        raise MembershipRefused("refused", "the agent changed state while it was leaving; try again")
    push.notify_roster()
    push.notify_agent(agent_id)


async def leave(app_state: Any, session_uuid: str, *, confirm_restart: bool = False) -> Dict[str, Any]:
    from src.api.session_sleep_routes import wake_by_uuid

    found = await body.run_db(lambda c: _read(c, session_uuid))
    session, agent = found["session"], found["owner"]
    if session is None:
        raise MembershipRefused("not_found", "no such session")
    name = session.get("label") or session_uuid
    if agent is None or agent["rank"] != "feature":
        raise MembershipRefused("refused", f"{name} is not a swarm member" if agent is None else
                                f"{name} is {shown_name(agent)}, a {agent['rank']} agent, not a member")
    remote = _host(session) != "local"
    if remote:
        await _remote_peer(session, False)
    info = await body.live_info(app_state, {"session_row_id": session["id"]})
    running, busy = info is not None, info is not None and getattr(info, "activity_status", None) in BUSY_STATES
    if not confirm_restart:
        raise _restart_needed(name, busy, False)
    if agent["state"] != "asleep":
        await body.sleep(app_state, agent["id"])
    if remote:
        from src.core.pack.span import remote_body

        try:
            await remote_body.release(agent)
        except body_create.CreateRefused as exc:
            raise MembershipRefused("refused", str(exc)) from exc
    released = await _release_cards(app_state, agent["id"])
    await body.run_db(lambda c: _park(c, agent["id"], session["id"]))
    logger.info("swarm_member_left", agent_id=agent["id"], released_cards=released, was_running=running, remote=remote)
    if running and remote:
        from src.core.mcp import federated

        await federated.forward(info, "POST", "/sessions/{session_uuid}/wake")
    elif running:
        await wake_by_uuid(app_state, session_uuid)
    return {"session_uuid": session_uuid, "agent_id": agent["id"], "released_cards": released}



def _new_member(conn: sqlite3.Connection, working_dir: str, label: Optional[str], harness: str, state_dir: Any) -> Optional[Dict[str, Any]]:
    from src.core.project_store import get_project_by_root, normalize_root

    project = get_project_by_root(conn, normalize_root(working_dir))
    if project is None or project.get("archived_at") or not project.get("new_sessions_join_swarm"):
        return None
    leader = store.get_project_agent(conn, project["id"])
    if leader is None:
        return None
    found = {"session": {"id": None, "working_dir": working_dir, "label": label, "agent_family": harness}, "project": project,
             "leader": leader, "parked": None}
    agent = _bind(conn, found, None)
    _write_files(conn, agent, leader, state_dir)
    wake_id = store.open_wake(conn, agent["id"], reason="spawn", mode="fresh", authority="owner")
    if wake_id is None:
        store.tear_down(conn, agent["id"])
        return None
    return {"agent": store.get_agent(conn, agent["id"]) or agent, "wake_id": wake_id, "leader": leader}


async def new_session_member(working_dir: Optional[str], label: Optional[str], agent_type: Optional[str]) -> Optional[Dict[str, Any]]:
    from src.config import settings as app_settings
    from src.core.agent_families import get_family, is_valid_family
    from src.core.swarm.launch import swarm_argv

    if not working_dir or not switch.is_on() or (agent_type is not None and not is_valid_family(agent_type)):
        return None
    harness = get_family(agent_type).name
    if harness not in ("claude", "codex"):
        return None
    state_dir = app_settings.get_state_dir()
    try:
        plan = await body.run_db(lambda c: _new_member(c, working_dir, (label or "").strip() or None, harness, state_dir))
    except (MembershipRefused, db.DatastoreUnreadableError, sqlite3.Error, OSError, ValueError) as exc:
        logger.warning("swarm_new_session_member_skipped", working_dir=working_dir, error=str(exc)[:200])
        return None
    if plan is None:
        return None
    try:
        plan["argv"] = await asyncio.to_thread(swarm_argv, plan["agent"], state_dir)
    except (OSError, ValueError) as exc:
        logger.warning("swarm_new_session_member_skipped", working_dir=working_dir, error=str(exc)[:200])
        await drop_new_session_member(plan)
        return None
    return plan


async def drop_new_session_member(plan: Dict[str, Any]) -> None:
    agent_id = plan["agent"]["id"]

    def work(conn: sqlite3.Connection) -> None:
        store.close_wake(conn, plan["wake_id"], "failed")
        store.cas_state(conn, agent_id, "waking", "asleep")
        store.tear_down(conn, agent_id)

    try:
        await body.run_db(work)
    except (db.DatastoreUnreadableError, sqlite3.Error) as exc:
        logger.error("swarm_new_session_member_drop_failed", agent_id=agent_id, error=str(exc)[:200])


async def bind_new_session(app_state: Any, plan: Dict[str, Any], session_id: str) -> None:
    agent, leader = plan["agent"], plan["leader"]
    try:
        info = await app_state.session_manager.get_session_info(session_id)
        if info is None or info.session_row_id is None:
            raise body_create.CreateRefused("the new session is not in the listing")
        row_id = int(info.session_row_id)

        def bind(conn: sqlite3.Connection) -> str:
            store.set_session_row(conn, agent["id"], row_id)
            found = conn.execute("SELECT session_uuid FROM sessions WHERE id = ?", (row_id,)).fetchone()
            return str(found[0]) if found and found[0] else ""

        key = await body.run_db(bind)
        ident = body_create.BodyIdentity(session_id, row_id, key, str(info.tmux_session), info.session.tmux_created_epoch)
        await body.finish_start(app_state, agent, plan["wake_id"], ident)
    except (body_create.CreateRefused, body.BodyError, db.DatastoreUnreadableError, sqlite3.Error, RuntimeError) as exc:
        logger.error("swarm_new_session_member_bind_failed", agent_id=agent["id"], session_id=session_id, error=str(exc)[:200])
        await body.run_db(lambda c: c.execute("UPDATE swarm_agents SET session_row_id = NULL WHERE id = ?", (agent["id"],)))
        await drop_new_session_member(plan)
        return
    port = thread_port.get()
    if port is not None:
        await port.ensure_thread(agent["thread_key"], agent["display_name"])
    logger.info("swarm_member_launched", agent_id=agent["id"], leader_id=leader["id"], session_id=session_id)
    await routing.tell(app_state, leader["id"], MEMBER_JOINED.format(name=agent["display_name"], agent_id=agent["id"],
                                                                      session_uuid=key),
                       source="wake_prompt", authority="data", ref=f"member_joined:{agent['id']}", reason="crosstalk")
