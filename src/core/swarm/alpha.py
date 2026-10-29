
from __future__ import annotations

import asyncio
import os
import shutil
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

import structlog

from src.core import db
from src.core.swarm import body, body_create, company_agent, learning, profiles, project_agent, slugs, store, switch, thread_port

logger = structlog.get_logger()

FOLDER = "Alpha"
SLUG = "alpha"
THREAD = "all"
EFFORT = "high"
JOB = ("chief of the Swarm. You route the owner's requests to the company agents with crosstalk_send to agent:<id> and "
       "suggest new companies with swarm_suggest (kind company). You never create anything yourself")
FOLDER_CARD_REF = "alpha:folder"


def alpha_path() -> str:
    return os.path.join(company_agent.projects_root(), FOLDER)


def live_alpha(conn: sqlite3.Connection) -> Optional[Dict[str, Any]]:
    row = conn.execute("SELECT id FROM swarm_agents WHERE rank = 'alpha' AND torn_down_at IS NULL").fetchone()
    return store.get_agent(conn, row["id"]) if row else None


def _register(conn: sqlite3.Connection, agent: Dict[str, Any]) -> Dict[str, Any]:
    if agent.get("project_id") is not None:
        return agent
    project = body_create.register_project(conn, agent["repo_dir"], FOLDER)
    store.update_agent(conn, agent["id"], project_id=project["id"])
    return store.get_agent(conn, agent["id"]) or agent


LEGACY_DEFAULT_NAME = "Alpha"
DEFAULT_NAME = "SysOp"
LEGACY_JOBS = frozenset({JOB.replace("swarm_", "pack_"), JOB.replace("swarm_", "pack_").replace("the Swarm", "the Pack")})


def _adopt_default_name(conn: sqlite3.Connection, agent: Dict[str, Any]) -> Dict[str, Any]:
    if agent["job"] in LEGACY_JOBS:
        agent = store.update_agent(conn, agent["id"], job=JOB)
    if agent["display_name"] != LEGACY_DEFAULT_NAME:
        return agent
    updated = store.update_agent(conn, agent["id"], display_name=DEFAULT_NAME)
    project_agent.relabel_session(conn, updated)
    project_agent.refresh_swarm_json(updated)
    return updated


def _create(conn: sqlite3.Connection, path: str) -> Dict[str, Any]:
    taken = {r[0] for r in conn.execute("SELECT slug FROM swarm_agents")}
    return store.create_agent(conn, slug=slugs.mint_slug(SLUG, taken.__contains__), rank="alpha", job=JOB, display_name=DEFAULT_NAME,
                              repo_dir=path, effort=EFFORT)


def _ensure(conn: sqlite3.Connection) -> Dict[str, Any]:
    existing = live_alpha(conn)
    if existing is not None:
        return {"agent": _register(conn, _adopt_default_name(conn, existing)), "created": False, "refused": ""}
    path = alpha_path()
    try:
        company_agent.make_repo_folder(path)
    except company_agent.TurnOnError as exc:
        return {"agent": None, "created": False, "refused": str(exc)}
    try:
        agent = _create(conn, path)
    except sqlite3.IntegrityError:
        shutil.rmtree(path, ignore_errors=True)
        return {"agent": live_alpha(conn), "created": False, "refused": ""}
    except sqlite3.Error:
        shutil.rmtree(path, ignore_errors=True)
        raise
    return {"agent": _register(conn, agent), "created": True, "refused": ""}


async def ensure_alpha() -> Optional[Dict[str, Any]]:
    """Make Alpha exist (docs/swarm.md 4.1): folder, repo, project row, one asleep agent. Safe to call at every boot.

    Description: runs when the Swarm is on (the huddle plugin registers its thread port, boot or a later turn-on). Never raises:
      a datastore or disk failure is logged and the next call tries again; a taken folder is logged and posts one info card.
    Output: Alpha's row dict, None when she does not exist yet. While the global Swarm switch is off it makes nothing and
      answers None; the turn-on (``switch.resume``) calls it again.
    """
    if not switch.is_on():
        logger.info("swarm_alpha_ensure_skipped_off")
        return None
    await asyncio.to_thread(profiles.sync_posture)
    try:
        result = await body.run_db(_ensure)
    except (sqlite3.Error, OSError, db.DatastoreError) as exc:
        logger.warning("swarm_alpha_ensure_failed", error_type=type(exc).__name__, error=str(exc)[:300])
        return None
    port = thread_port.get()
    if result["refused"]:
        logger.warning("swarm_alpha_folder_taken", reason=result["refused"])
        if port is not None:
            await port.settle_cards(FOLDER_CARD_REF, resolve=True)
            await port.post_card(THREAD, "info", "SysOp could not be created",
                                 f"Carnivore will not use a folder it did not make. {result['refused']}", FOLDER_CARD_REF)
        return None
    agent = result["agent"]
    if agent is not None and port is not None:
        await port.ensure_thread(agent["thread_key"], agent["display_name"])
    if result["created"] and agent is not None:
        logger.info("swarm_alpha_created", agent_id=agent["id"], repo_dir=agent["repo_dir"])
    return agent


def schedule_ensure() -> None:
    try:
        task = asyncio.get_running_loop().create_task(ensure_alpha())
    except RuntimeError:
        logger.warning("swarm_alpha_no_loop")
        return
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


_tasks: "set[asyncio.Task[Any]]" = set()


def desk_lines(conn: sqlite3.Connection, agent: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    if agent["rank"] != "alpha":
        return [], []
    out = ["companies (route the owner's orders to a company agent with crosstalk_send to agent:<id>):"]
    rows = conn.execute("SELECT id, name FROM companies ORDER BY name COLLATE NOCASE").fetchall()
    for company in rows:
        owner = conn.execute("SELECT id, display_name, state FROM swarm_agents WHERE rank = 'company' AND company_id = ? "
                             "AND torn_down_at IS NULL", (company["id"],)).fetchone()
        out.append(f"- {learning.one_line(company['name'])}: " + (f"{learning.one_line(owner['display_name'])} (agent {owner['id']}, {owner['state']})" if owner
                                               else "no agent yet"))
    if not rows:
        out.append("- no companies yet; suggest one with swarm_suggest (kind company) when the owner describes one")
    data: List[str] = []
    questions = conn.execute("SELECT id, text FROM swarm_questions WHERE state IN ('open','reopened') ORDER BY id").fetchall()
    if questions:
        out += ["", "open questions waiting for the owner in your thread (their text is under 'from agents'):"]
        for q in questions:
            out.append(f"- question {q['id']}")
            data += [f"question {q['id']}:", learning.QUOTE + " ".join(q["text"].split())[:200]]
    waiting = conn.execute("SELECT kind, name FROM swarm_suggestions WHERE state = 'pending' ORDER BY id").fetchall()
    if waiting:
        out += ["", "suggestions waiting for the owner (their names are under 'from agents'):"]
        for n, sug in enumerate(waiting, 1):
            out.append(f"- {sug['kind']} suggestion {n}")
            data += [f"{sug['kind']} suggestion {n}:", learning.QUOTE + " ".join(str(sug["name"]).split())[:200]]
    return out, data
