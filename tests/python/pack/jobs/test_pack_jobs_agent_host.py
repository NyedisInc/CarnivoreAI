
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional

import pytest

pytest.importorskip("fastapi")

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from test_pack_jobs_host import make_snapshot, start_body, world  # noqa: E402,F401

from src.core.attention import evidence as ev  # noqa: E402
from src.core.pack.jobs import agent_launch, agent_watch, paths  # noqa: E402
from src.core.pack.jobs.agent_account import AccountPick  # noqa: E402
from src.core.pack.jobs.agent_host import GONE_DETAIL, AgentDeps  # noqa: E402
from src.core.pack.jobs.agent_types import UsageTotals  # noqa: E402
from src.core.pack.jobs.types import HostState, JobError, JobIdBody, ReplyBody, StartBody  # noqa: E402

LIVE = (HostState.RUNNING, HostState.PARKED, HostState.PREPARING)
T0 = 1_800_000_000.0


def look(state: str, reason: str, *, dialog: Any = None, screen: Any = None) -> Any:
    return SimpleNamespace(verdict=ev.AttentionVerdict(state, reason, ev.TIER_REGISTRY, detail="the worker asks something"),
                           evidence=SimpleNamespace(dialog=dialog, startup_screen=screen), cycle=0, stale=False)


def later(obs: Any, cycle: int) -> Any:
    return SimpleNamespace(**{**vars(obs), "cycle": cycle})


BUSY, DONE = look(ev.STATE_BUSY, ev.REASON_TOOL), look(ev.STATE_DONE_IDLE, ev.REASON_TURN_ENDED)
UNKNOWN = look(ev.STATE_UNKNOWN, ev.REASON_NO_EVIDENCE)
DEAD = look(ev.STATE_UNKNOWN, ev.REASON_PANE_DEAD)


