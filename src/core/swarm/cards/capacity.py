
from __future__ import annotations

import sqlite3
import time
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Deque, Dict, Mapping, Optional, Tuple

import structlog

from src.config import settings as app_settings
from src.core.launch_profiles.resolve import default_profile
from src.core.launch_profiles.store import LaunchProfileError, LaunchProfileStore
from src.core.swarm import conflicts, settings as swarm_settings, store
from src.core.swarm.cards import cpu, port as card_port
from src.core.provider_ledger import poller as ledger_poller
from src.core.session_token_usage.account_resolve import resolve_session_account

logger = structlog.get_logger()

CPU_FLOOR_PCT = 85.0
USAGE_FLOOR_PCT = 90.0
CPU_INTERVALS = 4
MIN_GAP_S = 10.0
USAGE_FRESH_S = 900.0
GRANT_MAX = 20
SCOPE_KINDS = ("company", "project")

REFUSAL_TEXT = {
    "floor_cpu": "the machine's CPU has been over 85% for two minutes, so no new agent starts",
    "floor_usage": "an account's usage window is over 90%, so no new agent starts",
    "no_slot": "this project has no free agent slot",
}


@dataclass(frozen=True)
class Reading:

    cpu_busy_pct: Optional[float]
    cpu_floor: bool
    usage_max_pct: Optional[float]
    usage_floor: bool
    usage_account: Optional[str]
    usage_window: Optional[str]
    live_bodies: int
    cap_total: Optional[int]
    cap_per_parent: Optional[int]
    at: float

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


_last: Optional[Tuple[float, cpu.Ticks]] = None
_busy: Deque[float] = deque(maxlen=CPU_INTERVALS)


def reset() -> None:
    global _last
    _last = None
    _busy.clear()


def sample(clock: float, read: Optional[Callable[[], Optional[cpu.Ticks]]] = None) -> None:
    global _last
    cur = (read or cpu.ticks)()
    if cur is None:
        reset()
        return
    if _last is None:
        _last = (clock, cur)
        return
    if clock - _last[0] < MIN_GAP_S:
        return
    busy = cpu.busy_pct(_last[1], cur)
    _last = (clock, cur)
    if busy is None:
        _busy.clear()
    else:
        _busy.append(busy)


def cpu_state() -> Tuple[Optional[float], bool]:
    busy = tuple(_busy)
    latest = busy[-1] if busy else None
    return latest, len(busy) == CPU_INTERVALS and all(b > CPU_FLOOR_PCT for b in busy)


@dataclass(frozen=True)
class Usage:

    pct: Optional[float]
    floor: bool
    account: Optional[str]
    window: Optional[str]


def usage_state(account_id: Optional[str] = None, now: Optional[float] = None) -> Usage:
    stamp = time.time() if now is None else now
    best: Usage = Usage(None, False, None, None)
    for account in ledger_poller.snapshot().accounts:
        fetched = account.fetched_at
        if account.provider != "claude" or account.credential_state != "ok" or fetched is None or stamp - fetched.timestamp() > USAGE_FRESH_S:
            continue
        if account_id is not None and account.id != account_id:
            continue
        for window in account.windows:
            if best.pct is None or window.used_pct > best.pct:
                best = Usage(window.used_pct, window.used_pct > USAGE_FLOOR_PCT, account.name, window.label)
    return best


def account_for(profile: Optional[str]) -> Optional[str]:
    config_path = Path(app_settings.auth_config_file).expanduser()
    try:
        profiles = LaunchProfileStore(config_path).list()
    except (LaunchProfileError, OSError, ValueError) as exc:
        logger.warning("card_capacity_profiles_unreadable", error_type=type(exc).__name__)
        return None
    chosen = next((p for p in profiles if p.id == (profile or "").lower()), None)
    if profile and chosen is None:
        return None
    if chosen is None or chosen.harness != "claude":
        chosen = default_profile(profiles, "claude")
    if chosen.account.mode == "pinned":
        known = {a.id for a in ledger_poller.snapshot().accounts if a.provider == "claude"}
        return chosen.account.account_id if chosen.account.account_id in known else None
    config_dir = next((row.value for row in chosen.env if row.name == "CLAUDE_CONFIG_DIR" and row.value), None)
    row = resolve_session_account(config_path, agent_family="claude", profile_dir=config_dir)
    return row.id if row else None


def usage_for(profile: Optional[str] = None) -> Usage:
    return usage_state(account_for(profile))


def _workers(conn: sqlite3.Connection, where: str, args: Tuple[Any, ...]) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM swarm_wakes w JOIN swarm_agents a ON a.id = w.agent_id WHERE w.ended_at IS NULL "
                            f"AND a.torn_down_at IS NULL AND a.rank != 'project' AND {where}", args).fetchone()[0])


