
from __future__ import annotations

import asyncio
import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, Optional

import structlog

from src.core.db import transaction
from src.core.swarm import body, body_create, definition, delivery, memory, profiles, push, seats, slugs, store, switch, thread_port, wake_prompt
from src.core.swarm import settings as swarm_settings
from src.core.session_label import InvalidLabel, set_label
from src.cplugs.sdk.swarm import SwarmError

logger = structlog.get_logger()

GITINIT_PREFIX = "gitinit:"
NAMING_PREFIX = "naming:"
EFFORT = "high"
MAX_FAMILY_CHARS, MAX_PERSONA_CHARS, MAX_REASON_CHARS = 120, 60, 600

NAMING_ORDERS = (
    "You were just turned on as the project agent. Before you spawn anything, propose a naming family: a theme your "
    "agents' persona names will come from (for example Norse gods), and a persona name for yourself from that theme. "
    "Call swarm_propose_naming with the family, your persona and a short reason. The owner reviews it as a card. Until "
    "they approve, spawn with plain names only.")
PLAIN_ORDERS = ("You were just turned on as the project agent. Name every agent you spawn by the agent-name rules in your "
                "standing rules: a task agent by its general task, a feature agent by its specialty.")


class TurnOnError(SwarmError):
    pass


class ProjectMissing(TurnOnError):
    pass


def _project(conn: sqlite3.Connection, project_id: int) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT id, root, display_name, host_key FROM projects WHERE id = ? AND archived_at IS NULL", (project_id,)).fetchone()


SYSTEM_TREES = ("/System", "/Library", "/Applications", "/usr", "/bin", "/sbin", "/etc", "/private/etc", "/dev",
                "/cores", "/private/var/db", "/private/var/root")
SYSTEM_FOLDERS = ("/", "/Users", "/Volumes", "/private", "/var", "/private/var", "/tmp", "/private/tmp", "/opt")


USER_CONTENT_CONTAINERS = (("Library", "Mobile Documents"), ("Library", "CloudStorage"))
USER_CONTENT_MIN_DEPTH = 2


def _is_user_content_folder(real: str, home: str) -> bool:
    for parts in USER_CONTENT_CONTAINERS:
        container = os.path.join(home, *parts)
        if real.startswith(container + os.sep):
            below = [c for c in real[len(container) + 1:].split(os.sep) if c]
            if len(below) >= USER_CONTENT_MIN_DEPTH:
                return True
    return False


def _git_init_refusal(root: str) -> Optional[str]:
    if not os.path.isdir(root):
        return f"the project's folder {root} is missing"
    real, home = os.path.realpath(root), os.path.realpath(os.path.expanduser("~"))
    if real == home:
        return f"{root} is your home folder; git init will not run there"
    trees = SYSTEM_TREES + (os.path.join(home, "Library"),)
    if _is_user_content_folder(real, home):
        trees = SYSTEM_TREES
    if real in SYSTEM_FOLDERS or any(real == t or real.startswith(t + os.sep) for t in trees):
        return f"{root} is a system folder; git init will not run there"
    top = body_create._git(["rev-parse", "--show-toplevel"], root)
    if top.returncode == 0 and top.stdout.strip():
        return f"{root} sits inside the git repo at {top.stdout.strip()}; git init will not run there"
    return None


def _ensure_project_repo(root: str) -> None:
    top = body_create._git(["rev-parse", "--show-toplevel"], root) if os.path.isdir(root) else None
    if top is not None and top.returncode == 0 and os.path.realpath(top.stdout.strip()) == os.path.realpath(root):
        return
    refusal = _git_init_refusal(root)
    if refusal:
        raise TurnOnError(refusal)
    try:
        body_create.ensure_repo(root)
    except body_create.CreateRefused as exc:
        raise TurnOnError(str(exc)) from exc


