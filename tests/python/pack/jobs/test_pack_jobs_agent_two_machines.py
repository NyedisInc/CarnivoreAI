
from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional

import pytest

pytest.importorskip("fastapi")

from test_pack_jobs_two_machines import git, world  # noqa: E402,F401

import pack_jobs_fake_agent as fake  # noqa: E402
from src.core.attention import evidence as ev  # noqa: E402
from src.core.mcp import pack_jobs_tools as pjt  # noqa: E402
from src.core.pack.jobs import agent_launch, agent_watch, boot, paths, tell, usage_rollup  # noqa: E402
from src.core.pack.jobs.agent_account import AccountPick  # noqa: E402
from src.core.pack.jobs.agent_facts import CallerFacts  # noqa: E402
from src.core.pack.jobs.agent_host import AgentDeps  # noqa: E402
from src.core.pack.jobs.agent_types import CAP_ACCOUNT_IDENTITY, CAP_AGENT  # noqa: E402
from src.core.pack.jobs.engine_agent import AgentRequest  # noqa: E402
from src.core.pack.jobs.types import CAP_JOBS, TERMINAL, JobError, JobState  # noqa: E402

CALLER = "uuid-caller"
QUESTION = "blue or green?"
ASKED = QUESTION + "\nblue; green"
FINAL = "all done, the file is written"
USAGE = {"input_tokens": 11, "output_tokens": 22, "cache_read_input_tokens": 3, "cache_creation_input_tokens": 4}
FAKE_SCRIPT = Path(__file__).with_name("pack_jobs_fake_agent.py")


def look(state: str, reason: str, *, dialog: Any = None) -> Any:
    return SimpleNamespace(verdict=ev.AttentionVerdict(state, reason, ev.TIER_REGISTRY, detail="the worker asks"),
                           evidence=SimpleNamespace(dialog=dialog, startup_screen=None), cycle=0, stale=False)


BUSY, DONE = look(ev.STATE_BUSY, ev.REASON_TOOL), look(ev.STATE_DONE_IDLE, ev.REASON_TURN_ENDED)
ASK = look(ev.STATE_NEEDS_USER, ev.REASON_QUESTION, dialog=SimpleNamespace(question=QUESTION, options=["blue", "green"], startup_kind=None))


class Sim:

    def __init__(self, w: Any, family: str, *, ask: bool = False) -> None:
        self.w, self.family, self.ask = w, family, ask
        self.t0 = self.now = time.time()
        self.obs = BUSY
        self.relay = w.tmp / "relay profile"
        self.conversation = str(uuid.uuid4())
        self.created: List[Dict[str, Any]] = []
        self.stopped: List[str] = []
        self.typed: List[str] = []
        self.delivered: List[str] = []
        self.idents: List[Optional[str]] = []
        self.record = w.tmp / "fake-agent-record.json"
        self.job_id: Optional[str] = None
        w.host._clock = lambda: self.now
        w.host.agent.bind(self.deps())

    def write(self, text: str, *, usage: Optional[Dict[str, int]] = None) -> None:
        if self.family == "claude":
            fake.write_claude(self.relay, self.conversation, [fake.claude_record(text, self.now + 1, usage=usage)])
        else:
            fake.write_codex(self.relay, self.conversation, [fake.codex_record(text, self.now + 1)])

    def deps(self) -> AgentDeps:
        var = "CLAUDE_CONFIG_DIR" if self.family == "claude" else "CODEX_HOME"

        async def create(plan: Any, session_id: str, label: str, working_dir: str) -> agent_launch.WorkerRef:
            self.created.append({"plan": plan, "session_id": session_id, "label": label, "dir": working_dir})
            env = {**os.environ, **plan.extra_env}
            done = await asyncio.to_thread(subprocess.run, [sys.executable, str(FAKE_SCRIPT), str(self.record), "--push"], cwd=working_dir, env=env,
                                           capture_output=True, text=True, check=False)
            assert done.returncode == 0, done.stderr
            self.write(QUESTION if self.ask else FINAL, usage=None if self.ask else USAGE)
            self.obs = ASK if self.ask else DONE
            return agent_launch.WorkerRef(session_id, "uuid-" + session_id, "carnivore_" + session_id, 1)

        async def stop(session_id: str, session_uuid: Optional[str] = None) -> None:
            self.stopped.append(session_id)

        async def send_input(session_id: str, data: str) -> None:
            self.typed.append(data)
            if data == "\x1b":
                self.obs = SimpleNamespace(**{**vars(DONE), "cycle": self.obs.cycle + 1})

        async def deliver(session_id: str, text: str) -> None:
            self.delivered.append(text)
            self.write("used blue", usage=USAGE)
            self.obs = SimpleNamespace(**{**vars(DONE), "cycle": self.obs.cycle + 1})

        async def listed(session_id: str) -> bool:
            return session_id not in self.stopped

        async def conversation(session_id: str) -> Any:
            return self.conversation, self.created[0]["dir"]

        async def sleep(seconds: float) -> None:
            self.now += seconds
            await asyncio.sleep(0.001)

        return AgentDeps(create, stop, lambda sid: self.obs, send_input, listed, conversation,
                         lambda fam, key, caller, ident=None: self.idents.append(ident) or AccountPick("acct", {var: str(self.relay)}, "work", "relay"),
                         deliver=deliver, harness_present=lambda fam: True, sleep=sleep, poll_s=2.0)


