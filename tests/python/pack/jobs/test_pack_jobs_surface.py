
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any, List, Optional

import pytest

from src.core.hosts.ddl import LOCAL_HOST_KEY
from src.core.mcp import beast_mode, call_budget, pending, tools, write_tools
from src.core.mcp import pack_jobs_tools as pjt
from src.core.mcp.caller import AgentCaller
from src.core.mcp.common import ToolError
from src.core.pack.jobs.types import JobError, JobRecord, JobRequest, JobState

CALLER = AgentCaller("ses_a", "tmux_a", "ses_a")
FAKE_SECRET = "ghp_" + "a1B2c3D4" * 4 + "wxyz"


def _payload(result: dict) -> dict:
    return json.loads(result["content"][0]["text"])


class FakeEngine:

    def __init__(self, clock: Optional[dict] = None) -> None:
        self.rows: dict = {}
        self.calls: List[tuple] = []
        self.next_state = JobState.WAITING_APPROVAL
        self.clock = clock
        self.advance_in_propose = 0.0
        self.error: Optional[JobError] = None

    def put(self, state: JobState, job_id: str = "job_000000000001", **fields: Any) -> JobRecord:
        rec = JobRecord(id=job_id, state=state, peer_label="tower", caller_session="uuid-a", created_at=100.0, **fields)
        self.rows[job_id] = rec
        return rec

    async def propose(self, req: JobRequest) -> JobRecord:
        self.calls.append(("propose", req))
        if self.clock is not None:
            self.clock["t"] += self.advance_in_propose
        if self.error:
            raise self.error
        rec = self.put(self.next_state, reason="this computer has room" if self.next_state == JobState.HERE else "tower has room",
                       request_json=json.dumps({"request": {"command": req.command, "folder": req.folder}}))
        rec.caller_session = req.caller_session
        return rec

    async def proceed(self, job_id: str) -> JobRecord:
        self.calls.append(("proceed", job_id))
        self.rows[job_id].state = JobState.RUNNING
        return self.rows[job_id]

    async def wait(self, job_id: str, timeout_s: float) -> JobRecord:
        self.calls.append(("wait", job_id, timeout_s))
        return self.rows[job_id]

    def get(self, job_id: str) -> Optional[JobRecord]:
        return self.rows.get(job_id)

    async def stop(self, job_id: str) -> JobRecord:
        self.calls.append(("stop", job_id))
        self.rows[job_id].state = JobState.STOPPED
        return self.rows[job_id]

    def cancel(self, job_id: str, reason: str = "denied") -> None:
        self.calls.append(("cancel", job_id))
        self.rows[job_id].state = JobState.STOPPED

    def waiter_enter(self, job_id: str) -> None:
        self.calls.append(("waiter_enter", job_id))

    def waiter_leave(self, job_id: str) -> None:
        self.calls.append(("waiter_leave", job_id))

    def names(self, name: str) -> list:
        return [c for c in self.calls if c[0] == name]


@pytest.fixture
def world(tmp_path, monkeypatch):
    eng = FakeEngine()
    monkeypatch.setattr(pjt.boot, "engine", lambda: eng)
    monkeypatch.setattr(pending, "_store", pending.PendingActions())
    monkeypatch.setattr(beast_mode, "approval_skip", lambda action: False)
    info = SimpleNamespace(host_key=LOCAL_HOST_KEY, tmux_session="tmux_a", session_uuid="uuid-a",
                           session=SimpleNamespace(id="ses_a", working_dir=str(tmp_path)))

    async def infos() -> list:
        return [info]

    manager = SimpleNamespace(list_session_infos=infos, gate_waited=True)
    return eng, manager, tmp_path


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_here_parks_nothing_and_never_proceeds(world):
    eng, manager, _ = world
    eng.next_state = JobState.HERE
    out = _payload(run(pjt.delegate(manager, CALLER, {"command": "pytest -q"})))
    assert out == {"decision": "here", "reason": "this computer has room"}
    assert pending.get_store().list() == [] and not eng.names("proceed")


def test_remote_beast_off_parks_then_deny_cancels_and_approve_proceeds_once(world):
    eng, manager, _ = world
    out = _payload(run(pjt.delegate(manager, CALLER, {"command": "pytest -q"})))
    items = pending.get_store().list()
    assert out["status"] == "pending" and out["job_id"] == "job_000000000001" and out["computer"] == "tower"
    assert [i["action"] for i in items] == ["delegate"] and items[0]["args"]["job_id"] == out["job_id"]
    assert items[0]["args"]["computer"] == "tower"
    pending.get_store().deny(items[0]["id"])
    assert eng.names("cancel") == [("cancel", "job_000000000001")]
    eng.rows.clear()
    eng.calls.clear()
    out = _payload(run(pjt.delegate(manager, CALLER, {"command": "pytest -q"})))

    async def approve() -> dict:
        await pending.get_store().approve(out["id"])
        return _payload(await write_tools.approval_wait(manager, CALLER, {"id": out["id"], "timeout": 1}))

    answer = run(approve())
    assert len(eng.names("proceed")) == 1 and answer["status"] == "running" and answer["next"] == "job_wait"