def insert_project_agent(conn: sqlite3.Connection, project: sqlite3.Row, launch_profile: Optional[str] = None,
                         session_row_id: Optional[int] = None) -> Dict[str, Any]:
    taken = {r[0] for r in conn.execute("SELECT slug FROM swarm_agents WHERE repo_dir = ? AND torn_down_at IS NULL",
                                        (os.path.realpath(project["root"]),))}
    slug = slugs.mint_slug(f"{project['display_name']} project agent", taken.__contains__)
    extra: Dict[str, Any] = {"launch_profile": launch_profile} if launch_profile else {}
    if session_row_id is not None:
        extra["session_row_id"] = session_row_id
    filed = conn.execute("SELECT company_id FROM projects WHERE id = ?", (project["id"],)).fetchone()[0]
    boss = conn.execute("SELECT id FROM swarm_agents WHERE rank = 'company' AND company_id = ? AND torn_down_at IS NULL",
                        (filed,)).fetchone() if filed is not None else None
    return store.create_agent(conn, slug=slug, rank="project", job=f"project agent for {project['display_name']}",
                              display_name=f"{project['display_name']} agent", repo_dir=project["root"], effort=EFFORT,
                              project_id=project["id"], naming_state="none", parent_id=boss[0] if boss else None,
                              company_id=filed, **extra)


async def turn_on(app_state: Any, project_id: int, launch_profile: Optional[str] = None, first_order: str = "",
                  owner_message_ref: Optional[str] = None) -> Dict[str, Any]:
    switch.require_on()
    if launch_profile:
        launch_profile = await asyncio.to_thread(profiles.require_known, launch_profile)
    found = await body.run_db(lambda c: (_project(c, project_id), store.get_project_agent(c, project_id)))
    project, existing = found
    if project is None:
        raise ProjectMissing("no such project")
    if (project["host_key"] or "local") != "local":
        raise TurnOnError(f"{project['display_name']} lives on another computer; turn its agent on from that computer")
    if existing is not None and not (existing["state"] == "asleep" and existing["naming_state"] == "none"):
        raise TurnOnError(f"{existing['display_name']} is already on for this project")
    agent = existing
    if agent is not None and launch_profile:
        agent = await body.run_db(lambda c: store.update_agent(c, existing["id"], launch_profile=launch_profile))
    if agent is None:
        taken = await body.run_db(lambda c: seats.refusal(c, project_id, project["display_name"]))
        if taken:
            raise TurnOnError(taken)
        await asyncio.to_thread(_ensure_project_repo, project["root"])
        agent = await body.run_db(lambda c: insert_project_agent(c, project, launch_profile))
        port = thread_port.get()
        if port is not None:
            await port.ensure_thread(agent["thread_key"], agent["display_name"])
        logger.info("swarm_project_agent_created", agent_id=agent["id"], project_id=project_id)
        if port is not None:
            await port.close_open_cards(str(project_id), f"{GITINIT_PREFIX}{project_id}")
    orders = (NAMING_ORDERS if await asyncio.to_thread(swarm_settings.naming_family_on) else PLAIN_ORDERS) + (f"\n\n{first_order}" if first_order else "")
    await body.wake(app_state, agent["id"], "spawn", "owner" if owner_message_ref else "data", orders=orders,
                    owner_message_ref=owner_message_ref)
    return await body.run_db(lambda c: store.get_agent(c, agent["id"])) or agent


