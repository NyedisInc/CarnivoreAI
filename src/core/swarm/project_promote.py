
from __future__ import annotations

import asyncio
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import structlog
from fastapi import HTTPException

from src.core import db
from src.core.swarm import body, body_create, memory, project_agent, seats, store, thread_port
from src.core.swarm.names import shown_name

logger = structlog.get_logger()

PROMOTE_ORDERS = ("You were this project's lead session and are now its Swarm project agent. This conversation continues unchanged; "
                  "from here on you also own the project's Task Manager list and may spawn feature and task agents. Your standing rules "
                  "are in your agent definition.")
NOT_CLAUDE = ("codex", "shell")


class PromoteRefused(project_agent.TurnOnError):
    pass


@dataclass(frozen=True)
class AgentKind:

    rank: str
    orders: str
    existing: Callable[[sqlite3.Connection, int], Optional[Dict[str, Any]]]
    insert: Callable[[sqlite3.Connection, sqlite3.Row, int], Dict[str, Any]]
    seat_refusal: Callable[[sqlite3.Connection, sqlite3.Row], Optional[str]]


PROJECT = AgentKind("project", PROMOTE_ORDERS, store.get_project_agent,
                    lambda conn, project, row_id: project_agent.insert_project_agent(conn, project, session_row_id=row_id),
                    lambda conn, project: seats.refusal(conn, project["id"], project["display_name"]))


def refusal(session: Dict[str, Any], project: sqlite3.Row, owner: Optional[Dict[str, Any]], rank: str = "project") -> Optional[str]:
    name = session.get("label") or session["session_uuid"]
    if session["archived_at"]:
        return f"{name} was deleted, so it cannot become the project agent"
    if (session.get("host_key") or "local") != "local":
        return f"{name} runs on another machine; a project agent runs here"
    if session["project_id"] != project["id"]:
        return f"{name} belongs to another project"
    family = f"{session.get('agent_family') or ''} {session.get('agent_type') or ''}".lower().split()
    if any(part.startswith(NOT_CLAUDE) for part in family):
        return f"{name} is not a Claude session; a project agent is one"
    if os.path.realpath(session.get("working_dir") or "") != os.path.realpath(project["root"]):
        return f"{name} works in {session.get('working_dir')}, not in the project's folder {project['root']}"
    if owner is not None and owner["rank"] != rank:
        return f"{name} is already {shown_name(owner)}, a {owner['rank']} agent"
    return None


def _read(conn: sqlite3.Connection, session_uuid: str, project_id: int, kind: AgentKind) -> Dict[str, Any]:
    project = project_agent._project(conn, project_id)
    row = conn.execute("SELECT id, session_uuid, archived_at, host_key, project_id, working_dir, agent_family, agent_type, "
                       "COALESCE(title, claude_title, tmux_name) AS label FROM sessions WHERE session_uuid = ?", (session_uuid,)).fetchone()
    session = dict(row) if row is not None else None
    return {"project": project, "session": session,
            "owner": store.get_agent_by_session_row(conn, session["id"]) if session else None,
            "existing": kind.existing(conn, project_id)}


async def stop_if_running(app_state: Any, session: Dict[str, Any]) -> bool:
    from src.api.session_sleep_routes import sleep_by_uuid

    if await body.live_info(app_state, {"session_row_id": session["id"]}) is None:
        return False
    try:
        answer = await sleep_by_uuid(app_state, session["session_uuid"])
    except HTTPException as exc:
        raise PromoteRefused(f"{session['label']} would not stop: {exc.detail}") from exc
    if answer.status != "asleep":
        raise PromoteRefused(answer.detail or f"{session['label']} would not stop")
    return True


async def _free_old_body(app_state: Any, existing: Dict[str, Any]) -> None:
    if existing["state"] in ("waking", "sleeping"):
        raise PromoteRefused(f"{shown_name(existing)} is {existing['state']}; try again in a moment")
    if existing["state"] == "awake":
        try:
            await body.sleep(app_state, existing["id"])
        except body.BodyError as exc:
            raise PromoteRefused(str(exc)) from exc


def _write(conn: sqlite3.Connection, found: Dict[str, Any], state_dir: Path, kind: AgentKind) -> Dict[str, Any]:
    session, existing = found["session"], found["existing"]
    try:
        if existing is not None:
            store.rebind_session_row(conn, existing["id"], session["id"])
            return store.get_agent(conn, existing["id"]) or existing
        agent = kind.insert(conn, found["project"], session["id"])
    except sqlite3.IntegrityError as exc:
        raise PromoteRefused("another agent already holds that session or that project") from exc
    except store.AgentNotFound as exc:
        raise PromoteRefused(f"{shown_name(existing)} changed state while it was being re-pointed; try again") from exc
    boss = store.get_agent(conn, agent["parent_id"]) if agent.get("parent_id") is not None else None
    try:
        body_create.write_files(state_dir, agent, boss["display_name"] if boss else None, boss["slug"] if boss else None)
    except (body_create.CreateRefused, memory.SwarmFileError, OSError) as exc:
        store.tear_down(conn, agent["id"])
        raise PromoteRefused(f"the agent's files could not be written: {exc}") from exc
    return agent


async def promote_session(app_state: Any, session_uuid: str, project_id: int, kind: AgentKind = PROJECT) -> Dict[str, Any]:
    from src.config import settings as app_settings

    found = await body.run_db(lambda c: _read(c, session_uuid, project_id, kind))
    if found["project"] is None:
        raise project_agent.ProjectMissing("no such project")
    session, existing, owner = found["session"], found["existing"], found["owner"]
    if session is None:
        raise PromoteRefused("no such session")
    if owner is not None and existing is not None and owner["id"] == existing["id"]:
        return owner
    reason = refusal(session, found["project"], owner, kind.rank)
    if reason is None and existing is None:
        reason = await body.run_db(lambda c: kind.seat_refusal(c, found["project"]))
    if reason:
        raise PromoteRefused(reason)
    if existing is None:
        await asyncio.to_thread(project_agent._ensure_project_repo, found["project"]["root"])
    else:
        await _free_old_body(app_state, existing)
    was_running = await stop_if_running(app_state, session)
    state_dir = app_settings.get_state_dir()
    agent = await body.run_db(lambda c: _write(c, found, state_dir, kind))
    port = thread_port.get()
    if port is not None and existing is None:
        await port.ensure_thread(agent["thread_key"], agent["display_name"])
    logger.info("swarm_session_promoted", agent_id=agent["id"], project_id=project_id, rank=kind.rank, repointed=existing is not None, was_running=was_running)
    if was_running:
        await body.wake(app_state, agent["id"], "manual", "data", mode="resume", orders=kind.orders)
    return await body.run_db(lambda c: store.get_agent(c, agent["id"])) or agent