def test_remote_beast_on_skips_the_card_and_waits(world, monkeypatch):
    eng, manager, _ = world
    monkeypatch.setattr(beast_mode, "approval_skip", lambda action: action == "delegate")
    out = _payload(run(pjt.delegate(manager, CALLER, {"command": "pytest -q"})))
    store = pending.get_store()
    assert store.list() == [] and len(store.decided()) == 1
    assert len(eng.names("proceed")) == 1 and len(eng.names("wait")) == 1 and out["status"] == "running"


def test_one_deadline_covers_placement_approval_and_wait(world, monkeypatch):
    eng, manager, _ = world
    clock = {"t": 1000.0}
    eng.clock = clock
    eng.advance_in_propose = 10.0
    monkeypatch.setattr(pjt, "_now", lambda: clock["t"])
    seen = {}

    async def slow_park(mgr, caller, tid, tmux, action, summary, args, runner, **kw):
        seen.update(kw)
        clock["t"] += 35.0
        return await runner(True)

    monkeypatch.setattr(write_tools, "park", slow_park)
    with call_budget.using(50.0):
        out = _payload(run(pjt.delegate(manager, CALLER, {"command": "pytest -q"})))
    waited = eng.names("wait")[0][2]
    assert seen["max_wait"] <= 48 and waited <= 3.0 + 1e-9 and clock["t"] - 1000.0 + waited < 50
    assert out["status"] == "running" and out["job_id"] and out["next"] == "job_wait"
    clock["t"] = 1000.0
    eng.advance_in_propose = 0.0
    eng.calls.clear()
    with call_budget.using(95.0):
        run(pjt.delegate(manager, CALLER, {"command": "pytest -q 2"}))
    assert eng.names("wait")[0][2] <= pjt.CALL_BUDGET_S - 2


def test_job_wait_passes_the_budget_minus_five(world):
    eng, manager, _ = world
    eng.put(JobState.RUNNING)
    with call_budget.using(50.0):
        run(pjt.job_wait(manager, CALLER, {"job_id": "job_000000000001"}))
    with call_budget.using(95.0):
        run(pjt.job_wait(manager, CALLER, {"job_id": "job_000000000001"}))
    assert [c[2] for c in eng.names("wait")] == [45.0, 90.0]
    with call_budget.using(600.0):
        run(pjt.job_wait(manager, CALLER, {"job_id": "job_000000000001", "timeout": 595}))
    assert eng.names("wait")[-1][2] == 595.0
    with pytest.raises(ToolError):
        run(pjt.job_wait(manager, CALLER, {"job_id": "job_000000000001", "timeout": 596}))


def test_refusals(world):
    eng, manager, tmp = world
    eng.next_state = JobState.HERE
    with pytest.raises(ToolError, match="only from a session"):
        run(pjt.delegate(manager, AgentCaller("mcp-token:1", "t", "mcp-token:1", "tok"), {"command": "x"}))
    with pytest.raises(ToolError, match="only from a session"):
        run(pjt.delegate(manager, AgentCaller("ses_a", "tmux_a", "ses_a", proxied_agent_id=3), {"command": "x"}))
    with pytest.raises(ToolError, match="working folder"):
        run(pjt.delegate(manager, CALLER, {"command": "x", "folder": "/etc"}))
    with pytest.raises(ToolError, match="working folder"):
        run(pjt.delegate(manager, CALLER, {"command": "x", "folder": "../elsewhere"}))
    sub = tmp / "web"
    sub.mkdir()
    run(pjt.delegate(manager, CALLER, {"command": "x", "folder": "web"}))
    assert eng.names("propose")[-1][1].folder == f"{tmp}/web"
    eng.put(JobState.RUNNING, "job_00000000000a").caller_session = "uuid-other"
    for tool in (pjt.job_wait, pjt.job_stop):
        with pytest.raises(ToolError, match="not a job you started"):
            run(tool(manager, CALLER, {"job_id": "job_00000000000a"}))
    assert not eng.names("stop")