async def propose_naming(agent: Dict[str, Any], family: str, persona: str, reason: str) -> int:
    if not await asyncio.to_thread(swarm_settings.naming_family_on):
        raise TurnOnError("the naming family is off in the Swarm settings: no proposal is posted; name your agents by the agent-name rules")
    if agent["rank"] != "project":
        raise TurnOnError("only a project agent proposes a naming family")
    if agent["naming_state"] == "approved":
        raise TurnOnError("the owner already approved your naming family")
    for label, text, cap in (("family", family, MAX_FAMILY_CHARS), ("persona", persona, MAX_PERSONA_CHARS), ("reason", reason, MAX_REASON_CHARS)):
        if not isinstance(text, str) or not text.strip() or len(text.strip()) > cap:
            raise TurnOnError(f"{label} is required, at most {cap} characters")
    family, persona, reason = family.strip(), persona.strip(), reason.strip()
    try:
        memory.refuse_secrets(f"{family}\n{persona}\n{reason}", "naming proposal")
    except memory.SwarmFileError as exc:
        raise TurnOnError(str(exc)) from None
    port = thread_port.get()
    if port is None:
        raise TurnOnError("the huddle plugin is off, so there is nowhere to post the proposal")
    item = await port.post_card(agent["thread_key"], "waiting", "naming family", f"family: {family}\npersona: {persona}\n{reason}\n"
                                "approve to use it for this project's agents, or answer to ask for another.",
                                f"{NAMING_PREFIX}{agent['id']}")
    await body.run_db(lambda c: store.update_agent(c, agent["id"], naming_family=family, persona=persona, naming_state="proposed"))
    await asyncio.to_thread(push.notify_thread, agent["thread_key"])
    return int(item)


def _approve(conn: sqlite3.Connection, agent_id: int) -> Optional[Dict[str, Any]]:
    agent = store.get_agent(conn, agent_id)
    if agent is None or agent["torn_down_at"] is not None or agent["naming_state"] != "proposed" or not agent.get("persona"):
        return None
    project = _project(conn, agent["project_id"]) if agent["project_id"] is not None else None
    name = f"{agent['persona']} ({project['display_name']})" if project else agent["persona"]
    agent = store.update_agent(conn, agent_id, naming_state="approved", display_name=name)
    relabel_session(conn, agent)
    return agent


def relabel_session(conn: sqlite3.Connection, agent: Dict[str, Any]) -> None:
    row = conn.execute("SELECT session_uuid FROM sessions WHERE id = ?", (agent["session_row_id"],)).fetchone() \
        if agent["session_row_id"] is not None else None
    if row is None or not row[0]:
        return
    try:
        with transaction(conn):
            set_label(conn, session_uuid=str(row[0]), label=agent["display_name"])
    except InvalidLabel as exc:
        logger.warning("swarm_naming_label_refused", agent_id=agent["id"], error=str(exc)[:200])


def refresh_swarm_json(agent: Dict[str, Any]) -> None:
    mem = memory.memory_dir(Path(agent["repo_dir"]), agent["slug"], agent["memory_scope"])
    if not mem.is_dir():
        return
    memory.adopt_legacy_json(mem)
    try:
        parent_slug = definition.parse_swarm_json((mem / "swarm.json").read_text()).parent_slug
    except (OSError, memory.SwarmFileError):
        parent_slug = None
    meta = definition.SwarmMeta(slug=agent["slug"], display_name=agent["display_name"], rank=agent["rank"], parent_slug=parent_slug,
                               persona=agent.get("persona") or "", naming_family=agent.get("naming_family") or "",
                               character_seed=str(agent["character_seed"]))
    memory.atomic_write(mem / "swarm.json", definition.render_swarm_json(meta))


async def decide(app_state: Any, swarm_ref: str, approve: bool) -> None:
    if not approve:
        return
    prefix, _, ident = swarm_ref.partition(":")
    if f"{prefix}:" == GITINIT_PREFIX:
        await turn_on(app_state, int(ident))
        return
    if not await asyncio.to_thread(swarm_settings.naming_family_on):
        raise TurnOnError("the naming family is off in the Swarm settings; turn it on to approve a family")
    agent = await body.run_db(lambda c: _approve(c, int(ident)))
    if agent is None:
        raise TurnOnError("there is no naming proposal to approve")
    try:
        await asyncio.to_thread(refresh_swarm_json, agent)
    except (memory.SwarmFileError, OSError) as exc:
        logger.warning("swarm_naming_json_not_written", agent_id=agent["id"], error_type=type(exc).__name__)
    line = wake_prompt.naming_line(agent, True)
    if line and agent["state"] in ("awake", "waking"):
        await delivery.deliver_text(app_state, agent["id"], line, source="wake_prompt", authority="data", source_ref=f"{NAMING_PREFIX}{agent['id']}")
