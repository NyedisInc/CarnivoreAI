
from __future__ import annotations

import asyncio
import os
import sqlite3
import subprocess
from src.core.dev_tools import git_guard
import uuid
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import structlog

from src.core import db
from src.core.swarm import brief, definition, launch, memory, profiles, say, store

logger = structlog.get_logger()

GIT_TIMEOUT_S = 15


class CreateRefused(RuntimeError):
    pass


@dataclass(frozen=True)
class BodyIdentity:

    session_id: str
    row_id: int
    session_uuid: str
    tmux_name: str
    tmux_epoch: Optional[int]


def _git(args: list, cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False, timeout=GIT_TIMEOUT_S)


def ensure_repo(repo_dir: str) -> None:
    try:
        os.makedirs(repo_dir, exist_ok=True)
        if not git_guard.git_available():
            logger.info("swarm_git_init_skipped_no_git", repo_dir=repo_dir)
            return
        top = _git(["rev-parse", "--show-toplevel"], repo_dir)
        if top.returncode == 0 and os.path.realpath(top.stdout.strip()) == os.path.realpath(repo_dir):
            return
        init = _git(["init", "-q"], repo_dir)
    except (OSError, subprocess.SubprocessError) as exc:
        raise CreateRefused(f"cannot prepare the folder: {type(exc).__name__}") from exc
    if init.returncode != 0:
        raise CreateRefused("git init failed in the agent's folder")
    logger.info("swarm_git_init", repo_dir=repo_dir)


def _goal_text(agent: Dict[str, Any]) -> str:
    return f"\n\nGoal:\n{agent['goal']}" if agent.get("goal") else ""


def brief_for(agent: Dict[str, Any], parent_name: Optional[str] = None, memory_dir: str = "") -> str:
    rules = definition.rank_rules(agent["rank"])
    plain = f"You are {agent['display_name']}. Your job: {agent['job']}" + (f"\n\n{rules}" if rules else "")
    if not parent_name or agent["rank"] not in ("feature", "task") or not agent.get("goal"):
        return plain + _goal_text(agent)
    if agent["effort"] in brief.EFFORTS_NEEDING_REASON and not (agent.get("effort_reason") or "").strip():
        return plain + _goal_text(agent)
    spec = brief.BriefSpec(
        slug=agent["slug"], display_name=agent["display_name"], persona=agent.get("persona") or "a focused specialist",
        name_reason="its parent picked it for this job", job=agent["job"], rank=agent["rank"], order=agent["job"],
        goal=agent["goal"], effort=agent["effort"], effort_reason=agent.get("effort_reason") or "",
        parent_name=parent_name, memory_dir=memory_dir)
    return brief.render_brief(spec).body + f"\n{rules}\n" + _goal_text(agent)


def write_settings(state_dir: Path, agent: Dict[str, Any]) -> None:
    if agent["rank"] in definition.UPPER_RANKS:
        mem = memory.memory_dir(Path(agent["repo_dir"]), agent["slug"], agent["memory_scope"])
        memory.atomic_write(launch.settings_path(state_dir, agent["id"]), definition.render_settings(mem.resolve(), agent["rank"]))


def write_definition(agent: Dict[str, Any], parent_name: Optional[str] = None) -> None:
    repo = Path(agent["repo_dir"])
    if not repo.is_dir():
        raise CreateRefused("the agent's folder is gone")
    slug = agent["slug"]
    mem = memory.memory_dir(repo, slug, agent["memory_scope"])
    defn = definition.AgentDefinition(slug=slug, description=agent["job"][:300], rank=agent["rank"], effort=agent["effort"],
                                      memory=agent["memory_scope"], brief=brief_for(agent, parent_name, str(mem)) + f"\n\n{say.THREAD_LINE}\n",
                                      display_name=agent["display_name"])
    text, twin = definition.render_definition(defn), definition.render_codex_twin(defn)
    for path, content in ((repo / ".claude" / "agents" / f"{slug}.md", text), (repo / ".codex" / "agents" / f"{slug}.toml", twin)):
        if definition.is_swarm_definition(repo, slug, path):
            memory.atomic_write(path, content)
        else:
            logger.warning("swarm_definition_not_ours_skipped", agent_id=agent.get("id"), file=path.name)


