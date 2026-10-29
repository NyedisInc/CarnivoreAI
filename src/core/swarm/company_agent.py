
from __future__ import annotations

import asyncio
import os
import re
import shutil
import sqlite3
from contextlib import closing
from typing import Any, Dict, Optional, Tuple

import structlog

from src.core import db
from src.core.companies import store as companies
from src.core.swarm import body, body_create, profiles, slugs, store, switch, thread_port
from src.core.swarm.project_agent import TurnOnError

logger = structlog.get_logger()

EFFORT = "high"
MAX_FOLDER_CHARS = 100
_UNSAFE = re.compile(r"[/\\\x00-\x1f\x7f]")

ORDERS = (
    "You were just turned on as this company's agent. Read your desk: it lists the company's projects with their project "
    "agents, the account pointers and your open suggestions. Tell the owner with swarm_say that you are ready, and what "
    "you see. Route the owner's orders to a project agent with crosstalk_send to agent:<its id>; for a project with no agent "
    "yet, suggest turning one on with swarm_suggest (kind project, that project's name). You never create anything yourself.")


class CompanyMissing(TurnOnError):
    pass


def safe_component(name: Any) -> str:
    if not isinstance(name, str) or name != name.strip() or not 0 < len(name) <= MAX_FOLDER_CHARS:
        raise ValueError(f"a folder name is 1 to {MAX_FOLDER_CHARS} characters with no space at either end")
    if _UNSAFE.search(name) or name.startswith(".") or ".." in name:
        raise ValueError("a folder name has no slash, no control character, no '..' and no leading dot")
    return name


def projects_root() -> str:
    from src.config import settings as app_settings

    return str(app_settings.get_working_dir())


def hq_path(company_name: str) -> str:
    return os.path.join(projects_root(), safe_component(f"{company_name} HQ"))


def make_repo_folder(path: str) -> None:
    if os.path.lexists(path):
        raise TurnOnError(f"{path} already exists; Carnivore never adopts or overwrites a folder, so move it or rename the company")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        os.mkdir(path)
    except OSError as exc:
        raise TurnOnError(f"cannot create {path}: {type(exc).__name__}") from exc
    try:
        body_create.ensure_repo(path)
    except body_create.CreateRefused as exc:
        shutil.rmtree(path, ignore_errors=True)
        raise TurnOnError(str(exc)) from exc


def _company_state(conn: sqlite3.Connection, company_id: int) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    try:
        company = companies.get_company(conn, company_id)
    except companies.CompanyNotFound:
        return None, None
    row = conn.execute("SELECT * FROM swarm_agents WHERE rank = 'company' AND company_id = ? AND torn_down_at IS NULL", (company_id,)).fetchone()
    return company, (dict(row) if row else None)


def _kept_hq(conn: sqlite3.Connection, company_id: int) -> Optional[str]:
    row = conn.execute("SELECT p.root FROM companies c JOIN projects p ON p.id = c.hq_project_id WHERE c.id = ? AND p.archived_at IS NULL",
                       (company_id,)).fetchone()
    return row[0] if row and os.path.isdir(row[0]) else None


def insert_company_agent(conn: sqlite3.Connection, company: Dict[str, Any], project_id: int, hq: str, launch_profile: Optional[str] = None,
                         session_row_id: Optional[int] = None) -> Dict[str, Any]:
    taken = {r[0] for r in conn.execute("SELECT slug FROM swarm_agents WHERE repo_dir = ? AND torn_down_at IS NULL", (os.path.realpath(hq),))}
    slug = slugs.mint_slug(f"{company['name']} company agent", taken.__contains__)
    extra: Dict[str, Any] = {"launch_profile": launch_profile} if launch_profile else {}
    if session_row_id is not None:
        extra["session_row_id"] = session_row_id
    return store.create_agent(conn, slug=slug, rank="company", job=f"company agent for {company['name']}",
                              display_name=f"{company['name']} agent", repo_dir=hq, effort=EFFORT, company_id=company["id"],
                              project_id=project_id, **extra)


def _register(conn: sqlite3.Connection, company: Dict[str, Any], hq: str, launch_profile: Optional[str]) -> Dict[str, Any]:
    project = body_create.register_project(conn, hq, os.path.basename(hq))
    companies.assign_project(conn, project["id"], company["id"])
    companies.set_hq_project(conn, company["id"], project["id"])
    return insert_company_agent(conn, company, project["id"], hq, launch_profile)


def discard_unregistered(hq: str) -> None:
    def registered(conn: sqlite3.Connection) -> bool:
        return conn.execute("SELECT 1 FROM projects WHERE root = ?", (os.path.realpath(hq),)).fetchone() is not None

    from src.config import settings as app_settings

    with closing(db.connect(db.db_path_for(app_settings.get_state_dir()), create=False)) as conn:
        if not registered(conn):
            shutil.rmtree(hq, ignore_errors=True)


async def turn_on(app_state: Any, company_id: int, launch_profile: Optional[str] = None, first_order: str = "",
                  owner_message_ref: Optional[str] = None) -> Dict[str, Any]:
    switch.require_on()
    if launch_profile:
        launch_profile = await asyncio.to_thread(profiles.require_known, launch_profile)
    company, existing = await body.run_db(lambda c: _company_state(c, company_id))
    if company is None:
        raise CompanyMissing("no such company")
    agent = existing
    if agent is not None and not (agent["state"] == "asleep" and agent["session_row_id"] is None):
        raise TurnOnError(f"{company['name']} already has an agent ({agent['display_name']})")
    if agent is not None and launch_profile:
        agent = await body.run_db(lambda c: store.update_agent(c, existing["id"], launch_profile=launch_profile))
    if agent is None:
        hq = await body.run_db(lambda c: _kept_hq(c, company_id))
        if hq is None:
            try:
                hq = await asyncio.to_thread(hq_path, company["name"])
            except ValueError as exc:
                raise TurnOnError(f"the company's HQ folder cannot be named from {company['name']!r}: {exc}") from exc
            await asyncio.to_thread(make_repo_folder, hq)
        try:
            agent = await body.run_db(lambda c: _register(c, company, hq, launch_profile))
        except (sqlite3.Error, body_create.CreateRefused, companies.CompanyNotFound) as exc:
            logger.warning("swarm_company_register_failed", company_id=company_id, error_type=type(exc).__name__)
            await asyncio.to_thread(discard_unregistered, hq)
            raise TurnOnError("the company's HQ folder could not be registered as a project; nothing was kept, try again") from exc
        port = thread_port.get()
        if port is not None:
            await port.ensure_thread(agent["thread_key"], agent["display_name"])
        logger.info("swarm_company_agent_created", agent_id=agent["id"], company_id=company_id)
    orders = ORDERS + (f"\n\n{first_order}" if first_order else "")
    await body.wake(app_state, agent["id"], "spawn", "owner" if owner_message_ref else "data", orders=orders,
                    owner_message_ref=owner_message_ref)
    return await body.run_db(lambda c: store.get_agent(c, agent["id"])) or agent
