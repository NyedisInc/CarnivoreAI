
from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Dict, List, Optional

from src.cplugs.host import session_actions, session_rows
from src.cplugs.huddle import service
from src.cplugs.sdk.swarm import AgentRef, SeatRef
from tests.python.cplugs.huddle.test_task_manager_routes import NOW, row

BASE = "/api/v1/cplugs/huddle"


def aged(session_id: str, project: int, hours_old: float, agent: str = "claude"):
    r = row(session_id, project, agent)
    r.session.created_at = NOW - timedelta(hours=hours_old)
    return r


def give_rows(app, rows: List[object]) -> None:
    async def infos():
        return rows

    app.state.session_manager.list_session_infos = infos


def give_asleep(monkeypatch, records: List[Dict[str, object]]) -> None:
    async def asleep():
        return records

    monkeypatch.setattr(session_actions, "asleep", lambda request: asleep())


def give_stored_rows(monkeypatch, rows) -> None:
    def read(keys):
        if isinstance(rows, BaseException):
            raise rows
        return {k: rows[k] for k in keys if k in rows}

    monkeypatch.setattr(session_rows, "read", read)


class SwarmStub:

    def __init__(self, bodies=(), agent_projects=(), project_agents=None, fallbacks=None, dead=(), hqs=None) -> None:
        self.bodies, self.project_agents = set(bodies), dict(project_agents or {})
        self.agent_projects = set(agent_projects) | set(self.project_agents)
        self.fallbacks, self.dead, self.hqs = dict(fallbacks or {}), set(dead), dict(hqs or {})
        self.promoted, self.woken, self.retired, self.awake = [], [], [], {}

    def agent_seats(self) -> list:
        out = [SeatRef(1, "task", None, key) for key in sorted(self.bodies)]
        for n, project in enumerate(sorted(self.agent_projects), start=10):
            out.append(SeatRef(n, "project", project, self.project_agents.get(project), project in self.dead, f"agent {project}"))
        out += list(self.fallbacks.values())
        return out

    def fallback_agent(self, project_key: str):
        return self.fallbacks.get(project_key)

    async def agent_by_id(self, agent_id: int):
        seat = next((a for a in self.agent_seats() if a.agent_id == agent_id and not a.body_gone), None)
        if seat is None:
            return None
        body = self.awake.get(agent_id)
        return AgentRef(seat.agent_id, "slug", seat.display_name, seat.rank, "t", "awake" if body else "asleep", body, body or seat.session_uuid)

    async def agent_for_session_uuid(self, session_uuid: str):
        seat = next((a for a in self.agent_seats() if a.session_uuid == session_uuid and a.rank != "task" and not a.body_gone), None)
        return None if seat is None else await self.agent_by_id(seat.agent_id)

    async def wake(self, agent_id: int, reason: str):
        seat = next(a for a in self.agent_seats() if a.agent_id == agent_id)
        self.woken.append((agent_id, reason))
        self.awake[agent_id] = seat.session_uuid or f"ses_swarm_{agent_id}"
        self.on_wake(agent_id, self.awake[agent_id])

    def on_wake(self, agent_id: int, body: str) -> None:
        pass

    async def promote_session(self, session_uuid: str, project_key: str):
        self.promoted.append((session_uuid, project_key))
        self.project_agents[project_key] = session_uuid
        self.agent_projects.add(project_key)
        return AgentRef(10, "slug", "agent", "project", project_key, "asleep", None, session_uuid)

    def company_hq(self, project_key: str):
        return self.hqs.get(project_key)

    async def retire_dead_project_agent(self, agent_id: int) -> bool:
        self.retired.append(agent_id)
        project = next((a.project_key for a in self.agent_seats() if a.agent_id == agent_id), None)
        self.agent_projects.discard(project)
        self.dead.discard(project)
        self.project_agents.pop(project, None)
        return True

    async def thread_for_session(self, session_id: str) -> Optional[str]:
        return "agent:1" if session_id in self.bodies else None

    async def bodies_among(self, infos) -> frozenset:
        return frozenset(i.session.id for i in infos if i.session.id in self.bodies)

    def is_agent_key(self, list_key: str) -> bool:
        return list_key in self.agent_projects

    def thread_changed(self, list_key: str) -> None:
        pass

    def deal_requested(self, project_key: str) -> None:
        pass

    def is_waking(self, list_key: str) -> bool:
        return False

    def agent_names(self, keys=None) -> dict:
        return {}


def use_swarm(monkeypatch, stub: SwarmStub) -> SwarmStub:
    monkeypatch.setattr(service, "swarm_of", lambda ctx: stub)
    return stub


__all__ = ["BASE", "NOW", "SimpleNamespace", "SwarmStub", "aged", "give_asleep", "give_rows", "give_stored_rows", "use_swarm"]
