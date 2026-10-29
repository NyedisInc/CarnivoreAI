
from __future__ import annotations

import asyncio
import dataclasses
import sqlite3
from typing import Any, Dict, Optional

import structlog

from src.core import db
from src.core.swarm import body, commit, push, store, switch, thread_port, visibility

logger = structlog.get_logger()

VISIBILITY_PREFIX = "visibility:"

_repo_locks: Dict[str, "asyncio.Lock"] = {}


async def run(agent: Dict[str, Any], message: str = "") -> Optional[Dict[str, Any]]:
    """Commit the agent's memory paths, one commit at a time per repo; never raises for a repo or datastore condition.

    Inputs: agent (``swarm_agents`` row dict); message (a commit message other than the default). Output: the ``CommitResult`` as a dict, None when the commit could not run.
    A public or unknown origin without approval posts the approve card (carrying the fingerprint the check saw).
    While the global Swarm switch is off nothing is committed and None is answered: the changed files stay in the
      folder and the next sleep after a turn-on commits them (docs/swarm.md 4.10).
    Example: await run(agent) -> {"status": "committed", "sha": "..."}
    """
    if not switch.is_on():
        logger.info("swarm_commit_skipped_off", agent_id=agent.get("id"))
        return None
    repo = str(agent.get("repo_dir") or "")
    lock = _repo_locks.setdefault(repo, asyncio.Lock())
    try:
        async with lock:
            result = await body.run_db(lambda c: commit.commit_memory(c, agent, message=message))
    except (OSError, ValueError, sqlite3.Error, db.DatastoreUnreadableError) as exc:
        logger.warning("swarm_sleep_commit_failed", agent_id=agent.get("id"), error=type(exc).__name__)
        return None
    if result.status == commit.PENDING_APPROVAL and result.fingerprint:
        await _post_card(agent, result)
    return dataclasses.asdict(result)


async def _post_card(agent: Dict[str, Any], result: "commit.CommitResult") -> None:
    port = thread_port.get()
    if port is None:
        return
    text = (f"{agent['display_name']} has memory to commit in {agent['repo_dir']}, and the repo's origin is "
            f"{result.detail}. approve to let memory commits land in it, or answer to keep them local.")
    await port.post_card(agent["thread_key"], "question", "commit memory to this repo?", text,
                         f"{VISIBILITY_PREFIX}{agent['id']}:{result.fingerprint}")
    await asyncio.to_thread(push.notify_thread, agent["thread_key"])


async def decide(app_state: Any, swarm_ref: str, approve: bool) -> None:
    if not approve:
        return
    _, agent_id, fingerprint = swarm_ref.split(":", 2)
    agent = await body.run_db(lambda c: store.get_agent(c, int(agent_id)))
    if agent is None or not agent.get("repo_dir"):
        raise body.BodyError("that card belongs to an agent that no longer exists")
    ok = await body.run_db(lambda c: visibility.approve(c, str(agent["repo_dir"]), fingerprint))
    if not ok:
        raise body.BodyError("the repo's remotes changed since this card; the next sleep asks again")
