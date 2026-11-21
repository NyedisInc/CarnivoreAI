
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from src.core.session_delivery import bring_up

PROJECT = 7
NOW = datetime(2026, 11, 17, tzinfo=timezone.utc)


def info(ses_id: str, project_id: int = PROJECT, minutes_ago: int = 0, status: str = "idle") -> SimpleNamespace:
    session = SimpleNamespace(id=ses_id, last_activity=NOW - timedelta(minutes=minutes_ago))
    return SimpleNamespace(session=session, project_id=project_id, agent_family="claude", activity_status=status, startup_gate="ready")


class FakeOps:

    def __init__(self, live: Optional[List[SimpleNamespace]] = None) -> None:
        self.live: List[SimpleNamespace] = list(live or [])
        self.started: List[int] = []

    async def list(self) -> List[Any]:
        return list(self.live)

    async def durable_keys(self, infos: Optional[List[Any]] = None) -> Dict[str, str]:
        return {i.session.id: f"key-{i.session.id}" for i in self.live}

    async def asleep(self) -> List[Dict[str, Any]]:
        return []

    async def wake(self, session_uuid: str) -> Dict[str, Any]:
        raise AssertionError("nothing is asleep")

    async def start(self, project_id: int) -> str:
        self.started.append(project_id)
        await asyncio.sleep(0.01)
        new_id = f"ses_new{len(self.started)}"
        self.live.append(info(new_id, project_id))
        return new_id


def patch_offer(monkeypatch) -> None:
    monkeypatch.setattr(bring_up, "offer_holds_projects", lambda: set())


def test_two_concurrent_deliveries_start_one_session(monkeypatch):
    patch_offer(monkeypatch)
    ops = FakeOps()

    async def both() -> List[str]:
        return list(await asyncio.gather(bring_up.wake_newest_or_start(ops, PROJECT), bring_up.wake_newest_or_start(ops, PROJECT)))

    got = asyncio.run(both())
    assert ops.started == [PROJECT] and got[0] == got[1]


def test_a_running_session_is_used_and_the_lead_comes_first(monkeypatch):
    patch_offer(monkeypatch)
    ops = FakeOps([info("ses_recent", minutes_ago=1), info("ses_lead", minutes_ago=50), info("ses_other_project", project_id=9)])
    assert asyncio.run(bring_up.wake_newest_or_start(ops, PROJECT)) == "ses_recent"
    assert asyncio.run(bring_up.wake_newest_or_start(ops, PROJECT, lead_key="key-ses_lead")) == "ses_lead"
    assert ops.started == []


def test_a_dead_row_is_not_used_and_a_new_session_starts(monkeypatch):
    patch_offer(monkeypatch)
    ops = FakeOps([info("ses_dead", status="dead")])
    got = asyncio.run(bring_up.wake_newest_or_start(ops, PROJECT))
    assert ops.started == [PROJECT] and got == "ses_new1"