class Sim:

    def __init__(self, w: Any, tmp: Path) -> None:
        self.w, self.tmp = w, tmp
        self.now, self.tick, self.obs = T0, 0, BUSY
        self.read = agent_watch.Read(None, None)
        self.script: Dict[int, Callable[[], None]] = {}
        self.created: List[Dict[str, Any]] = []
        self.stopped: List[str] = []
        self.typed: List[str] = []
        self.delivered: List[str] = []
        self.after_escape: Any = None
        self.harness, self.listed, self.order_ok, self.present = True, True, [], False
        self.usage = UsageTotals(input_tokens=11, output_tokens=22, cache_read_tokens=3, cache_write_tokens=4, cost_usd=0.5)
        self.conv_calls: List[str] = []
        self.on_sleep: Optional[Callable[["Sim"], None]] = None
        w.host._clock = lambda: self.now
        w.host.agent.bind(self.deps())

    def deps(self) -> AgentDeps:
        async def create(plan: Any, session_id: str, label: str, working_dir: str) -> agent_launch.WorkerRef:
            row = self.w.host.store.host_get(self.job_id)
            self.order_ok.append(row is not None and row.worker_session_id == session_id and row.state == HostState.PREPARING)
            self.created.append({"plan": plan, "session_id": session_id, "label": label, "dir": working_dir,
                                 "task_file": (Path(working_dir) / agent_launch.TASK_DIR / agent_launch.TASK_FILE).read_text()})
            (Path(working_dir) / "worker-out.txt").write_text("done by the worker\n")
            return agent_launch.WorkerRef(session_id, "uuid-" + session_id, "carnivore_" + session_id, 1)

        async def stop(session_id: str, session_uuid: Optional[str] = None) -> None:
            self.stopped.append(session_id)

        async def send_input(session_id: str, data: str) -> None:
            self.typed.append(data)
            if data == "\x1b":
                self.obs = later(self.after_escape or DONE, (self.obs.cycle if self.obs is not None else 0) + 1)

        async def deliver(session_id: str, text: str) -> None:
            self.delivered.append(text)

        async def present(tmux_name: str) -> bool:
            return self.present

        async def listed(session_id: str) -> bool:
            return self.listed

        async def conversation(session_id: str) -> Any:
            self.conv_calls.append(session_id)
            return "conv-1", str(self.tmp)

        async def sleep(seconds: float) -> None:
            self.tick += 1
            self.now += seconds
            if self.on_sleep is not None:
                self.on_sleep(self)
            self.script.get(self.tick, lambda: None)()
            await asyncio.sleep(0.001)

        return AgentDeps(create, stop, lambda sid: self.obs, send_input, listed, conversation,
                         lambda family, key, caller, ident=None: AccountPick("acct", {"CLAUDE_CONFIG_DIR": str(self.tmp / "relay")}, "work", "relay"),
                         deliver=deliver, present=present, harness_present=lambda family: self.harness, transcript_reader=lambda *a: self.read, usage_reader=lambda *a: self.usage,
                         sleep=sleep, poll_s=2.0)

    def body(self, **spec: Any) -> StartBody:
        self.job_id = paths.new_job_id()
        snap = make_snapshot(self.w, self.job_id)
        data = start_body(self.w, self.job_id, snap, "x", time_cap_s=spec.pop("time_cap_s", 3600))
        data.pop("command")
        data["agent"] = {"task": "write worker-out.txt", "family": "claude", "permission_mode": "default", **spec}
        return StartBody(**data)

    async def start(self, **spec: Any) -> StartBody:
        body = await asyncio.to_thread(self.body, **spec)
        await self.w.host.start("iid-a", body)
        await self.w.host._tasks[body.job_id]
        return body

    def row(self) -> Any:
        return self.w.host.store.host_get(self.job_id)

    async def until(self, pred: Callable[[Any], bool], limit: int = 4000) -> Any:
        for _ in range(limit):
            row = self.row()
            if pred(row):
                return row
            await asyncio.sleep(0.001)
        raise AssertionError(f"never reached: {self.row()} at tick {self.tick}")

    async def ended(self) -> Any:
        return await self.until(lambda r: r.state not in LIVE)

    def finish_text(self, text: str = "all done") -> None:
        self.read = agent_watch.Read(text, self.now + 1)
        self.obs = DONE


@pytest.fixture()
def sim(world, tmp_path):  # noqa: F811
    return Sim(world, tmp_path)


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_row_before_session_and_task_never_on_the_launch(sim) -> None:
    async def go() -> None:
        secret_task = "do the thing TASKTEXT-9f3a1"
        body = await sim.start(task=secret_task)
        made = sim.created[0]
        assert sim.order_ok == [True]
        assert made["task_file"] == secret_task
        plan = made["plan"]
        assert secret_task not in json.dumps([plan.extra_args, plan.extra_env, plan.opening_prompt, made["label"]])
        assert made["label"] == f"job {body.job_id[4:12]}"
        row = sim.row()
        assert row.state == HostState.RUNNING and row.body == "agent" and row.caller_install == "iid-a"
        assert (row.worker_session_id, row.worker_session_uuid) == (made["session_id"], "uuid-" + made["session_id"])
        assert (row.account_label, row.account_how, row.family, row.permission_mode) == ("work", "relay", "claude", "default")
        assert os.path.realpath(made["dir"]).startswith(os.path.realpath(sim.w.host.jobs_root))
        st = await sim.w.host.status("iid-a", JobIdBody(job_id=body.job_id))
        assert st["state"] == "running" and st["account_how"] == "relay" and "result_text" not in st
        sim.finish_text()
        await sim.ended()
    run(go())


