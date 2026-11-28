
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

from src.core.session_delivery import bring_up
from src.core.session_startup_gate import GATE_READY

PROJECT = 7
NOW = datetime(2026, 11, 18, tzinfo=timezone.utc)


def row(ses_id: str, minutes_ago: int = 0, family: Optional[str] = "claude", agent_type: Optional[str] = None,
        status: str = "idle") -> SimpleNamespace:
    session = SimpleNamespace(id=ses_id, last_activity=NOW - timedelta(minutes=minutes_ago), agent_type=None)
    return SimpleNamespace(session=session, project_id=PROJECT, agent_family=family, agent_type=agent_type, activity_status=status,
                           startup_gate=GATE_READY)


class FakeOps:

    def __init__(self, live: Optional[List[SimpleNamespace]] = None, asleep: Optional[List[str]] = None,
                 refuse: Optional[str] = None) -> None:
        self.live: List[SimpleNamespace] = list(live or [])
        self.sleepers: List[str] = list(asleep or [])
        self.refuse = refuse
        self.woken: List[str] = []
        self.started: List[int] = []

    async def list(self) -> List[Any]:
        return list(self.live)

    async def durable_keys(self, infos: Optional[List[Any]] = None) -> Dict[str, str]:
        return {i.session.id: "u-" + i.session.id.removeprefix("ses_") for i in self.live}

    async def asleep(self) -> List[Dict[str, Any]]:
        return [{"session_uuid": u, "project_id": PROJECT} for u in self.sleepers]

    async def wake(self, session_uuid: str) -> Dict[str, Any]:
        self.woken.append(session_uuid)
        await asyncio.sleep(0.01)
        if session_uuid == self.refuse or session_uuid not in self.sleepers:
            return {"status": "refused", "code": "nope"}
        self.sleepers.remove(session_uuid)
        self.live.append(row("ses_" + session_uuid.removeprefix("u-")))
        return {"status": "started"}

    async def start(self, project_id: int) -> str:
        self.started.append(project_id)
        self.live.append(row("ses_new"))
        return "ses_new"


@pytest.fixture(autouse=True)
def no_offer(monkeypatch) -> None:
    monkeypatch.setattr(bring_up, "offer_holds_projects", lambda: set())
    monkeypatch.setattr(bring_up, "_BRING_UP_LOCKS", {})


def test_an_asleep_lead_is_woken_before_a_newer_non_lead_sleeper():
    ops = FakeOps(asleep=["u-newer", "u-lead"])
    assert asyncio.run(bring_up.wake_newest_or_start(ops, PROJECT, lead_key="u-lead")) == "ses_lead"
    assert ops.woken == ["u-lead"] and ops.started == []


def test_the_wake_only_path_also_wakes_the_lead_first():
    ops = FakeOps(asleep=["u-newer", "u-lead"])
    assert asyncio.run(bring_up.wake_newest(ops, PROJECT, lead_key="u-lead")) == "ses_lead"
    assert ops.woken == ["u-lead"]


def test_an_asleep_lead_is_woken_even_beside_a_running_non_lead():
    ops = FakeOps(live=[row("ses_running")], asleep=["u-other", "u-lead"])
    assert asyncio.run(bring_up.wake_newest(ops, PROJECT, lead_key="u-lead")) == "ses_lead"
    assert asyncio.run(bring_up.wake_newest_or_start(ops, PROJECT, lead_key="u-lead")) == "ses_lead"
    assert ops.woken == ["u-lead"] and ops.started == []


def test_with_no_lead_a_running_agent_takes_the_delivery_and_nothing_is_woken():
    ops = FakeOps(live=[row("ses_running")], asleep=["u-other"])
    assert asyncio.run(bring_up.wake_newest_or_start(ops, PROJECT)) == "ses_running"
    assert ops.woken == [] and ops.started == []


def test_a_codex_agent_counts_as_running():
    ops = FakeOps(live=[row("ses_codex", family="codex")], asleep=["u-other"])
    assert asyncio.run(bring_up.wake_newest_or_start(ops, PROJECT)) == "ses_codex"
    ops = FakeOps(live=[row("ses_codex", family=None, agent_type="codex"), row("ses_newer", minutes_ago=0)])
    assert asyncio.run(bring_up.wake_newest(ops, PROJECT, lead_key="u-codex")) == "ses_codex"
    assert ops.woken == [] and ops.started == []


