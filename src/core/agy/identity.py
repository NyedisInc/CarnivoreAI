
from __future__ import annotations

from typing import Any, Iterable, Optional

AGY = "agy"


def is_agy_agent_block(agent: Any) -> bool:
    if agent is None:
        return False
    get = agent.get if isinstance(agent, dict) else lambda key: getattr(agent, key, None)
    return AGY in (get("process"), get("rules"))


def is_agy_profile(profile: Any) -> bool:
    agent = profile.get("agent") if isinstance(profile, dict) else getattr(profile, "agent", None)
    return is_agy_agent_block(agent)


def is_agy_agent_type(agent_type: Optional[str], profiles: Iterable[Any]) -> bool:
    wanted = (agent_type or "").lower()
    if not wanted:
        return False
    for profile in profiles:
        pid = profile.get("id") if isinstance(profile, dict) else getattr(profile, "id", None)
        if str(pid or "").lower() == wanted:
            return is_agy_profile(profile)
    return False


def row_is_agy(row: Any, profiles: Optional[Iterable[Any]] = None) -> bool:
    if row.get("agent_family") != "custom":
        return False
    if profiles is None:
        from src.config import settings  # noqa: PLC0415

        profiles = settings.get_launch_profiles()
    return is_agy_agent_type(row.get("agent_type"), profiles)


def agy_profile_id(profiles: Optional[Iterable[Any]] = None) -> Optional[str]:
    if profiles is None:
        from src.config import settings  # noqa: PLC0415

        profiles = settings.get_launch_profiles()
    fallback: Optional[str] = None
    for profile in profiles:
        if not is_agy_profile(profile):
            continue
        pid = profile.get("id") if isinstance(profile, dict) else getattr(profile, "id", None)
        if not pid:
            continue
        is_def = profile.get("default") if isinstance(profile, dict) else getattr(profile, "default", False)
        if is_def:
            return str(pid)
        if fallback is None:
            fallback = str(pid)
    return fallback


def info_is_agy(info: Any, profiles: Optional[Iterable[Any]] = None) -> bool:
    family = getattr(info, "agent_family", None)
    if family != "custom":
        return False
    session = getattr(info, "session", None)
    agent_type = getattr(info, "agent_type", None) or getattr(session, "agent_type", None)
    return row_is_agy({"agent_family": family, "agent_type": agent_type}, profiles)