def test_finished_needs_two_reads_and_a_new_assistant_record(sim) -> None:
    async def go() -> None:
        body = await sim.start()
        sim.read, sim.obs = agent_watch.Read("an old line", T0 - 50), DONE
        for _ in range(30):
            await asyncio.sleep(0.003)
        assert sim.row().state == HostState.RUNNING and not sim.stopped
        at = sim.tick
        sim.read = agent_watch.Read("all done", sim.now + 1)
        row = await sim.ended()
        assert sim.tick - at <= 6 and (row.state, row.exit_code, row.result_text) == (HostState.EXITED, 0, "all done")
        assert sim.stopped == [row.worker_session_id]
        assert json.loads(row.usage_json)["output_tokens"] == 22
        out = await sim.w.host.collect("iid-a", JobIdBody(job_id=body.job_id))
        assert out["changed"] == 1 and out["result_text"] == "all done" and out["usage"]["input_tokens"] == 11
        assert out["account_how"] == "relay" and out["worker_session_uuid"] == row.worker_session_uuid
        st = await sim.w.host.status("iid-a", JobIdBody(job_id=body.job_id))
        assert st["state"] == "exited" and st["result_text"] == "all done"
    run(go())


def test_result_text_is_redacted_and_capped(sim) -> None:
    async def go() -> None:
        await sim.start()
        key = "sk-ant-api03-" + "A" * 80
        sim.finish_text(f"the key is {key} " + "x" * 40000)
        row = await sim.ended()
        assert key not in row.result_text and "A" * 20 not in row.result_text and len(row.result_text) <= agent_watch.RESULT_MAX
    run(go())


def test_a_credential_in_a_parked_question_is_starred_before_it_leaves(sim) -> None:
    async def go() -> None:
        await sim.start()
        key = "sk-ant-api03-" + "B" * 80
        dialog = SimpleNamespace(question=f"Use this key {key}?", options=("yes", "no"), startup_kind=None)
        sim.obs = look(ev.STATE_NEEDS_USER, ev.REASON_QUESTION, dialog=dialog)
        row = await sim.until(lambda r: r.state == HostState.PARKED)
        assert key not in row.question and "B" * 20 not in row.question and "Use this key" in row.question
        sim.finish_text()
        await sim.ended()
    run(go())


def test_the_usage_is_read_before_the_worker_is_stopped_and_the_task_folder_never_comes_back(sim) -> None:
    async def go() -> None:
        body = await sim.start()
        slot = Path(sim.created[0]["dir"])
        exclude = agent_launch._exclude_file(slot)
        exclude.write_text("")
        order: List[str] = []
        real_usage = sim.w.host.agent.deps.usage_reader
        sim.w.host.agent.deps.usage_reader = lambda *a: (order.append("usage" if not sim.stopped else "usage-after-stop"), real_usage(*a))[1]
        sim.finish_text()
        await sim.ended()
        assert order and order[-1] == "usage" and "usage-after-stop" not in order
        out = await sim.w.host.collect("iid-a", JobIdBody(job_id=body.job_id))
        assert out["changed"] == 1
    run(go())


def test_permission_and_startup_park_for_the_owner_and_reply_refuses(sim) -> None:
    async def go() -> None:
        for kind, obs in (("permission", look(ev.STATE_NEEDS_USER, ev.REASON_PERMISSION)),
                          ("startup", look(ev.STATE_UNKNOWN, ev.REASON_REGISTRY_ABSENT, screen=SimpleNamespace(kind="trust", text="Do you trust this folder?")))):
            sim.stopped.clear()
            body = await sim.start()
            sim.obs = obs
            parked = await sim.until(lambda r: r.state == HostState.PARKED)
            assert parked.question_kind == kind and parked.question
            with pytest.raises(JobError) as err:
                await sim.w.host.reply("iid-a", ReplyBody(job_id=body.job_id, text="yes"))
            assert err.value.code == "owner_only" and sim.typed == []
            st = await sim.w.host.status("iid-a", JobIdBody(job_id=body.job_id))
            assert st["state"] == "parked" and st["question_kind"] == kind
            row = await sim.ended()
            assert (row.state, row.exit_code) == (HostState.EXITED, 1) and kind in row.detail
            assert sim.now - parked.parked_at >= agent_watch.PARK_S and sim.stopped == [row.worker_session_id]
    run(go())