def test_the_leads_wake_refused_on_the_no_start_path_goes_to_the_running_agent():
    ops = FakeOps(live=[row("ses_running")], asleep=["u-other", "u-lead"], refuse="u-lead")
    assert asyncio.run(bring_up.wake_newest(ops, PROJECT, lead_key="u-lead")) == "ses_running"
    assert ops.woken == ["u-lead"] and ops.started == []


def test_two_concurrent_wakes_for_one_project_wake_exactly_one_session():
    ops = FakeOps(asleep=["u-a", "u-b"])

    async def both() -> List[Any]:
        return list(await asyncio.gather(bring_up.wake_newest(ops, PROJECT), bring_up.wake_newest(ops, PROJECT), return_exceptions=True))

    got = asyncio.run(both())
    assert got == ["ses_a", "ses_a"] and ops.woken == ["u-a"]


def test_a_running_agent_known_only_by_its_agent_type_still_counts_as_running():
    ops = FakeOps(live=[row("ses_unresolved", family=None, agent_type="claude-code")], asleep=["u-other"])
    assert asyncio.run(bring_up.wake_newest(ops, PROJECT)) == "ses_unresolved"
    assert ops.woken == [] and ops.started == []


def test_a_lead_that_will_not_wake_is_not_replaced_by_another_sleeper():
    ops = FakeOps(asleep=["u-newer", "u-lead"], refuse="u-lead")
    with pytest.raises(bring_up.BringUpFailed):
        asyncio.run(bring_up.wake_newest_or_start(ops, PROJECT, lead_key="u-lead"))
    assert ops.woken == ["u-lead"] and ops.started == []


def unstick_ctx(monkeypatch, ops: FakeOps, lead_key: str, swarm: Any = None) -> SimpleNamespace:
    from src.plugins.taskmanager import service

    seat = SimpleNamespace(lead_key=lead_key)
    monkeypatch.setattr(service, "store", lambda ctx: None)
    monkeypatch.setattr(service, "RoleStore", lambda store: SimpleNamespace(seat=lambda key: seat))
    return SimpleNamespace(sessions=ops, swarm=swarm)


def test_the_unstick_fallback_picks_the_running_lead_over_a_newer_running_agent(monkeypatch):
    from src.plugins.taskmanager import service

    ops = FakeOps(live=[row("ses_newer", minutes_ago=1), row("ses_lead", minutes_ago=90, family=None, agent_type="claude")])
    assert asyncio.run(service.bring_up_session(unstick_ctx(monkeypatch, ops, "u-lead"), str(PROJECT))) == "ses_lead"
    assert ops.woken == [] and ops.started == []


def test_the_unstick_fallback_wakes_the_asleep_lead_not_the_newest_sleeper(monkeypatch):
    from src.plugins.taskmanager import service

    ops = FakeOps(asleep=["u-newer", "u-lead"])
    assert asyncio.run(service.bring_up_session(unstick_ctx(monkeypatch, ops, "u-lead"), str(PROJECT))) == "ses_lead"
    assert ops.woken == ["u-lead"]


def test_a_dead_lead_next_to_a_live_non_lead_goes_to_the_live_one_and_wakes_nothing(monkeypatch):
    from src.plugins.taskmanager import service

    ops = FakeOps(live=[row("ses_lead", status="dead"), row("ses_live", minutes_ago=5)], asleep=["u-other"])
    assert asyncio.run(service.bring_up_session(unstick_ctx(monkeypatch, ops, "u-lead"), str(PROJECT))) == "ses_live"
    assert asyncio.run(bring_up.wake_newest(ops, PROJECT, lead_key="u-lead")) == "ses_live"
    assert ops.woken == [] and ops.started == []


class SwarmStub:

    def __init__(self, ops: FakeOps) -> None:
        self.ops, self.woken, self.awake = ops, [], False

    async def agent_by_id(self, agent_id: int) -> Any:
        return SimpleNamespace(id=agent_id, session_id="ses_body" if self.awake else None, session_uuid="u-body")

    async def wake(self, agent_id: int, why: str) -> None:
        self.woken.append(agent_id)
        self.awake = True
        self.ops.sleepers.remove("u-body")
        self.ops.live.append(row("ses_body"))


def test_a_swarm_lead_key_is_woken_through_the_swarm_never_by_uuid(monkeypatch):
    from src.plugins.taskmanager import service

    ops = FakeOps(asleep=["u-newer", "u-body"])
    swarm = SwarmStub(ops)
    assert asyncio.run(service.bring_up_session(unstick_ctx(monkeypatch, ops, "swarm:7", swarm), str(PROJECT))) == "ses_body"
    assert swarm.woken == [7] and ops.woken == [] and ops.started == []
