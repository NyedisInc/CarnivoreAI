
from __future__ import annotations

import asyncio
import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

import structlog

from src.core.agent_families import AGENT_FAMILY_BY_NAME
from src.core.launch_profiles import create_seam
from src.core.launch_profiles.plan import LaunchDisplay
from src.core.launch_profiles.resolve import LaunchProfileNotFound
from src.core.launch_record import write_launch_record
from src.core.session_agent_infer import restart_agent_type

logger = structlog.get_logger()


@dataclass(frozen=True)
class ReplayedLaunch:

    command: str
    staged: Dict[str, str] = field(default_factory=dict)
    record: Optional[str] = None
    display: Optional[LaunchDisplay] = None


def launch_row(conn: sqlite3.Connection, socket: str, name: str) -> Optional[Dict[str, Any]]:
    from src.core.session_store import identity_for_live_name

    row = identity_for_live_name(conn, socket=socket, name=name)
    if row is None:
        return None
    usable = restart_agent_type(row.get("agent_type"), row.get("agent_family_source"))
    if not usable:
        return {"agent_type": None, "launch_record": None, "model": None}
    extra = conn.execute("SELECT launch_record, model FROM sessions WHERE id = ?", (int(row["id"]),)).fetchone()
    return {"agent_type": usable, "launch_record": extra["launch_record"], "model": extra["model"]}


def _record_profile(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    try:
        record = json.loads(raw)
    except ValueError:
        logger.warning("launch_record_unreadable")
        return None
    return str(record.get("profile") or "") if isinstance(record, dict) else None


def check_relaunch(settings: Any, agent_type: Optional[str], raw_record: Optional[str]) -> bool:
    recorded = _record_profile(raw_record)
    if recorded is None:
        return False
    asked = str(agent_type or "")
    create_seam.check_explicit_pick(settings, recorded if not asked or asked.lower() in AGENT_FAMILY_BY_NAME else asked)
    return True


async def replay(
    settings: Any, row: Optional[Mapping[str, Any]], *, model: Optional[str], extra_args: Optional[Sequence[str]],
    preview: bool = False,
) -> Optional[ReplayedLaunch]:
    if row is None or not check_relaunch(settings, row.get("agent_type"), row.get("launch_record")):
        return None
    agent_type = str(row.get("agent_type") or "")
    return await resolve_replay(settings, agent_type, model=model or row.get("model") or None,
                                extra_args=extra_args, preview=preview)


async def resolve_replay(
    settings: Any, agent_type: str, *, model: Optional[str], extra_args: Optional[Sequence[str]], preview: bool = False,
    record_only: bool = False,
) -> Optional[ReplayedLaunch]:
    sink: List[Any] = []
    command = settings.pane_launch_command(
        agent_type, model=model, extra_args=list(extra_args or ()), plan_sink=sink)
    if not sink:
        return None
    plan = sink[0]
    if preview:
        return ReplayedLaunch(command=command, display=plan.display)
    if record_only:
        return ReplayedLaunch(command=command, record=await create_seam.record_for(plan), display=plan.display)
    prepared = await create_seam.prepare(plan)
    return ReplayedLaunch(command=command, staged=prepared.staged, record=prepared.record, display=plan.display)


async def replay_for_restart(
    settings: Any, conn: Optional[sqlite3.Connection], socket: str, name: str, *, model: Optional[str],
    extra_args: Optional[Sequence[str]], preview: bool = False, picked: bool = False,
) -> Optional[ReplayedLaunch]:
    row = None
    if conn is not None:
        try:
            row = launch_row(conn, socket, name)
        except sqlite3.Error as exc:
            logger.debug("restart_launch_row_read_failed", name=name, error=type(exc).__name__)
        finally:
            conn.close()
    try:
        return await replay(settings, row, model=model, extra_args=extra_args, preview=preview)
    except LaunchProfileNotFound:
        if not picked:
            raise
        return None


def _with_account(record: str, account_id: str) -> str:
    data = json.loads(record)
    data.setdefault("account", {})["id"] = create_seam.recorded_account_id(data.get("harness", ""), account_id)
    return json.dumps(data, sort_keys=True, separators=(",", ":"))


async def write_record(
    settings: Any, conn: Optional[sqlite3.Connection], replayed: Optional[ReplayedLaunch], chosen_type: Optional[str],
    session_uuid: Optional[str], *, model: Optional[str], extra_args: Optional[Sequence[str]],
    account_id: Optional[str] = None,
) -> bool:
    try:
        if chosen_type:
            replayed = await resolve_replay(settings, chosen_type, model=model, extra_args=extra_args, record_only=True)
        if conn is None or replayed is None or not replayed.record or not session_uuid:
            return False
        record = replayed.record if account_id is None else await asyncio.to_thread(_with_account, replayed.record, account_id)
        return write_launch_record(conn, session_uuid=session_uuid, record=record)
    except (ValueError, OSError, RuntimeError, NotImplementedError, sqlite3.Error) as exc:
        logger.warning("restart_launch_record_not_persisted", error=type(exc).__name__)
        return False
    finally:
        if conn is not None:
            conn.close()
