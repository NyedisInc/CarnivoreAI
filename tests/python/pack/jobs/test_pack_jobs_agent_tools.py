
from __future__ import annotations

import asyncio
import dataclasses
import json
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import federation_pack_jobs_routes as fed
from src.api import peer_auth
from src.core.mcp import call_budget, instructions, pending, tools
from src.core.mcp import pack_jobs_reply_tools as reply_tools
from src.core.mcp import pack_jobs_tools as pjt
from src.core.mcp.caller import AgentCaller
from src.core.mcp.common import ToolError
from src.core.pack.jobs.engine_agent import AgentRequest, digest_of
from src.core.pack.jobs.store import JobStore
from src.core.pack.jobs.types import HostJob, HostState, JobError, JobRecord, JobState
from tests.python.pack.jobs.test_pack_jobs_surface import CALLER, FakeEngine, _payload, run, world  # noqa: F401

JOB = "job_000000000001"


class AgentEngine(FakeEngine):

    async def reply(self, job_id: str, text: str, caller_session: Any, question_digest: Any = None) -> JobRecord:
        self.calls.append(("reply", job_id, text, caller_session))
        self.digests = [*getattr(self, "digests", []), question_digest]
        self.rows[job_id].state = JobState.RUNNING
        return self.rows[job_id]


@pytest.fixture()
def agent_world(world, monkeypatch):  # noqa: F811
    _, manager, tmp = world
    eng = AgentEngine()
    monkeypatch.setattr(pjt.boot, "engine", lambda: eng)
    monkeypatch.setattr(pjt.boot, "host", lambda: SimpleNamespace(store=JobStore(tmp / "jobs")))
    return eng, manager, tmp


def test_both_forms_and_neither_are_refused(agent_world):
    _, manager, _ = agent_world
    for args in ({"command": "pytest", "task": "do it"}, {}, {"agent_type": "reviewer"}):
        with pytest.raises(ToolError, match="exactly one"):
            run(pjt.delegate(manager, CALLER, args))
    with pytest.raises(ToolError, match="unknown argument"):
        run(pjt.delegate(manager, CALLER, {"task": "x", "bogus": 1}))
    for bad in ({"task": "  "}, {"task": "x" * 19001}, {"task": "x", "agent_type": "Bad Name"}, {"task": "x", "time_cap_minutes": 0},
                {"task": "x", "kind": "nope"}):
        with pytest.raises(ToolError):
            run(pjt.delegate(manager, CALLER, bad))


def test_the_task_form_builds_an_agent_request_and_the_card_shows_the_whole_task(agent_world):
    eng, manager, _ = agent_world
    task = "fix the retry path\nthen run the tests " + "y" * 300

    async def propose(req: Any) -> JobRecord:
        eng.calls.append(("propose", req))
        rec = eng.put(JobState.WAITING_APPROVAL, family="claude", permission_mode="bypassPermissions", agent_type="reviewer")
        rec.caller_session = req.caller_session
        req.launch = {"family": "claude", "permission_mode": "bypassPermissions", "model": "m1", "task": task}
        rec.request_json = json.dumps({"request": dataclasses.asdict(req)})
        return rec

    eng.propose = propose
    out = _payload(run(pjt.delegate(manager, CALLER, {"task": task, "agent_type": "reviewer", "time_cap_minutes": 30})))
    req = eng.names("propose")[0][1]
    assert isinstance(req, AgentRequest) and req.task == task and req.agent_type == "reviewer" and req.command == "" and req.time_cap_s == 1800
    assert req.caller_session == "uuid-a" and req.kind == "suite"
    assert out["status"] == "pending" and out["job_id"] == JOB
    item = pending.get_store().list()[0]
    assert item["args"]["task"] == task
    shown = item["display"]
    assert shown["consequences"][2]["key"] == "delegate_mode_bypass" and len(shown["consequences"]) == 3
    assert {r["key"]: r["value"] for r in shown["detail"]}["task"] == task

    async def again(req: Any) -> JobRecord:
        eng.calls.append(("propose", req))
        return eng.rows[JOB]

    eng.propose = again
    out2 = _payload(run(pjt.delegate(manager, CALLER, {"task": task, "agent_type": "reviewer", "time_cap_minutes": 30})))
    assert out2["status"] == "pending" and len(pending.get_store().list()) == 1
    assert pending.get_store().list()[0]["display"]["consequences"][2]["key"] == "delegate_mode_bypass"