def rewrite_definitions(state_dir: Path) -> int:
    with closing(db.connect(db.db_path_for(state_dir), create=False)) as conn:
        agents = store.list_agents(conn)
    names = {a["id"]: a["display_name"] for a in agents}
    done = 0
    for agent in agents:
        if agent["session_row_id"] is None:
            continue
        try:
            write_definition(agent, names.get(agent["parent_id"]) if agent.get("parent_id") is not None else None)
            done += 1
        except (CreateRefused, memory.SwarmFileError, OSError) as exc:
            logger.warning("swarm_definition_rewrite_failed", agent_id=agent["id"], error_type=type(exc).__name__, error=str(exc)[:200])
    logger.info("swarm_definitions_rewritten", count=done)
    return done


def write_files(state_dir: Path, agent: Dict[str, Any], parent_name: Optional[str] = None, parent_slug: Optional[str] = None) -> None:
    repo = Path(agent["repo_dir"])
    slug, rank = agent["slug"], agent["rank"]
    mem = memory.memory_dir(repo, slug, agent["memory_scope"])
    write_definition(agent, parent_name)
    memory.ensure_layout(mem)
    meta = definition.SwarmMeta(slug=slug, display_name=agent["display_name"], rank=rank, parent_slug=parent_slug,
                               persona=agent.get("persona") or "", naming_family=agent.get("naming_family") or "",
                               character_seed=str(agent["character_seed"]))
    memory.atomic_write(mem / "swarm.json", definition.render_swarm_json(meta))
    if agent["memory_scope"] == memory.SCOPE_LOCAL:
        definition.add_exclude_lines(repo, slug)
    launch.desk_dir(state_dir, agent["id"]).mkdir(parents=True, exist_ok=True)
    write_settings(state_dir, agent)


def register_project(conn: sqlite3.Connection, repo_dir: str, display_name: str) -> Dict[str, Any]:
    from src.core.project_store import normalize_root
    from src.core.project_writes import ProjectNameConflict, ProjectRootConflict, ProjectRootRefused, create_project

    root = normalize_root(repo_dir)
    for attempt in range(1, 20):
        found = conn.execute("SELECT id, display_name FROM projects WHERE root = ?", (root,)).fetchone()
        if found is not None:
            return {"id": int(found[0]), "display_name": found[1]}
        name = display_name if attempt == 1 else f"{display_name}-{attempt}"
        try:
            return create_project(conn, name=name, path=repo_dir)
        except ProjectNameConflict:
            continue
        except ProjectRootConflict:
            continue
        except ProjectRootRefused as exc:
            raise CreateRefused(str(exc)) from None
    raise CreateRefused("could not register the agent's folder as a project")


def _prepare(state_dir: Path, agent: Dict[str, Any]) -> Dict[str, Any]:
    ensure_repo(agent["repo_dir"])
    with closing(db.connect(db.db_path_for(state_dir), create=False)) as conn:
        parent = store.get_agent(conn, agent["parent_id"]) if agent.get("parent_id") is not None else None
    write_files(state_dir, agent, parent["display_name"] if parent else None, parent["slug"] if parent else None)
    with closing(db.connect(db.db_path_for(state_dir), create=False)) as conn:
        project = register_project(conn, agent["repo_dir"], os.path.basename(agent["repo_dir"].rstrip("/")) or agent["slug"])
        if agent.get("project_id") != project["id"]:
            store.update_agent(conn, agent["id"], project_id=project["id"])
        return project


async def create_body(app_state: Any, agent: Dict[str, Any]) -> BodyIdentity:
    from src.config import settings as app_settings

    state_dir = app_settings.get_state_dir()
    project = await asyncio.to_thread(_prepare, state_dir, agent)
    manager = app_state.session_manager
    created = await manager.create_session(
        session_id=f"ses_{uuid.uuid4().hex[:8]}", working_dir=agent["repo_dir"], auto_start_claude=True,
        project_name=project["display_name"], agent_type=profiles.effective_profile(agent) or agent["harness"],
        model=agent["model"], agent_extra_args=launch.swarm_argv(agent, state_dir),
        label=agent["display_name"])
    info = await manager.get_session_info(created.id)
    if info is None or info.session_row_id is None:
        raise CreateRefused("the new body is not in the session listing")
    row_id = int(info.session_row_id)

    def bind() -> str:
        with closing(db.connect(db.db_path_for(state_dir), create=False)) as conn:
            store.set_session_row(conn, agent["id"], row_id)
            found = conn.execute("SELECT session_uuid FROM sessions WHERE id = ?", (row_id,)).fetchone()
        return str(found[0]) if found and found[0] else ""

    key = await asyncio.to_thread(bind)
    if not key:
        raise CreateRefused("the new body's session row has no durable key")
    return BodyIdentity(created.id, row_id, key, str(info.tmux_session), info.session.tmux_created_epoch)