def project_workers(conn: sqlite3.Connection, project_id: int) -> int:
    return _workers(conn, "a.project_id = ?", (project_id,))


def company_of(conn: sqlite3.Connection, project_id: Optional[int]) -> Optional[int]:
    if project_id is None:
        return None
    row = conn.execute("SELECT company_id FROM projects WHERE id = ?", (project_id,)).fetchone()
    return row["company_id"] if row else None


def slots(conn: sqlite3.Connection, project_id: int, grants: Mapping[str, int]) -> Tuple[Optional[int], Optional[int]]:
    cfg = swarm_settings.read_current()
    limits = [int(grants[f"project:{project_id}"]) if f"project:{project_id}" in grants else cfg.max_live_bodies]
    company = company_of(conn, project_id)
    if company is not None and f"company:{company}" in grants:
        others = _workers(conn, "a.project_id IN (SELECT id FROM projects WHERE company_id = ? AND id != ?)", (company, project_id))
        limits.append(int(grants[f"company:{company}"]) - others)
    if conflicts.current(project_id) is not None:
        limits.append(conflicts.THROTTLED_WORKERS)
    known = [n for n in limits if n is not None]
    if not known:
        return None, None
    granted = max(0, min(known))
    free = granted - _workers(conn, "a.project_id = ?", (project_id,))
    if cfg.max_live_bodies is not None:
        free = min(free, cfg.max_live_bodies - store.live_body_count(conn))
    return max(0, free), granted


def floor_refusal(profile: Optional[str] = None) -> Optional[str]:
    if cpu_state()[1]:
        return "floor_cpu"
    return "floor_usage" if usage_for(profile).floor else None


def refusal_text(code: str, profile: Optional[str] = None) -> str:
    if code != "floor_usage":
        return REFUSAL_TEXT[code]
    usage = usage_for(profile)
    if usage.pct is None or not usage.floor:
        return REFUSAL_TEXT[code]
    return f"the {usage.account} account's {usage.window} usage window is at {usage.pct:g}%, over {USAGE_FLOOR_PCT:g}%, so no new agent starts"


def refusal(conn: sqlite3.Connection, project_id: Optional[int], grants: Mapping[str, int], *, floors: bool = True, profile: Optional[str] = None) -> Optional[str]:
    if floors:
        floor = floor_refusal(profile)
        if floor:
            return floor
    if project_id is None:
        cap = swarm_settings.read_current().max_live_bodies
        return None if cap is None or cap - store.live_body_count(conn) > 0 else "no_slot"
    free = slots(conn, project_id, grants)[0]
    return None if free is None or free > 0 else "no_slot"


def reading(conn: sqlite3.Connection) -> Reading:
    cfg = swarm_settings.read_current()
    busy, cpu_floor = cpu_state()
    usage = usage_for()
    return Reading(cpu_busy_pct=busy, cpu_floor=cpu_floor, usage_max_pct=usage.pct, usage_floor=usage.floor, usage_account=usage.account, usage_window=usage.window,
                   live_bodies=store.live_body_count(conn), cap_total=cfg.max_live_bodies, cap_per_parent=cfg.max_children_per_parent, at=time.time())


async def grants_by_scope() -> Dict[str, int]:
    return {g["scope"]: int(g["slots"]) for g in (await card_port.get().policy_read("grants", {}))["grants"]}


async def gate_inputs(project_id: Optional[int]) -> Tuple[Dict[str, int], bool]:
    grants = await grants_by_scope()
    if project_id is None:
        return grants, False
    return grants, bool((await card_port.get().policy_read("dealing", {"project_key": str(project_id)}))["dealing"])


def grant_refusal(agent: Optional[Mapping[str, Any]], scope: str, scope_company: Optional[int]) -> Optional[str]:
    if agent is None or agent.get("rank") == "alpha":
        return None
    if agent.get("rank") == "company" and scope.startswith("project:") and scope_company is not None and agent.get("company_id") == scope_company:
        return None
    return "only SysOp grants capacity, and a company agent only for the projects of its own company"


def pace_refusal(agent: Optional[Mapping[str, Any]], project_id: int, project_company: Optional[int]) -> Optional[str]:
    if agent is None or agent.get("rank") == "alpha":
        return None
    if agent.get("rank") == "project" and agent.get("project_id") == project_id:
        return None
    if agent.get("rank") == "company" and project_company is not None and agent.get("company_id") == project_company:
        return None
    return "only SysOp, the project's own agent or its company agent sets a project's pace"
