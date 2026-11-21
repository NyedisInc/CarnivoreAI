
from __future__ import annotations

import asyncio
import dataclasses
import json
import sqlite3
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

from src.core.pack.jobs import agent_facts, engine as engine_mod, engine_agent, paths, tell
from src.core.pack.jobs.agent_types import CAP_AGENT, UsageTotals
from src.core.pack.jobs.engine import Engine, idem_key
from src.core.pack.jobs.engine_agent import AgentRequest
from src.core.pack.jobs.place import PlaceView
from src.core.pack.jobs.store import JobStore
from src.core.pack.jobs.types import (AdmitBody, CollectAnswer, HostState, JobError, JobRecord, JobRequest, JobState, PlaceAnswer,
                                      Snapshot, StatusAnswer)

UID = "uid-test-0001"


class FakeTarget:

    install_id, label = "iid-b", "b"

    def __init__(self) -> None:
        self.statuses: List[StatusAnswer] = []
        self.admitted: List[AdmitBody] = []
        self.replies: List[Any] = []

    async def admit(self, body: AdmitBody) -> None:
        self.admitted.append(body)

    async def status_full(self, job_id: str) -> StatusAnswer:
        return self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]

    async def reply(self, body: Any) -> None:
        self.replies.append(body)


def running(**kw: Any) -> StatusAnswer:
    return StatusAnswer(state=HostState.RUNNING, **kw)


def parked(question: str, kind: str = "question") -> StatusAnswer:
    return StatusAnswer(state=HostState.PARKED, question=question, question_kind=kind)


@pytest.fixture()
def rig(tmp_path):
    target, notices = FakeTarget(), []

    async def notifier(_store: Any, rec: JobRecord, token: str) -> bool:
        notices.append((rec.id, token))
        return True

    async def facts(_session: Optional[str]) -> agent_facts.CallerFacts:
        return agent_facts.CallerFacts("claude", "work", "bypassPermissions", "opus-x", None)

    async def no_sleep(_s: float) -> None:
        await asyncio.sleep(0)

    state, jobs = tmp_path / "state", tmp_path / "jobs"
    state.mkdir()
    jobs.mkdir()
    eng = Engine(state_dir=state, jobs_root=jobs, install_id="iid-a", target_for=lambda _i: target, sleep=no_sleep,
                 open_db=lambda: sqlite3.connect(":memory:"), facts_for=facts, notifier=notifier)
    eng.target, eng.notices = target, notices  # type: ignore[attr-defined]
    return eng


def seed(eng: Engine, state: JobState = JobState.RUNNING, *, body: str = "agent", caller: Optional[str] = "ses_caller", **cols: Any) -> JobRecord:
    now = 1_000_000.0
    job_id = paths.new_job_id()
    return eng.store.create_job(JobRecord(id=job_id, idem_key=job_id, project_uid=UID, project_name="app", caller_session=caller, state=state,
                                          peer_install_id="iid-b", peer_label="b", body=body, created_at=now, updated_at=now, started_at=now, **cols))




def test_the_plan_mode_maps_to_default_and_a_bypass_stays_a_bypass() -> None:
    assert agent_facts.map_claude_mode("plan") == "default"
    assert agent_facts.map_claude_mode("bypassPermissions") == "bypassPermissions"
    assert agent_facts.map_claude_mode("acceptEdits") == "acceptEdits"
    assert agent_facts.map_claude_mode(None) == "default" and agent_facts.map_claude_mode("weird") == "default"