def test_question_parks_reply_resumes_and_ten_minutes_ends_with_the_question(sim) -> None:
    async def go() -> None:
        body = await sim.start()
        dialog = SimpleNamespace(question="Which database?", options=("sqlite", "postgres"), startup_kind=None)
        sim.obs = look(ev.STATE_NEEDS_USER, ev.REASON_QUESTION, dialog=dialog)
        parked = await sim.until(lambda r: r.state == HostState.PARKED)
        assert parked.question_kind == "question" and "Which database?" in parked.question and "postgres" in parked.question
        assert await sim.w.host.reply("iid-a", ReplyBody(job_id=body.job_id, text="use sqlite")) == {"ok": True}
        assert sim.typed == ["\x1b"] and sim.delivered == ["use sqlite"]
        assert sim.row().replied_at == sim.now
        assert sim.row().state == HostState.RUNNING and sim.row().question is None
        sim.obs = look(ev.STATE_NEEDS_USER, ev.REASON_QUESTION, dialog=SimpleNamespace(question="Sure?", options=("y",), startup_kind=None))
        asked = await sim.until(lambda r: r.state == HostState.PARKED)
        row = await sim.ended()
        assert sim.now - asked.parked_at >= agent_watch.PARK_S and (row.exit_code, row.detail, row.question_kind) == (0, "question", "question")
        out = await sim.w.host.collect("iid-a", JobIdBody(job_id=body.job_id))
        assert "Sure?" in out["question"] and out["question_kind"] == "question" and out["changed"] == 1
        with pytest.raises(JobError) as err:
            await sim.w.host.reply("iid-a", ReplyBody(job_id=body.job_id, text="late"))
        assert err.value.code == "not_asking"
    run(go())


def test_reply_refused_when_the_question_does_not_close(sim) -> None:
    async def go() -> None:
        body = await sim.start()
        sim.obs = look(ev.STATE_NEEDS_USER, ev.REASON_PLAN_APPROVAL)
        await sim.until(lambda r: r.state == HostState.PARKED)

        async def stuck(session_id: str, data: str) -> None:
            sim.typed.append(data)

        sim.w.host.agent.deps.send_input = stuck
        with pytest.raises(JobError) as err:
            await sim.w.host.reply("iid-a", ReplyBody(job_id=body.job_id, text="go"))
        assert err.value.code == "worker_not_ready" and sim.typed == ["\x1b"] and sim.row().state == HostState.PARKED
        sim.finish_text()
        await sim.ended()
    run(go())


@pytest.mark.parametrize("after", ["permission", "startup", "none", "stale", "working"])
def test_reply_types_nothing_unless_a_newer_reading_shows_a_resting_prompt(sim, after: str) -> None:
    async def go() -> None:
        body = await sim.start()
        sim.obs = look(ev.STATE_NEEDS_USER, ev.REASON_QUESTION, dialog=SimpleNamespace(question="Which?", options=("a",), startup_kind=None))
        await sim.until(lambda r: r.state == HostState.PARKED)
        shown = {"permission": look(ev.STATE_NEEDS_USER, ev.REASON_PERMISSION), "working": BUSY,
                 "startup": look(ev.STATE_NEEDS_USER, ev.REASON_INPUT, screen=SimpleNamespace(text="trust this folder?")),
                 "none": None, "stale": sim.obs}[after]
        sim.after_escape = shown
        before = sim.obs
        if after in ("none", "stale"):
            async def escape(session_id: str, data: str) -> None:
                sim.typed.append(data)
                sim.obs = None if after == "none" else before
            sim.w.host.agent.deps.send_input = escape
        with pytest.raises(JobError) as err:
            await sim.w.host.reply("iid-a", ReplyBody(job_id=body.job_id, text="yes"))
        assert err.value.code in ("owner_only", "worker_not_ready")
        assert sim.delivered == [] and "\r" not in sim.typed and sim.typed == ["\x1b"]
        sim.finish_text()
        await sim.ended()
    run(go())


