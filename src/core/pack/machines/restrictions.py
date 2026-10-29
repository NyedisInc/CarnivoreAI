
from __future__ import annotations

import asyncio
from typing import Any, Callable, Dict, FrozenSet, List, Optional

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

ACTION_HOST_AGENTS = "host_agents"
ACTION_INSTALL_TOOLS = "install_tools"
ACTION_RECEIVE_CREDENTIALS = "receive_credentials"
ACTION_UPDATE_CARNIVORE = "update_carnivore"
ACTION_RECEIVE_PROJECTS = "receive_projects"

MANAGED_SCOPES: FrozenSet[str] = frozenset({"machine", "replica", "migrate", "credentials", "refresh", "swarm-proxy", "skills"})


class Restrictions(BaseModel):
    """The document. ``max_agents`` None is no cap; empty allowed lists mean every project and company."""

    model_config = ConfigDict(extra="forbid")

    may_install_tools: bool = True
    may_receive_credentials: bool = False
    may_update_carnivore: bool = True
    may_host_agents: bool = True
    may_receive_projects: bool = True
    max_agents: Optional[int] = Field(default=None, ge=0, le=10000)
    allowed_projects: List[str] = Field(default_factory=list, max_length=500)
    allowed_companies: List[str] = Field(default_factory=list, max_length=500)


_BOOLS = ("may_install_tools", "may_receive_credentials", "may_update_carnivore", "may_host_agents",
          "may_receive_projects")


def from_dict(raw: Any) -> Restrictions:
    if not isinstance(raw, dict):
        return Restrictions()
    try:
        return Restrictions(**raw)
    except (TypeError, ValueError):
        return Restrictions()


def merged(current: Restrictions, patch: Dict[str, Any]) -> Restrictions:
    base = current.model_dump()
    unknown = sorted(set(patch) - set(base))
    if unknown:
        raise ValueError(f"unknown restriction {', '.join(unknown)}")
    base.update(patch)
    return Restrictions(**base)


def _list_narrows(old: List[str], new: List[str]) -> bool:
    return bool(new) and (not old or set(new) <= set(old))


def loosened_rules(old: Restrictions, new: Restrictions) -> List[str]:
    out = [name for name in _BOOLS if getattr(new, name) and not getattr(old, name)]
    if old.max_agents is not None and (new.max_agents is None or new.max_agents > old.max_agents):
        out.append("max_agents")
    for name in ("allowed_projects", "allowed_companies"):
        old_list, new_list = getattr(old, name), getattr(new, name)
        if old_list and not _list_narrows(old_list, new_list):
            out.append(name)
    return out


def narrows(old: Restrictions, new: Restrictions) -> bool:
    return not loosened_rules(old, new)


def check(restrictions: Restrictions, action: str, *, project_uid: Optional[str] = None,
          company_uid: Optional[str] = None, live_agents: int = 0) -> Optional[str]:
    if action == ACTION_HOST_AGENTS:
        if not restrictions.may_host_agents:
            return "may_host_agents"
        if restrictions.max_agents is not None and live_agents >= restrictions.max_agents:
            return "max_agents"
        if restrictions.allowed_projects and project_uid is not None and project_uid not in restrictions.allowed_projects:
            return "allowed_projects"
        if restrictions.allowed_companies and company_uid is not None and company_uid not in restrictions.allowed_companies:
            return "allowed_companies"
        return None
    flag = {ACTION_INSTALL_TOOLS: "may_install_tools", ACTION_RECEIVE_CREDENTIALS: "may_receive_credentials",
            ACTION_UPDATE_CARNIVORE: "may_update_carnivore", ACTION_RECEIVE_PROJECTS: "may_receive_projects"}.get(action)
    if flag is None:
        return "unknown_action"
    return None if getattr(restrictions, flag) else flag


def refusal(rule: str) -> HTTPException:
    return HTTPException(403, {"code": "pack_restricted", "rule": rule,
                               "detail": f"this computer's own restriction {rule} refuses that"})


def enforce(restrictions: Restrictions, action: str, **subject: Any) -> None:
    rule = check(restrictions, action, **subject)
    if rule is not None:
        raise refusal(rule)


def scopes_for(restrictions: Restrictions, *, tracks_master: bool) -> FrozenSet[str]:
    out = set()
    if restrictions.may_host_agents or restrictions.allowed_projects:
        out.add("replica")
    if restrictions.may_receive_projects:
        out.add("migrate")
    if restrictions.may_receive_credentials:
        out.add("credentials")
    if restrictions.may_update_carnivore and tracks_master:
        out.add("refresh")
    return frozenset(out)


_agent_counter: Callable[[], int] = lambda: 0  # noqa: E731


def set_agent_counter(counter: Callable[[], int]) -> None:
    global _agent_counter
    _agent_counter = counter


def live_agents() -> int:
    return _agent_counter()


def require_peer_allowed(action: str, subject: Optional[Callable[[Any], Dict[str, Any]]] = None):
    async def dependency(request: Request) -> None:
        from src.core.pack.machines import config_state

        current = await asyncio.to_thread(config_state.default().restrictions)
        enforce(current, action, live_agents=live_agents(), **(subject(request) if subject else {}))

    return dependency
