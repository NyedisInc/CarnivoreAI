
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, List, Optional, Sequence

import structlog

from src.core.db import DatastoreUnreadableError, connect, db_path_for, table_exists
from src.core.swarm import commit_guard
from src.core.swarm.definition import UPPER_RANKS, UPPER_TOOLS
from src.core.swarm.store import get_agent_by_session_row

logger = structlog.get_logger(__name__)



class SwarmLaunchUnreadable(RuntimeError):
    """The datastore exists but could not be read, so whether this row is a Swarm body is unknown (fail closed)."""


_UPPER_CLI_TOOLS = ",".join(t for t in UPPER_TOOLS if not t.startswith("mcp__"))


def swarm_dir(state_dir: Path) -> Path:
    """``<state_dir>/swarm``, the Swarm's own folder under the durable state directory."""
    return Path(state_dir) / "swarm"


def settings_path(state_dir: Path, agent_id: int) -> Path:
    return swarm_dir(state_dir) / "settings" / f"{int(agent_id)}.json"


def desk_dir(state_dir: Path, agent_id: int) -> Path:
    return swarm_dir(state_dir) / "desk" / str(int(agent_id))


def profile_names_chrome(agent: dict) -> bool:
    from src.config import settings as app_settings
    from src.core.launch_profiles.store import LaunchProfileError, LaunchProfileStore
    from src.core.swarm.profiles import effective_profile

    name = effective_profile(agent)
    if not name:
        return False
    try:
        profiles = LaunchProfileStore(Path(app_settings.auth_config_file).expanduser()).list()
    except (LaunchProfileError, OSError, ValueError) as exc:
        logger.warning("swarm_chrome_profile_unreadable", error=type(exc).__name__)
        return False
    for profile in profiles:
        if profile.id == name.lower():
            script = profile.custom_command.script if profile.custom_command else ""
            return "--chrome" in profile.flags or "--chrome" in script.split()
    return False


def launch_args_for_agent(agent: dict, state_dir: Path, *, chrome_profile: bool = False, commit_guard_on: bool = False) -> List[str]:
    args = ["--agent", str(agent["slug"]), "--effort", str(agent["effort"])]
    if commit_guard_on and agent["rank"] not in UPPER_RANKS:
        args += ["--settings", str(settings_path(state_dir, agent["id"]))]
    if agent["rank"] in UPPER_RANKS:
        args += ["--setting-sources", "project,local", "--strict-mcp-config", "--tools", _UPPER_CLI_TOOLS,
                 "--settings", str(settings_path(state_dir, agent["id"])),
                 "--add-dir", str(desk_dir(state_dir, agent["id"]))]
    if agent["rank"] in UPPER_RANKS or not chrome_profile:
        args.append("--no-chrome")
    return args


def swarm_argv(agent: dict, state_dir: Path) -> List[str]:
    chrome = agent["rank"] not in UPPER_RANKS and profile_names_chrome(agent)
    guard = commit_guard.apply(state_dir, agent, settings_path(state_dir, agent["id"]))
    return launch_args_for_agent(agent, state_dir, chrome_profile=chrome, commit_guard_on=guard)


def swarm_launch_args(
    session_row_id: Optional[int], *, conn: Optional[sqlite3.Connection] = None
) -> List[str]:
    """The Swarm flags for the session row, ``[]`` for a plain row (or no row, or no Swarm table).

    Inputs: session_row_id (the ``sessions.id`` integer); conn (a ``db.connect()`` connection, else one is
    opened and closed here). A datastore file that does not exist yet has no Swarm rows (``[]``).
    Raises: SwarmLaunchUnreadable - the datastore exists and could not be read. FAIL CLOSED: answering ``[]`` would
    start a Swarm row as a plain claude with no ``--agent`` and no lockdown.
    """
    if not isinstance(session_row_id, int) or isinstance(session_row_id, bool):
        return []
    from src.config import settings

    if conn is None:
        path = db_path_for(settings.get_state_dir())
        if not Path(path).exists():
            return []
        try:
            with closing(connect(path, create=False)) as own:
                return swarm_launch_args(session_row_id, conn=own)
        except (DatastoreUnreadableError, OSError, sqlite3.Error) as exc:
            logger.warning("swarm_launch_args_unreadable", session_row_id=session_row_id, error=type(exc).__name__)
            raise SwarmLaunchUnreadable(f"cannot tell whether session row {session_row_id} is a Swarm agent") from exc
    if not table_exists(conn, "swarm_agents"):
        return []
    agent = get_agent_by_session_row(conn, session_row_id)
    return swarm_argv(agent, settings.get_state_dir()) if agent else []


def with_swarm_args(
    session_row_id: Optional[int], args: Optional[Sequence[str]], *, conn: Optional[sqlite3.Connection] = None,
    hold: bool = False,
) -> Optional[List[str]]:
    swarm = swarm_launch_args(session_row_id, conn=conn)
    if hold:
        from src.core.swarm import switch

        switch.hold_launch(bool(swarm), f"row {session_row_id}")
    if not swarm:
        from src.core.swarm.resume_agent import plain_resume_override

        override = plain_resume_override(args)
        return None if args is None else override + list(args)
    return swarm + list(args or [])


def with_swarm_args_for_tmux(
    socket_name: str, name: str, args: Optional[Sequence[str]], *, hold: bool = False
) -> Optional[List[str]]:
    """:func:`with_swarm_args` for a live tmux session found by socket and name (the restart seam).

    Inputs: hold (bool) - passed to :func:`with_swarm_args` (a launch, not a preview).
    Raises: SwarmLaunchUnreadable - an existing datastore could not be read (fail closed, see ``swarm_launch_args``);
    a datastore file that does not exist yet leaves ``args`` unchanged. switch.BodyHeld as :func:`with_swarm_args`.
    """
    from src.config import settings
    from src.core.session_store import identity_for_live_name, sessions_table_ready

    path = db_path_for(settings.get_state_dir())
    if not Path(path).exists():
        return None if args is None else list(args)
    try:
        with closing(connect(path, create=False)) as conn:
            identity = identity_for_live_name(conn, socket=socket_name, name=name) if sessions_table_ready(conn) else None
            return with_swarm_args(identity["id"] if identity else None, args, conn=conn, hold=hold)
    except (DatastoreUnreadableError, OSError, sqlite3.Error) as exc:
        logger.warning("swarm_launch_args_unreadable", name=name, error=type(exc).__name__)
        raise SwarmLaunchUnreadable(f"cannot tell whether session {name!r} is a Swarm agent") from exc


def restart_resume_args(socket_name: str, name: str, resume_target: Any, *, preview: bool = False) -> Optional[List[str]]:
    from src.core.session_resume_target import resume_extra_args

    return with_swarm_args_for_tmux(socket_name, name, resume_extra_args(resume_target), hold=not preview)