def test_a_worker_that_cannot_be_stopped_stays_live_and_is_stopped_on_a_later_poll(sim) -> None:
    async def go() -> None:
        await sim.start()
        refuse = {"on": True}
        real = sim.w.host.agent.deps.stop_worker

        async def stop(session_id: str, session_uuid: Optional[str] = None) -> None:
            if refuse["on"]:
                raise JobError("worker_not_stopped", "the worker could not be stopped", 409)
            await real(session_id, session_uuid)

        sim.w.host.agent.deps.stop_worker = stop
        sim.finish_text()
        await sim.until(lambda r: r.detail == "the worker could not be stopped, trying again")
        assert sim.row().state == HostState.RUNNING and sim.row().result_text is None
        refuse["on"] = False
        row = await sim.ended()
        assert row.state == HostState.EXITED and row.result_text == "all done" and sim.stopped == [row.worker_session_id]
    run(go())


def test_the_stop_of_a_worker_the_owner_already_put_to_sleep_goes_on_to_collect(monkeypatch) -> None:
    from types import SimpleNamespace as NS

    from src.core.session_ops import sleep as sleep_ops

    for code in ("not_running", "archived", "no_tmux_identity"):
        async def fake(state: Any, uuid: str, fresh_ok: bool = False, _c: str = code) -> Any:
            return sleep_ops.SleepOutcome("refused", uuid, code=_c)

        monkeypatch.setattr(sleep_ops, "sleep_session", fake)
        _, stop = agent_launch.worker_hooks(NS(state=NS(), app=None))
        asyncio.run(stop("ses_a", "uuid-a"))
    async def other(state: Any, uuid: str, fresh_ok: bool = False) -> Any:
        return sleep_ops.SleepOutcome("refused", uuid, code="presence_unknown")

    monkeypatch.setattr(sleep_ops, "sleep_session", other)
    with pytest.raises(JobError):
        asyncio.run(stop("ses_a", "uuid-a"))


def test_recover_keeps_a_worker_that_tmux_still_has_and_the_sweep_restarts_a_dead_watch(sim) -> None:
    async def go() -> None:
        body = await sim.start()
        host = sim.w.host
        host.agent._watches[body.job_id].cancel()
        await asyncio.sleep(0.01)
        sim.listed, sim.present = False, True
        assert await host.recover_agents() == 1 and sim.row().state == HostState.RUNNING and body.job_id in host.agent._watches
        host.agent._watches[body.job_id].cancel()
        await asyncio.sleep(0.01)
        assert await host.agent.sweep_watches() == 1 and body.job_id in host.agent._watches
        sim.finish_text()
        await sim.ended()
    run(go())


def test_the_owners_max_agents_bounds_agent_jobs_but_never_a_stop_or_a_status(sim) -> None:
    from fastapi import HTTPException

    from src.core.pack.jobs.types import AdmitBody
    from src.core.pack.machines.restrictions import Restrictions

    async def go() -> None:
        sim.w.b.restrictions = Restrictions(max_agents=1)
        first = await sim.start()
        again = await asyncio.to_thread(sim.body)
        with pytest.raises(HTTPException) as err:
            await sim.w.host.start("iid-a", again)
        assert err.value.status_code == 403 and err.value.detail["rule"] == "max_agents" and sim.w.host.store.host_get(again.job_id) is None
        with pytest.raises(HTTPException):
            await sim.w.host.admit("iid-a", AdmitBody(job_id=paths.new_job_id(), project_uid=sim.w.uid, kind="suite", agent_family="claude"))
        sim.w.b.restrictions = Restrictions(max_agents=5)
        assert (await sim.w.host.status("iid-a", JobIdBody(job_id=first.job_id)))["state"] == "running"
        sim.w.b.restrictions = Restrictions(max_agents=1)
        assert (await sim.w.host.status("iid-a", JobIdBody(job_id=first.job_id)))["state"] == "running"
        sim.job_id = first.job_id
        sim.finish_text()
        await sim.ended()
    run(go())


