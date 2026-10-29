
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, Optional

import structlog

from src.core.swarm import body, definition, effort as effort_floor, slugs, store, thread_port

logger = structlog.get_logger()

_SLUG_TRIES = 3


class CreateInvalid(ValueError):
    pass


def _title(slug: str) -> str:
    return slug.replace("-", " ").title()


def _owner_file_exists(repo: str, slug: str) -> bool:
    base = Path(repo)
    return not all(definition.is_swarm_definition(base, slug, base / sub / f"{slug}.{ext}")
                   for sub, ext in ((".claude/agents", "md"), (".codex/agents", "toml")))


def _insert(conn: sqlite3.Connection, req: Dict[str, Any], repo: str) -> Dict[str, Any]:
    parent_id, parent = req.get("parent_id"), None
    if parent_id is not None:
        parent = store.get_agent(conn, parent_id)
        if parent is None or parent["torn_down_at"] is not None:
            raise CreateInvalid("the parent agent does not exist or is torn down")
    taken = {r[0] for r in conn.execute("SELECT slug FROM swarm_agents WHERE repo_dir = ? AND torn_down_at IS NULL", (repo,))}
    slug = slugs.mint_slug(req["job"], lambda c: c in taken or _owner_file_exists(repo, c))
    extra = {k: req[k] for k in ("goal", "launch_profile", "harness", "persona", "effort_reason", "task_type", "specialty") if req.get(k) is not None}
    return store.create_agent(conn, slug=slug, rank=req["rank"], job=req["job"], parent_id=parent_id, repo_dir=repo,
                              display_name=req.get("display_name") or _title(slug), effort=req["effort"], **extra)


async def create_agent(req: Dict[str, Any]) -> Dict[str, Any]:
    try:
        level, why = effort_floor.resolve(req.get("effort"), req.get("effort_reason"))
    except effort_floor.EffortRefused as exc:
        raise CreateInvalid(str(exc)) from None
    req = {**req, "effort": level, "effort_reason": why or None}
    repo = os.path.expanduser(req["repo_dir"])
    if not os.path.isabs(repo):
        raise CreateInvalid("repo_dir must be an absolute folder")
    if os.path.exists(repo) and not os.path.isdir(repo):
        raise CreateInvalid("repo_dir is a file, not a folder")
    last: Optional[sqlite3.IntegrityError] = None
    for _ in range(_SLUG_TRIES):
        try:
            agent = await body.run_db(lambda c: _insert(c, req, repo))
            break
        except sqlite3.IntegrityError as exc:
            if "slug" not in str(exc) and "repo_dir" not in str(exc):
                raise
            last = exc
    else:
        raise last  # type: ignore[misc]
    port = thread_port.get()
    if port is not None:
        await port.ensure_thread(agent["thread_key"], agent["display_name"])
    logger.info("swarm_agent_created", agent_id=agent["id"], rank=agent["rank"], slug=agent["slug"])
    return agent