class Caller:

    def __init__(self, w: Any, family: str, *, advertise: bool = True, identity_cap: bool = False) -> None:
        self.w, self.sent = w, []
        self.engine = eng = w.engine()
        view_for = eng._view_for

        async def facts(caller: Optional[str]) -> CallerFacts:
            return CallerFacts(family, account_key="work", permission_mode="default" if family == "claude" else "ask", account_identity="me@x.co")

        async def notifier(store: Any, rec: Any, token: str) -> bool:
            async def resolve(app: Any, session_id: str) -> tell.Receiver:
                return tell.Receiver("ses_caller", CALLER, CALLER, 1)

            return await tell.notify_caller(None, store, rec, token, resolve=resolve, queue=lambda r, t: self.sent.append(t) or "m", wake=lambda a, k: None)

        eng._facts_for, eng._notifier = facts, notifier
        caps = [CAP_JOBS, CAP_AGENT, *([CAP_ACCOUNT_IDENTITY] if identity_cap else [])] if advertise else [CAP_JOBS]
        eng._view_for = lambda root, puid: dataclasses.replace(view_for(root, puid), caps={"iid-b": caps})

    def request(self, task: str = "write worker-out.txt", **kw: Any) -> AgentRequest:
        return AgentRequest(command="", folder=str(self.w.a.root), task=task, caller_session=CALLER, kind="suite", time_cap_s=3600, **kw)

    async def until(self, pred: Callable[[Any], bool], job_id: str, limit: float = 60.0) -> Any:
        end = time.monotonic() + limit
        while time.monotonic() < end:
            rec = self.engine.store.get_job(job_id)
            if pred(rec):
                return rec
            await asyncio.sleep(0.02)
        raise AssertionError(f"never reached: {self.engine.store.get_job(job_id)}")

    async def settle(self) -> None:
        await asyncio.gather(*self.engine._notify_tasks)


@pytest.mark.parametrize("family", ["claude", "codex"])
def test_a_task_runs_on_the_other_computer_and_comes_back(world, family: str) -> None:
    w = world
    sim, caller = Sim(w, family), Caller(w, family)

    async def flow():
        waiting = await caller.engine.propose(caller.request())
        assert waiting.state == JobState.WAITING_APPROVAL and waiting.body == "agent" and waiting.family == family, waiting
        sim.job_id = waiting.id
        await caller.engine.proceed(waiting.id)
        done = await caller.until(lambda r: r.state in TERMINAL, waiting.id)
        await caller.settle()
        return done

    done = asyncio.run(flow())
    assert done.state == JobState.DONE, (done.error_code, done.error_detail)
    assert done.result_text == FINAL and (done.account_label, done.account_how) == ("work", "relay")
    assert (w.a.root / "worker-out.txt").read_text() == "worker did: write worker-out.txt\n"
    assert not (w.a.root / agent_launch.TASK_DIR).exists(), "the task file must not come back"
    assert len(sim.created) == 1 and sim.stopped == [sim.created[0]["session_id"]], "the worker session is stopped"
    assert sim.created[0]["dir"].startswith(str(w.b.jobs)), "the worker runs in a slot under b's jobs folder"
    plan, ran = sim.created[0]["plan"], json.loads(sim.record.read_text())
    assert ran["task_read"].startswith("write worker-out.txt") and ran["task_mode"] == "0o600"
    assert not ran["task_in_argv"] and "write worker-out.txt" not in " ".join([*plan.extra_args, plan.opening_prompt, sim.created[0]["label"]])
    assert plan.agent_type == family and all(plan.extra_env[k] == v for k, v in paths.push_block_env().items())
    assert ran["push"]["code"] != 0 and "carnivore-no-push" in ran["push"]["stderr"], "the push block is on in the worker's env"
    assert len(caller.sent) == 1 and "finished" in caller.sent[0] and f'job_wait("{done.id}")' in caller.sent[0], caller.sent
    if family == "claude":
        assert json.loads(done.usage_json)["input_tokens"] == 11
        rolled = usage_rollup.delegated_for("ses_caller", CALLER, state_dir=w.a.state)
        assert rolled is not None and rolled.jobs == 1 and rolled.output_tokens == 22