def test_time_cap_stops_collects_and_is_124(sim) -> None:
    async def go() -> None:
        body = await sim.start(time_cap_s=60)
        row = await sim.ended()
        assert (row.state, row.exit_code, row.detail) == (HostState.EXITED, 124, "time cap") and sim.stopped == [row.worker_session_id]
        assert (await sim.w.host.collect("iid-a", JobIdBody(job_id=body.job_id)))["changed"] == 1
    run(go())


def test_dead_pane_ends_and_unreadable_waits_five_minutes(sim) -> None:
    async def go() -> None:
        await sim.start()
        sim.obs = DEAD
        row = await sim.ended()
        assert (row.exit_code, row.detail) == (1, "worker exited")
        sim.stopped.clear()
        body = await sim.start()
        sim.obs = UNKNOWN
        began = sim.now
        await sim.until(lambda r: sim.now - began >= 240)
        assert sim.row().state == HostState.RUNNING
        row = await sim.ended()
        assert sim.now - began >= agent_watch.UNREADABLE_S and (row.exit_code, row.detail) == (1, "worker status unreadable")
        assert sim.stopped == [row.worker_session_id]
        assert (await sim.w.host.collect("iid-a", JobIdBody(job_id=body.job_id)))["changed"] == 1
    run(go())


def test_recover_refinds_a_worker_and_fails_a_missing_one(sim) -> None:
    async def go() -> None:
        body = await sim.start()
        host = sim.w.host
        host.agent._watches[body.job_id].cancel()
        await asyncio.sleep(0.01)
        assert body.job_id not in host.agent._watches
        assert await host.recover_agents() == 1 and body.job_id in host.agent._watches
        sim.finish_text()
        await sim.ended()
        second = await sim.start()
        host.agent._watches[second.job_id].cancel()
        await asyncio.sleep(0.01)
        sim.listed = False
        await host.recover_agents()
        row = sim.row()
        assert (row.state, row.exit_code, row.detail) == (HostState.EXITED, 1, GONE_DETAIL)
        third = await asyncio.to_thread(sim.body)
        host.store.host_put(__import__("src.core.pack.jobs.types", fromlist=["HostJob"]).HostJob(
            job_id=third.job_id, caller_install="iid-a", project_uid=third.project_uid, state=HostState.PREPARING, body="agent",
            worker_session_id="ses_deadbeef"))
        sim.listed = True
        host.recover()
        assert host.store.host_get(third.job_id).state == HostState.FAILED
        await host.recover_agents()
        assert sim.stopped[-1] == "ses_deadbeef"
    run(go())


def test_gates_before_any_session(sim) -> None:
    async def go() -> None:
        sim.harness = False
        with pytest.raises(JobError) as err:
            await sim.w.host.admit("iid-a", __import__("src.core.pack.jobs.types", fromlist=["AdmitBody"]).AdmitBody(
                job_id=paths.new_job_id(), project_uid=sim.w.uid, kind="suite", agent_family="claude"))
        assert err.value.code == "no_harness"
        body = await asyncio.to_thread(sim.body)
        with pytest.raises(JobError) as err:
            await sim.w.host.start("iid-a", body)
        assert err.value.code == "no_harness" and sim.w.host.store.host_get(body.job_id) is None and not sim.created
        sim.harness = True

        def no_login(family: str, key: Optional[str], caller: Optional[str], ident: Optional[str] = None) -> AccountPick:
            raise JobError("account_not_usable", "no login", 409)

        sim.w.host.agent.deps.resolve_account = no_login
        with pytest.raises(JobError) as err:
            await sim.w.host.start("iid-a", body)
        assert err.value.code == "account_not_usable" and sim.w.host.store.host_get(body.job_id) is None
    run(go())