def test_a_job_worker_may_not_delegate_by_session_id_or_by_uuid(agent_world):
    _, manager, tmp = agent_world
    store = JobStore(tmp / "jobs")
    store.host_put(HostJob(job_id=JOB, state=HostState.RUNNING, body="agent", worker_session_id="ses_a", worker_session_uuid="other-uuid"))
    for args in ({"task": "again"}, {"command": "pytest -q"}):
        out = _payload(run(pjt.delegate(manager, CALLER, args)))
        assert out == {"decision": "here", "reason": pjt.WORKER_REFUSAL}
    assert pending.get_store().list() == []
    store.host_set(JOB, state=HostState.EXITED)
    assert pjt.worker_refusal(SimpleNamespace(session=SimpleNamespace(id="ses_a"), session_uuid="uuid-a")) is None
    store.host_put(HostJob(job_id="job_000000000009", state=HostState.RUNNING, body="agent", worker_session_id="ses_zzz", worker_session_uuid="uuid-a"))
    assert pjt.worker_refusal(SimpleNamespace(session=SimpleNamespace(id="ses_other"), session_uuid="uuid-a")) == pjt.WORKER_REFUSAL
    with pytest.raises(ToolError, match="job worker"):
        run(reply_tools.job_reply(manager, CALLER, {"job_id": JOB, "text": "yes"}))


def test_the_worker_refusal_reads_the_servers_table_not_the_arguments(agent_world):
    _, manager, _ = agent_world
    out = _payload(run(pjt.delegate(manager, CALLER, {"task": "x"})))
    assert out["status"] == "pending"
    with pytest.raises(ToolError, match="unknown argument"):
        run(pjt.delegate(manager, CALLER, {"task": "x", "is_worker": False}))


def test_the_waits_count_as_a_waiter_and_the_running_answer_never_says_to_stop(agent_world):
    eng, manager, _ = agent_world
    eng.put(JobState.RUNNING)
    out = _payload(run(pjt.job_wait(manager, CALLER, {"job_id": JOB})))
    assert [c[0] for c in eng.calls if c[0].startswith("waiter") or c[0] == "wait"] == ["waiter_enter", "wait", "waiter_leave"]
    note = out["note"]
    assert note.index("call job_wait again") < note.index("sub-agent") < note.index("other work") < note.index("one message")
    assert "stop" not in note.lower() and "end your turn" not in note.lower()
    eng.calls.clear()
    eng.next_state = JobState.RUNNING
    run(pjt.delegate(manager, CALLER, {"command": "pytest -q"}))
    assert "waiter_enter" in [c[0] for c in eng.calls] and eng.calls[-1][0] == "waiter_leave"


def test_the_question_and_the_done_shapes():
    ask = pjt.agent_result(JobRecord(id="j", state=JobState.QUESTION, peer_label="tower", body="agent", question="which db?", question_kind="question"))
    assert ask["status"] == "question" and ask["question"] == "which db?" and ask["next"] == "job_reply"
    owner = pjt.agent_result(JobRecord(id="j", state=JobState.QUESTION, question="trust?", question_kind="startup"))
    assert owner["next"] == "owner" and "job_reply" not in owner["note"].split(";")[0]
    done = pjt.agent_result(JobRecord(id="j", state=JobState.DONE, body="agent", exit_code=0, started_at=1.0, ended_at=3.0, result_text="all fixed",
                                      usage_json=json.dumps({"input_tokens": 5, "output_tokens": 7}), account_label="work", account_how="relay"))
    assert done["result_text"] == "all fixed" and done["usage"]["output_tokens"] == 7 and done["account"] == {"label": "work", "how": "relay", "words": "the relay copy of the caller's login"}
    plain = pjt.agent_result(JobRecord(id="j", state=JobState.DONE, exit_code=0, started_at=1.0, ended_at=3.0))
    assert "result_text" not in plain and "usage" not in plain


def test_job_reply_parks_then_sends_once_the_owner_approves(agent_world):
    eng, manager, _ = agent_world
    eng.put(JobState.QUESTION, body="agent", question="which db?", question_kind="question")
    out = _payload(run(reply_tools.job_reply(manager, CALLER, {"job_id": JOB, "text": "use sqlite"})))
    assert out["status"] == "pending" and not eng.names("reply")
    item = pending.get_store().list()[0]
    assert item["action"] == "job_reply" and item["args"]["text"] == "use sqlite" and item["args"]["question"] == "which db?"

    async def approve() -> dict:
        await pending.get_store().approve(out["id"])
        from src.core.mcp import write_tools
        return _payload(await write_tools.approval_wait(manager, CALLER, {"id": out["id"], "timeout": 1}))

    answer = run(approve())
    assert eng.names("reply") == [("reply", JOB, "use sqlite", "uuid-a")] and answer["status"] == "running"
    assert eng.digests == [digest_of("which db?")]


@pytest.mark.parametrize("state,kind,match", [(JobState.RUNNING, None, "not_asking"), (JobState.QUESTION, "permission", "owner_only"),
                                              (JobState.QUESTION, "startup", "owner_only")])
def test_job_reply_refuses_what_a_caller_may_not_answer(agent_world, state, kind, match):
    eng, manager, _ = agent_world
    eng.put(state, body="agent", question_kind=kind, question="q")
    with pytest.raises(ToolError, match=match):
        run(reply_tools.job_reply(manager, CALLER, {"job_id": JOB, "text": "yes"}))
    assert pending.get_store().list() == []


