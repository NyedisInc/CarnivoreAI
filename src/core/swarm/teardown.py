
from __future__ import annotations

import asyncio
import shutil
import sqlite3
import subprocess
from contextlib import closing
from pathlib import Path
from typing import Any, Dict

import structlog

from src.core import db, session_store
from src.core.swarm import body, commit_guard, definition, launch, memory, store, thread_port

logger = structlog.get_logger()


def _remove(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def erase_files(state_dir: Path, agent: Dict[str, Any]) -> None:
    if agent["rank"] != "task" or agent["memory_scope"] != memory.SCOPE_LOCAL:
        raise ValueError("only a task agent with local memory is erased")
    repo, slug = Path(agent["repo_dir"]), memory.require_slug(agent["slug"])
    for path in (repo / ".claude" / "agents" / f"{slug}.md", repo / ".codex" / "agents" / f"{slug}.toml"):
        if definition.is_swarm_definition(repo, slug, path):
            _remove(path)
    for path in (memory.memory_dir(repo, slug, memory.SCOPE_LOCAL), launch.desk_dir(state_dir, agent["id"]),
                 launch.settings_path(state_dir, agent["id"]), commit_guard.hooks_dir(state_dir, agent["id"])):
        _remove(path)
    try:
        definition.remove_exclude_lines(repo, slug)
    except (memory.SwarmFileError, subprocess.SubprocessError) as exc:
        logger.warning("swarm_teardown_exclude_skipped", agent_id=agent["id"], error_type=type(exc).__name__)


def archive_and_tombstone(agent: Dict[str, Any]) -> None:
    from src.config import settings as app_settings

    with closing(db.connect(db.db_path_for(app_settings.get_state_dir()), create=False)) as conn:
        found = conn.execute("SELECT session_uuid FROM sessions WHERE id = ?", (agent["session_row_id"],)).fetchone() \
            if agent["session_row_id"] is not None else None
        if found and found[0]:
            try:
                session_store.archive_session(conn, str(found[0]))
            except session_store.SessionNotFoundError:
                logger.warning("swarm_teardown_session_missing", agent_id=agent["id"])
        store.tear_down(conn, agent["id"])


async def run(app_state: Any, agent: Dict[str, Any]) -> None:
    """Tear a task agent down: sleep its body, erase its files, archive its row and thread, tombstone it.

    Inputs: app_state (carries the session manager); agent (``swarm_agents`` row dict, rank ``task``).
    Raises: body.BodyError (the body would not close or is still starting: nothing was erased), ValueError (not a task
      agent), OSError (a file could not be deleted: the agent stays, a retry finishes the job).
    Example: await teardown.run(app.state, agent)
    """
    from src.config import settings as app_settings

    if agent["rank"] != "task":
        raise ValueError("only a task agent is torn down")
    current = await body.run_db(lambda c: store.get_agent(c, agent["id"]))
    if current is None or current["torn_down_at"] is not None:
        return
    if current["state"] == "awake":
        await body.sleep(app_state, agent["id"], "teardown")
    elif current["state"] != "asleep":
        raise body.BodyError(f"{current['display_name']} is {current['state']}; it cannot be torn down yet")
    await asyncio.to_thread(erase_files, app_settings.get_state_dir(), current)
    await asyncio.to_thread(archive_and_tombstone, current)
    port = thread_port.get()
    if port is not None:
        await port.archive_thread(current["thread_key"])
    logger.info("swarm_agent_torn_down", agent_id=current["id"], slug=current["slug"])