def test_stop_ends_the_worker_through_the_normal_stop(sim) -> None:
    async def go() -> None:
        body = await sim.start()
        await sim.w.host.stop("iid-a", __import__("src.core.pack.jobs.types", fromlist=["StopBody"]).StopBody(job_id=body.job_id, keep_files=True))
        row = sim.row()
        assert row.state == HostState.STOPPED and sim.stopped == [row.worker_session_id] and body.job_id not in sim.w.host.agent._watches
    run(go())




def _episode_ticks(name: str) -> List[Any]:
    import test_attention_replay as replay
    from src.core.attention.resolve import resolve_attention
    from src.core.attention.transcript_facts import classify_transcript_records

    episode = replay.load_episode(name)
    events = episode["events"]
    facts = [classify_transcript_records(e["transcript_records"], now=replay.parse_iso(e["t"])) for e in events]
    out = []
    for index, at in replay.tick_schedule(episode):
        evidence = replay.evidence_for(events[index], episode, at, facts[index])
        out.append((at, SimpleNamespace(verdict=resolve_attention(evidence), evidence=evidence),
                    [json.dumps(r) for r in events[index]["transcript_records"]]))
    return out


def test_h9_a_real_transcript_with_pauses_does_not_end_the_job_early(sim) -> None:
    ticks = _episode_ticks("d_reinvoked_after_production_said_done")
    first_done = next(i for i, t in enumerate(ticks) if t[1].verdict.state == ev.STATE_DONE_IDLE)
    assert first_done > 100 and any(t[1].verdict.state == ev.STATE_UNKNOWN for t in ticks[:first_done + 1])

    async def go() -> None:
        base = ticks[0][0]
        sim.now = (base - timedelta(days=1)).timestamp()

        def feed(s: Sim) -> None:
            n = min(s.tick, len(ticks) - 1)
            s.now = (base - timedelta(days=1)).timestamp() + (ticks[n][0] - base).total_seconds()
            s.obs = ticks[n][1]
            s.read = agent_watch.parse_transcript(ticks[n][2])

        sim.on_sleep = feed
        sim.obs = ticks[0][1]
        await sim.start(time_cap_s=21600)
        row = await sim.ended()
        assert row.state == HostState.EXITED and row.exit_code == 0 and row.result_text
        assert first_done + 1 <= sim.tick <= first_done + 4, (sim.tick, first_done)
        assert len(sim.stopped) == 1
    run(go())


def test_h9_a_real_question_transcript_parks_and_does_not_finish(sim) -> None:
    ticks = _episode_ticks("b_blocked_on_askuserquestion")

    async def go() -> None:
        base = ticks[0][0]

        def feed(s: Sim) -> None:
            n = min(s.tick, len(ticks) - 1)
            s.obs, s.read = ticks[n][1], agent_watch.parse_transcript(ticks[n][2])

        sim.on_sleep = feed
        sim.obs = ticks[0][1]
        sim.now = (base - timedelta(days=1)).timestamp()
        await sim.start(time_cap_s=21600)
        parked = await sim.until(lambda r: r.state == HostState.PARKED)
        assert parked.question_kind in ("question", "input", "plan_approval") and not sim.stopped
        sim.w.host.agent._watches[sim.job_id].cancel()
    run(go())


def test_conversation_seam_reads_the_uuid_from_the_wrapper_and_the_dir_from_the_session() -> None:
    from src.models.sessions import Session, SessionInfo

    session = Session(id="ses_x", pty_pid=1, working_dir="/work/dir")
    info = SessionInfo(session=session, claude_session_uuid="uuid-123")

    async def get_session_info(session_id: str) -> Any:
        return info if session_id == "ses_x" else None

    manager = SimpleNamespace(get_session_info=lambda session_id: get_session_info(session_id))
    app = SimpleNamespace(state=SimpleNamespace(session_manager=manager))
    deps = AgentDeps.from_app(app)
    assert run(deps.conversation("ses_x")) == ("uuid-123", "/work/dir")
    assert run(deps.conversation("ses_none")) == (None, None)