def test_job_reply_is_for_the_asker_only_and_checks_its_text(agent_world):
    eng, manager, _ = agent_world
    rec = eng.put(JobState.QUESTION, body="agent", question="q", question_kind="question")
    for bad in ("", "x" * 8001, None, "a\0b"):
        with pytest.raises(ToolError, match="text must be"):
            run(reply_tools.job_reply(manager, CALLER, {"job_id": JOB, "text": bad}))
    rec.caller_session = "someone-else"
    with pytest.raises(ToolError, match="not a job you started"):
        run(reply_tools.job_reply(manager, CALLER, {"job_id": JOB, "text": "yes"}))
    with pytest.raises(ToolError, match="unknown argument"):
        run(reply_tools.job_reply(manager, CALLER, {"job_id": JOB, "text": "yes", "x": 1}))


def test_descriptions_fit_and_only_delegate_always_loads():
    names = ("delegate", "job_wait", "job_stop", "job_reply")
    rows = {r["name"]: r for r in tools.tool_definitions(None) if r["name"] in names}
    assert set(rows) == set(names) and all(len(r["description"]) <= 400 for r in rows.values())
    assert [n for n, r in rows.items() if "_meta" in r] == ["delegate"]
    text = " ".join(r["description"] + json.dumps(r["inputSchema"]) for r in rows.values()).lower()
    assert "cannot push" not in text and "can't push" not in text and "sandbox" in rows["delegate"]["description"]
    assert "595" in rows["job_wait"]["description"] and "sub-agent" in rows["job_wait"]["description"]
    assert rows["job_wait"]["inputSchema"]["properties"]["timeout"]["maximum"] == 595
    assert rows["delegate"]["inputSchema"].get("required", []) == []


def test_the_guide_keeps_the_task_line_inside_the_cap_and_drops_it_for_a_worker(monkeypatch, agent_world):
    from src.core.mcp import agent_tool_switches

    monkeypatch.setattr(agent_tool_switches, "current", lambda: agent_tool_switches.AgentToolSwitches(huddle=True, swarm=True, pack=True))
    pane = AgentCaller("ses_a", "tmux_a", "ses_a")
    text = instructions.guide(pane)
    assert "job_reply" in text and "agent task" in text and len(text) <= instructions.MAX_CHARS
    _, _, tmp = agent_world
    JobStore(tmp / "jobs").host_put(HostJob(job_id=JOB, state=HostState.RUNNING, body="agent", worker_session_id="ses_a"))
    assert "delegate" not in instructions.guide(pane)
    token = AgentCaller("mcp-token:1", "", "mcp-token:1", token_name="t")
    assert "delegate" in instructions.guide(token)


def test_a_client_that_declares_900_waits_up_to_595(agent_world):
    eng, manager, _ = agent_world
    eng.put(JobState.RUNNING)
    with call_budget.using(call_budget.from_header("900")):
        run(pjt.job_wait(manager, CALLER, {"job_id": JOB, "timeout": 595}))
    assert eng.names("wait")[-1][2] == 595.0
    with call_budget.using(call_budget.from_header("120")):
        run(pjt.job_wait(manager, CALLER, {"job_id": JOB, "timeout": 595}))
    assert eng.names("wait")[-1][2] == 90.0


class _Host:

    def __init__(self) -> None:
        self.seen: list = []

    async def reply(self, caller: str, body: Any) -> dict:
        self.seen.append((caller, body.job_id, body.text))
        if body.text == "refuse":
            raise JobError("owner_only", "not yours", 409)
        return {"ok": True}


def _client(host: Any, peer: bool = True) -> TestClient:
    app = FastAPI()
    app.include_router(fed.router, prefix="/api/v1")
    principal = peer_auth.Principal("peer", SimpleNamespace(peer_install_id="iid-a")) if peer else peer_auth.OWNER
    app.dependency_overrides[fed._require_replica] = lambda: principal
    app.state.pack_jobs_host = host
    return TestClient(app)


def test_the_peer_reply_route_runs_the_host_gate_for_the_calling_peer():
    host = _Host()
    c = _client(host)
    assert c.post("/api/v1/federation/pack/jobs/reply", json={"job_id": JOB, "text": "yes"}).json() == {"ok": True}
    assert host.seen == [("iid-a", JOB, "yes")]
    bad = c.post("/api/v1/federation/pack/jobs/reply", json={"job_id": JOB, "text": "refuse"})
    assert bad.status_code == 409 and bad.json()["detail"]["code"] == "owner_only"
    assert c.post("/api/v1/federation/pack/jobs/reply", json={"job_id": "nope", "text": "x"}).status_code == 422
    assert c.post("/api/v1/federation/pack/jobs/reply", json={"job_id": JOB, "text": "x", "extra": 1}).status_code == 422
    assert _client(host, peer=False).post("/api/v1/federation/pack/jobs/reply", json={"job_id": JOB, "text": "x"}).status_code == 403
    assert _client(None).post("/api/v1/federation/pack/jobs/reply", json={"job_id": JOB, "text": "x"}).status_code == 503


def test_the_agent_capability_is_advertised():
    from src.core.pack.machines import capabilities

    assert "pack.jobs.agent" in capabilities.names()