def test_shapes(world, monkeypatch):
    land = json.dumps({"applied": ["a.py"], "deleted": [], "clashes": [], "ref": None})
    done = JobRecord(id="job_1", state=JobState.DONE, peer_label="tower", exit_code=0, started_at=10.0, ended_at=51.0, land_json=land,
                     output_tail=f"ok \x1b[31mred\x1b[0m token {FAKE_SECRET}")
    out = pjt.agent_result(done)
    assert out["status"] == "done" and out["seconds"] == 41 and out["applied"] == ["a.py"] and "\x1b" not in out["output_tail"]
    assert FAKE_SECRET not in out["output_tail"] and "token " in out["output_tail"]
    capped = JobRecord(id="job_1", state=JobState.DONE, exit_code=124, started_at=1.0, ended_at=2.0)
    assert pjt.agent_result(capped)["detail"] == "time cap"
    clash = JobRecord(id="job_1", state=JobState.DONE, peer_label="tower", exit_code=1, started_at=1.0, ended_at=2.0, snapshot_commit="abc",
                      land_json=json.dumps({"applied": [], "clashes": ["x.py"], "ref": "refs/carnivore/jobs/job_1"}))
    texts = {}
    for armed in (True, False):
        monkeypatch.setattr(beast_mode, "beast_enabled", lambda armed=armed: armed)
        shaped = pjt.agent_result(clash)
        assert shaped["clashes"] == ["x.py"] and shaped["ref"] == "refs/carnivore/jobs/job_1" and shaped["base"] == "abc"
        assert "applied" not in shaped
        texts[armed] = shaped["todo"]
    assert texts[True] != texts[False] and "merge" in texts[True] and "tell the owner" in texts[False]
    many = JobRecord(id="job_1", state=JobState.DONE, land_json=json.dumps({"applied": [f"f{i}" for i in range(60)]}))
    shaped = pjt.agent_result(many)
    assert len(shaped["applied"]) == 50 and shaped["applied_more"] == 10
    failed = pjt.agent_result(JobRecord(id="job_1", state=JobState.FAILED, error_code="no_free_slot", error_detail="x" * 500))
    assert failed["reason"] == "no_free_slot" and len(failed["detail"]) == 300
    assert pjt.agent_result(JobRecord(id="job_1", state=JobState.LOST))["status"] == "lost"
    assert pjt.agent_result(JobRecord(id="job_1", state=JobState.STOPPED)) == {"status": "stopped", "job_id": "job_1", "computer": None}
    assert pjt.agent_result(JobRecord(id="job_1", state=JobState.WAITING_APPROVAL))["next"] == "approval_wait"


def test_job_stop_stops_an_own_job(world):
    eng, manager, _ = world
    eng.put(JobState.RUNNING)
    assert _payload(run(pjt.job_stop(manager, CALLER, {"job_id": "job_000000000001"})))["status"] == "stopped"


def test_tools_list_loads_only_delegate_up_front_and_descriptions_fit():
    rows = {r["name"]: r for r in tools.tool_definitions(None) if r["name"] in ("delegate", "job_wait", "job_stop")}
    assert set(rows) == {"delegate", "job_wait", "job_stop"}
    assert rows["delegate"]["_meta"] == {"anthropic/alwaysLoad": True}
    assert "_meta" not in rows["job_wait"] and "_meta" not in rows["job_stop"]
    assert all(len(r["description"]) <= 400 for r in rows.values())
    assert "re-attach" in rows["delegate"]["description"]


def test_from_header_table():
    table = [(None, 50), ("", 50), ("abc", 50), ("0", 50), ("60", 50), ("120", 95), ("900", 600)]
    assert [call_budget.from_header(v) for v, _ in table] == [float(w) for _, w in table]


def test_a_session_without_a_database_record_cannot_use_the_job_tools(world):
    eng, manager, _ = world
    eng.put(JobState.RUNNING).caller_session = None
    infos = asyncio.run(manager.list_session_infos())
    infos[0].session_uuid = None
    for call in (pjt.delegate(manager, CALLER, {"command": "pytest -q"}), pjt.job_wait(manager, CALLER, {"job_id": "job_000000000001"}),
                 pjt.job_stop(manager, CALLER, {"job_id": "job_000000000001"})):
        with pytest.raises(ToolError):
            run(call)
    assert not eng.names("propose") and not eng.names("stop")


def test_a_start_the_host_refused_tells_the_agent_the_hosts_sentence():
    rec = JobRecord(id="job_000000000001", state=JobState.HERE, reason="tower has room", error_detail="tower is busy right now")
    assert pjt.agent_result(rec) == {"decision": "here", "reason": "tower is busy right now"}


def test_stop_of_a_landing_job_says_it_was_refused(world):
    eng, manager, _ = world
    eng.put(JobState.LANDING)

    async def refuse(job_id: str) -> JobRecord:
        return eng.rows[job_id]

    eng.stop = refuse  # type: ignore[method-assign]
    out = _payload(run(pjt.job_stop(manager, CALLER, {"job_id": "job_000000000001"})))
    assert out["status"] == "running" and "stop refused" in out["note"]


def test_beast_mode_can_skip_the_delegate_card():
    assert beast_mode.eligible_action("delegate") and "delegate" in tools.GATED_TOOLS
    assert not beast_mode.eligible_action("session_delete")


def test_a_reattached_running_job_neither_parks_nor_proceeds(world):
    eng, manager, _ = world
    eng.next_state = JobState.RUNNING
    out = _payload(run(pjt.delegate(manager, CALLER, {"command": "pytest -q"})))
    assert out["status"] == "running" and pending.get_store().list() == [] and not eng.names("proceed")