def test_a_question_parks_job_reply_resumes_and_a_worker_may_not_delegate(world, monkeypatch) -> None:
    w = world
    sim, caller = Sim(w, "claude", ask=True), Caller(w, "claude")
    monkeypatch.setitem(boot._built, "host", w.host)

    async def flow():
        eng = caller.engine
        waiting = await eng.propose(caller.request())
        await eng.proceed(waiting.id)
        asking = await eng.wait(waiting.id, 60)
        assert asking.state == JobState.QUESTION and asking.question == ASKED and asking.question_kind == "question", asking
        worker = sim.created[0]["session_id"]
        info = SimpleNamespace(session=SimpleNamespace(id=worker), session_uuid="uuid-" + worker)
        assert pjt.worker_refusal(info) == pjt.WORKER_REFUSAL, "a live worker is found in this computer's own table"
        assert pjt.worker_refusal(SimpleNamespace(session=SimpleNamespace(id="ses_other"), session_uuid="uuid-other")) is None
        with pytest.raises(JobError) as other:
            await eng.reply(waiting.id, "green", "uuid-someone-else")
        assert other.value.code == "not_your_job" and sim.typed == []
        await eng.reply(waiting.id, "use blue", CALLER)
        done = await eng.wait(waiting.id, 60)
        await caller.settle()
        return done

    done = asyncio.run(flow())
    assert done.state == JobState.DONE and done.result_text == "used blue", done
    assert sim.typed == ["\x1b"] and sim.delivered == ["use blue"]
    assert caller.sent == [], "a call was holding the whole time, so no message"
    assert pjt.worker_refusal(SimpleNamespace(session=SimpleNamespace(id=sim.created[0]["session_id"]), session_uuid=None)) is None, "the job ended"


def test_ten_minutes_without_an_answer_ends_with_the_question(world) -> None:
    w = world
    sim, caller = Sim(w, "claude", ask=True), Caller(w, "claude")

    async def flow():
        waiting = await caller.engine.propose(caller.request())
        await caller.engine.proceed(waiting.id)
        done = await caller.until(lambda r: r.state in TERMINAL, waiting.id)
        await caller.settle()
        return done

    done = asyncio.run(flow())
    assert done.state == JobState.DONE and done.question == ASKED and done.question_kind == "question" and done.result_text == QUESTION, done
    assert sim.now - sim.t0 >= agent_watch.PARK_S, "ten minutes of the injected clock"
    assert sim.stopped == [sim.created[0]["session_id"]]
    assert len(caller.sent) == 2 and "asks a question" in caller.sent[0] and "finished" in caller.sent[1], caller.sent


def test_a_reader_in_the_wrong_profile_root_finds_nothing(world) -> None:
    w = world
    sim = Sim(w, "claude")
    sim.write(FINAL, usage=USAGE)
    right = agent_watch.read_transcript("claude", sim.conversation, str(w.tmp), str(sim.relay))
    assert right.text == FINAL and right.last_at == pytest.approx(sim.t0 + 1)
    empty = w.tmp / "some other profile"
    (empty / "projects").mkdir(parents=True)
    assert agent_watch.read_transcript("claude", sim.conversation, str(w.tmp), str(empty)) == agent_watch.Read(None, None)
    assert agent_watch.read_usage_totals("claude", sim.conversation, str(w.tmp), str(empty)) is None


def test_a_peer_without_the_agent_capability_is_not_sent_an_agent_job(world) -> None:
    w = world
    Sim(w, "claude")
    rec = asyncio.run(Caller(w, "claude", advertise=False).engine.propose(Caller(w, "claude", advertise=False).request()))
    assert rec.state == JobState.HERE, rec
    assert not (w.a.jobs / "repos").exists()


@pytest.mark.parametrize("identity_cap,want", [(True, "me@x.co"), (False, None)])
def test_the_callers_login_identity_reaches_the_targets_account_check_only_when_it_advertises_it(world, identity_cap: bool, want: Optional[str]) -> None:
    w = world
    sim, caller = Sim(w, "claude"), Caller(w, "claude", identity_cap=identity_cap)

    async def flow():
        waiting = await caller.engine.propose(caller.request())
        sim.job_id = waiting.id
        await caller.engine.proceed(waiting.id)
        await caller.until(lambda r: r.state in TERMINAL, waiting.id)
        await caller.settle()

    asyncio.run(flow())
    assert sim.idents and sim.idents[-1] == want, sim.idents