def test_the_newest_mode_and_model_come_from_the_end_of_the_transcript(tmp_path: Path) -> None:
    lines = [{"type": "user", "permissionMode": "default"}, {"type": "assistant", "message": {"model": "old-model"}},
             {"type": "permission-mode", "permissionMode": "acceptEdits"}, {"type": "assistant", "message": {"model": "new-model"}}]
    path = tmp_path / "t.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in lines) + "\n{torn")
    assert agent_facts.newest_permission_mode(path) == ("acceptEdits", "new-model")
    assert agent_facts.newest_permission_mode(tmp_path / "missing.jsonl") == (None, None)




def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "app"
    (repo / ".claude" / "agents").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    return repo


def test_a_definition_is_read_project_first_then_the_profile_then_home_and_loses_hooks_and_servers(tmp_path: Path) -> None:
    repo, profile, home = _repo(tmp_path), tmp_path / "profile", tmp_path / "home"
    (profile / "agents").mkdir(parents=True)
    (home / ".claude" / "agents").mkdir(parents=True)
    (home / ".claude" / "agents" / "rev.md").write_text("---\ndescription: home\n---\nhome body")
    (profile / "agents" / "rev.md").write_text("---\ndescription: profile\n---\nprofile body")
    got = agent_facts.read_definition(str(repo), "rev", profile_dir=str(profile), home=home)
    assert json.loads(got.definition_json)["description"] == "profile"
    (repo / ".claude" / "agents" / "rev.md").write_text(
        "---\nname: rev\ndescription: project\ntools: Read, Grep\nmodel: opus\npermissionMode: bypassPermissions\nhooks: x\nmcpServers: y\n---\nproject body")
    got = agent_facts.read_definition(str(repo), "rev", profile_dir=str(profile), home=home)
    obj = json.loads(got.definition_json)
    assert obj == {"description": "project", "prompt": "project body", "tools": ["Read", "Grep"], "model": "opus"}
    assert got.model == "opus" and got.body == "project body"


def test_an_unknown_agent_type_is_refused_and_says_where_it_looked(tmp_path: Path) -> None:
    repo, profile = _repo(tmp_path), tmp_path / "profile"
    with pytest.raises(JobError) as err:
        agent_facts.read_definition(str(repo), "ghost", profile_dir=str(profile), home=tmp_path / "home")
    assert err.value.code == "unknown_agent_type"
    for place in (repo / ".claude" / "agents" / "ghost.md", profile / "agents" / "ghost.md", tmp_path / "home" / ".claude" / "agents" / "ghost.md"):
        assert str(place) in err.value.detail
    with pytest.raises(JobError) as bad:
        agent_facts.read_definition(str(repo), "../etc/passwd")
    assert bad.value.code == "bad_request"




def _agent_req(folder: str, task: str = "write the tests", agent_type: Optional[str] = None) -> AgentRequest:
    return AgentRequest(command="", folder=folder, caller_session="ses_caller", task=task, agent_type=agent_type)


def test_the_idempotency_key_covers_the_task_and_the_agent_type_and_leaves_command_jobs_alone() -> None:
    base = idem_key(_agent_req("/w/app"))
    assert base != idem_key(_agent_req("/w/app", task="other")) and base != idem_key(_agent_req("/w/app", agent_type="rev"))
    cmd = JobRequest(command="ls", folder="/w/app")
    assert idem_key(cmd) == idem_key(dataclasses.replace(cmd))
    assert engine_agent.idem_extra(cmd) == []


def test_propose_computes_the_launch_on_the_caller_and_places_only_on_computers_with_the_agent_capability(rig, tmp_path, monkeypatch) -> None:
    repo = _repo(tmp_path)
    (repo / ".claude" / "agents" / "rev.md").write_text("---\ndescription: d\n---\nreview it")
    monkeypatch.setattr(rig, "_resolve_project", lambda folder: ({"uid": UID, "name": "app", "root": str(repo)}, ""))
    peers = [SimpleNamespace(install_id="iid-old", label="old"), SimpleNamespace(install_id="iid-b", label="b")]
    seen: Dict[str, Any] = {}
    view = PlaceView(self_input=SimpleNamespace(install_id="iid-a"), peers=peers, caps={"iid-old": ["pack.jobs"], "iid-b": ["pack.jobs", CAP_AGENT]})
    monkeypatch.setattr(rig, "_view_for", lambda root, uid: view)

    def fake_place(work, uid, pol, v):
        seen["peers"] = [p.install_id for p in v.peers]
        return PlaceAnswer("remote", "iid-b", "b", "room")

    monkeypatch.setattr(engine_mod.place, "place", fake_place)
    snap = Snapshot(commit="a" * 40, tree="b" * 40, head=None, toplevel=str(repo), scope="", side_git_dir="", taken_at=1.0)
    monkeypatch.setattr(engine_mod.snapshot, "take", lambda *a, **k: snap)
    monkeypatch.setattr(engine_mod, "scopes_for", lambda *a, **k: {"replica"})
    rec = asyncio.run(rig.propose(_agent_req(str(repo), agent_type="rev")))
    assert seen["peers"] == ["iid-b"]
    assert (rec.state, rec.body, rec.task_head, rec.agent_type, rec.family, rec.permission_mode) == (
        JobState.WAITING_APPROVAL, "agent", "write the tests", "rev", "claude", "bypassPermissions")
    assert (rig.target.admitted[0].agent_family, rig.target.admitted[0].account_key) == ("claude", "work")
    ctx = engine_mod.engine_run.load_ctx(rec)
    req = engine_mod.engine_run.request_of(ctx)
    assert isinstance(req, AgentRequest) and req.launch["model"] == "opus-x" and json.loads(req.launch["definition_json"])["prompt"] == "review it"
    body = rig._start_body(rec, ctx, "blob-1")
    assert body.command is None and body.agent.task == "write the tests" and body.agent.permission_mode == "bypassPermissions"
    assert body.agent.agent_type == "rev" and body.agent.account_key == "work"


def test_an_unknown_agent_type_starts_nothing(rig, tmp_path, monkeypatch) -> None:
    repo = _repo(tmp_path)
    monkeypatch.setattr(agent_facts.Path, "home", classmethod(lambda cls: tmp_path / "nohome"))
    with pytest.raises(JobError) as err:
        asyncio.run(rig.propose(_agent_req(str(repo), agent_type="ghost")))
    assert err.value.code == "unknown_agent_type" and rig.store.list_jobs() == [] and rig.target.admitted == []


def test_an_engine_without_a_facts_reader_refuses_agent_jobs(tmp_path) -> None:
    eng = Engine(state_dir=tmp_path, jobs_root=tmp_path, install_id="iid-a", open_db=lambda: None)  # type: ignore[arg-type]
    with pytest.raises(JobError) as err:
        asyncio.run(eng.propose(_agent_req(str(tmp_path))))
    assert err.value.code == "agent_jobs_unavailable"




def test_a_parked_worker_becomes_a_question_the_caller_answers_and_a_new_question_is_announced_again(rig) -> None:
    rec = seed(rig)
    rig.target.statuses = [parked("Which database?"), running(account_label="work", account_how="relay", usage=UsageTotals(input_tokens=5)),
                           parked("Which port?"), StatusAnswer(state=HostState.EXITED, exit_code=0)]
    states: List[str] = []

    async def drive() -> bool:
        async def sleep(_s: float) -> None:
            row = rig.store.get_job(rec.id)
            states.append(row.state.value)
            if row.state == JobState.QUESTION and row.question == "Which database?":
                after = await rig.reply(rec.id, "use sqlite", "ses_caller")
                assert after.state == JobState.RUNNING and after.question is None
            await asyncio.sleep(0)

        rig._sleep = sleep
        done = await rig._poll_agent(rig.store.get_job(rec.id))
        await asyncio.sleep(0.01)
        return done

    assert asyncio.run(drive()) is True
    assert states[0] == "question" and "running" in states and states[-1] == "question"
    row = rig.store.get_job(rec.id)
    assert row.state == JobState.COLLECTING and (row.account_label, row.account_how) == ("work", "relay")
    assert json.loads(row.usage_json)["input_tokens"] == 5
    assert rig.target.replies[0].text == "use sqlite"
    assert [t.split(":")[0] for _, t in rig.notices] == ["question", "question"]


def test_a_reply_that_lands_during_a_poll_is_not_reported_as_a_question_again(rig) -> None:
    rec = seed(rig, JobState.QUESTION, question="q?", question_kind="question")
    clock = {"t": 0.0}

    def mono() -> float:
        clock["t"] += 1.0
        return clock["t"]

    rig._mono = mono
    seen: List[str] = []
    calls = {"n": 0}

    async def status_full(_job_id: str) -> StatusAnswer:
        calls["n"] += 1
        if calls["n"] == 1:
            await rig.reply(rec.id, "yes", "ses_caller")
            return parked("q?")
        return StatusAnswer(state=HostState.EXITED, exit_code=0)

    rig.target.status_full = status_full

    async def sleep(_s: float) -> None:
        seen.append(rig.store.get_job(rec.id).state.value)
        await asyncio.sleep(0)

    rig._sleep = sleep
    assert asyncio.run(rig._poll_agent(rig.store.get_job(rec.id))) is True
    assert seen[0] == "running", seen


def test_a_target_alternating_two_questions_gets_one_message_not_one_per_poll(rig) -> None:
    rec = seed(rig)
    sent: List[str] = []

    async def mine(_app: Any, _sid: str) -> tell.Receiver:
        return tell.Receiver("ses_caller", "uuid-a", "uuid-a", 1)

    async def notifier(store: Any, row: JobRecord, token: str) -> bool:
        return await tell.notify_caller(None, store, row, token, resolve=mine, queue=lambda r, t: sent.append(t) or "m", wake=lambda a, k: None)

    rig._notifier = notifier
    rig.target.statuses = [parked("A?") if i % 2 == 0 else parked("B?") for i in range(20)] + [StatusAnswer(state=HostState.EXITED, exit_code=0)]

    async def drive() -> None:
        await rig._poll_agent(rig.store.get_job(rec.id))
        await asyncio.sleep(0.05)

    asyncio.run(drive())
    assert len(sent) == 1, sent


def test_a_reply_for_a_question_that_has_since_changed_is_refused(rig) -> None:
    rec = seed(rig, JobState.QUESTION, question="may I run the tests?", question_kind="question")
    shown = engine_agent.digest_of(rec.question)
    rig.store.set_state(rec.id, JobState.QUESTION, question="may I drop the staging database?", question_kind="question")
    with pytest.raises(JobError) as err:
        asyncio.run(rig.reply(rec.id, "yes", "ses_caller", shown))
    assert err.value.code == "question_changed" and rig.target.replies == []
    assert asyncio.run(rig.reply(rec.id, "no", "ses_caller", engine_agent.digest_of("may I drop the staging database?"))).state == JobState.RUNNING


def test_reply_refuses_everyone_but_the_owner_and_every_state_but_a_question(rig) -> None:
    asking = seed(rig, JobState.QUESTION, question="q?", question_kind="question")
    cases = [(asking.id, "ses_other", "not_your_job"), (seed(rig, body="command").id, "ses_caller", "not_an_agent_job"),
             (seed(rig, JobState.RUNNING).id, "ses_caller", "not_asking"),
             (seed(rig, JobState.QUESTION, question="allow?", question_kind="permission").id, "ses_caller", "owner_only"),
             (seed(rig, JobState.QUESTION, question="trust?", question_kind="startup").id, "ses_caller", "owner_only"),
             ("job_0123456789ab", "ses_caller", "unknown_job")]
    for job_id, caller, code in cases:
        with pytest.raises(JobError) as err:
            asyncio.run(rig.reply(job_id, "yes", caller))
        assert err.value.code == code, (job_id, code)
    assert rig.target.replies == []
    with pytest.raises(JobError) as bad:
        asyncio.run(rig.reply(asking.id, "x\0y", "ses_caller"))
    assert bad.value.code == "bad_request"


def test_wait_returns_at_once_on_a_question(rig) -> None:
    rec = seed(rig, JobState.QUESTION, question="q?", question_kind="question")
    assert asyncio.run(rig.wait(rec.id, 60)).state == JobState.QUESTION




def test_no_message_while_a_caller_holds_and_one_after_it_leaves(rig) -> None:
    rec = seed(rig)

    async def go() -> None:
        rig.waiter_enter(rec.id)
        rig.waiter_enter(rec.id)
        rig._notify_soon(rec.id, "question:aa")
        rig.waiter_leave(rec.id)
        rig._notify_soon(rec.id, "question:bb")
        rig.waiter_leave(rec.id)
        assert rig._waiters == {} and rig.notices == []
        rig._end(rec.id, JobState.DONE, detail="done")
        rig._end(rec.id, JobState.FAILED, code="x", detail="late")
        await asyncio.sleep(0.01)

    asyncio.run(go())
    assert rig.notices == [(rec.id, "done")]


def test_wait_counts_as_holding_while_it_runs(rig) -> None:
    rec = seed(rig)

    async def go() -> int:
        task = asyncio.ensure_future(rig.wait(rec.id, 60))
        await asyncio.sleep(0.01)
        held = rig._waiters.get(rec.id, 0)
        rig._end(rec.id, JobState.DONE, detail="done")
        await task
        await asyncio.sleep(0.01)
        return held

    assert asyncio.run(go()) == 1 and rig._waiters == {} and rig.notices == []


def test_stopped_and_here_jobs_send_no_message(rig) -> None:
    stopped = seed(rig)

    async def go() -> None:
        rig._end(stopped.id, JobState.STOPPED, code="stopped", detail="stopped by the asker")
        await asyncio.sleep(0.01)

    asyncio.run(go())
    assert rig.notices == []




def test_the_receiver_must_be_the_jobs_caller_session() -> None:
    mine = tell.Receiver("ses_a", "u-a", "u-a", 1)
    assert tell.check_receiver("ses_a", mine) is mine and tell.check_receiver("u-a", mine) is mine
    for caller, rcv in (("ses_a", tell.Receiver("ses_b", "u-b", "u-b", 1)), ("ses_a", None), (None, mine), ("", mine)):
        with pytest.raises(tell.TellRefused):
            tell.check_receiver(caller, rcv)


def test_notify_caller_writes_nothing_for_another_session_and_only_once_per_state(tmp_path) -> None:
    store = JobStore(tmp_path)
    job = store.create_job(JobRecord(id="job_0123456789ab", caller_session="ses_a", state=JobState.DONE, peer_label="tower", body="agent"))
    queued: List[Any] = []
    woke: List[str] = []

    async def other(_app: Any, _sid: str) -> tell.Receiver:
        return tell.Receiver("ses_b", "u-b", "u-b", 1)

    async def mine(_app: Any, _sid: str) -> tell.Receiver:
        return tell.Receiver("ses_a", "u-a", "u-a", 1)

    def queue(rcv: tell.Receiver, text: str) -> str:
        queued.append((rcv.id, text))
        return "m-1"

    async def go() -> List[bool]:
        refused = await tell.notify_caller(None, store, job, "done", resolve=other, queue=queue, wake=lambda a, k: woke.append(k))
        sent = await tell.notify_caller(None, store, job, "failed", resolve=mine, queue=queue, wake=lambda a, k: woke.append(k))
        again = await tell.notify_caller(None, store, job, "failed", resolve=mine, queue=queue, wake=lambda a, k: woke.append(k))
        after_restart = await tell.notify_caller(None, JobStore(tmp_path), job, "failed", resolve=mine, queue=queue, wake=lambda a, k: woke.append(k))
        return [refused, sent, again, after_restart]

    assert asyncio.run(go()) == [False, True, False, False]
    assert len(queued) == 1 and queued[0][0] == "ses_a" and woke == ["u-a"]
    assert queued[0][1] == 'job job_0123456789ab on tower failed. No result came back: job_wait("job_0123456789ab") says why.'
    assert "stop" not in queued[0][1] and "wait for" not in queued[0][1]


def test_a_command_job_without_a_caller_session_is_not_announced(tmp_path) -> None:
    store = JobStore(tmp_path)
    job = store.create_job(JobRecord(id="job_0123456789ab", caller_session=None, state=JobState.DONE))
    assert asyncio.run(tell.notify_caller(None, store, job, "done")) is False


def test_the_system_row_is_a_real_crosstalk_message_the_dispatcher_can_claim(tmp_path, monkeypatch) -> None:
    from src.core.crosstalk import store
    from src.core.db_steps import STEPS

    def connect() -> sqlite3.Connection:
        conn = sqlite3.connect(tmp_path / "cloude.db", isolation_level=None)
        conn.row_factory = sqlite3.Row
        return conn

    with connect() as conn:
        STEPS[56](conn)
        STEPS[89](conn)
        STEPS[93](conn)
    monkeypatch.setattr(store, "_conn", connect)
    monkeypatch.setattr(store, "_notify", lambda: None)
    message_id = tell.queue_notice(tell.Receiver("ses_a", "u-a", "u-a", 7), "job x finished")
    assert store.claim_for("u-other") is None
    row = store.claim_for("u-a")
    assert row["id"] == message_id and row["source"] == "system" and row["text"] == "job x finished" and row["receiver_epoch"] == 7
