from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

import src.config  # noqa: F401
from src.core.automations import gates, models as m, targets
from src.core.automations.scheduler import Scheduler
from src.core.automations.targets import agent, sequence
from src.core.provider_ledger import refresh_poke

USAGE = {"input_tokens": 100, "output_tokens": 40, "cache_read_input_tokens": 30, "cache_creation_input_tokens": 5}


class Store:

    attachments_root = Path(tempfile.mkdtemp(prefix="cc_usage_att_"))

    def update_run(self, run_id: str, **fields: Any) -> Dict[str, Any]:
        return {"run_id": run_id}


@pytest.fixture
def run_agent(tmp_path, monkeypatch):
    monkeypatch.setattr(refresh_poke, "resolve_claude_binary", lambda: "/fake/claude")
    monkeypatch.setattr(gates, "login_of", lambda target: (None, None))
    monkeypatch.setattr(agent, "folder_problem", lambda folder: None)
    seen: List[int] = []
    current: Dict[str, Any] = {}

    async def fake_child(argv, env, *, on_line, **kw):
        seen.append(1)
        result = {"type": "result", "subtype": "success", "is_error": False, "terminal_reason": "completed", "num_turns": 1,
                  "total_cost_usd": 0.25, "session_id": "s", "result": "done", **current}
        on_line(json.dumps(result).encode())
        return SimpleNamespace(ran=True, timed_out=False, exit_code=0, stderr_tail=b"", spawn_error=None)

    monkeypatch.setattr(refresh_poke, "run_child_streaming", fake_child)
    folder = tmp_path / "work"
    folder.mkdir()

    def go(extra: Dict[str, Any]) -> m.RunOutcome:
        current.clear()
        current.update(extra)
        automation = {"target": {"kind": "agent", "folder": str(folder), "prompt": "p", "max_turns": 3}, "delivery": {"notify": False}}
        out = asyncio.run(agent.run(SimpleNamespace(store=Store()), automation, {"run_id": "r1"}))
        assert seen, "population check: the faked child never ran"
        return out

    return go


def test_agent_run_records_usage(run_agent):
    out = run_agent({"usage": USAGE})
    assert out.status == m.SUCCEEDED
    assert out.usage == {"input": 100, "output": 40, "cache": 35, "total": 175}


def test_missing_usage_is_null_never_zeros(run_agent):
    assert run_agent({}).usage is None
    assert run_agent({"usage": {"output_tokens": 4}}).usage is None
    assert run_agent({"usage": "bogus"}).usage is None
    only = run_agent({"usage": {"input_tokens": 7, "output_tokens": 2}}).usage
    assert only == {"input": 7, "output": 2, "cache": 0, "total": 9}


def test_scheduler_writes_the_outcome_usage_onto_the_run():
    seen: Dict[str, Any] = {}
    sched = Scheduler.__new__(Scheduler)
    sched.store = SimpleNamespace(update_run=lambda run_id, **f: seen.update(f))
    sched._after_end = lambda *a, **k: None
    sched._app_state, sched._boot_id, sched._cancelling, sched._tasks, sched._clock = None, "b", set(), [], lambda: 1.0
    usage = {"input": 1, "output": 1, "cache": 0, "total": 2}

    async def runner(ctx, automation, run_row):
        return m.RunOutcome(status=m.SUCCEEDED, usage=usage)

    asyncio.run(sched._execute(runner, {"automation_id": "aut_1", "target": {"kind": "session_message"}}, {"run_id": "run_1", "status": m.RUNNING}))
    assert seen.get("usage") == usage


def _sequence(monkeypatch, usages: List[Optional[Dict[str, int]]]) -> m.RunOutcome:
    queue = list(usages)

    async def runner(ctx, automation, run_row):
        return m.RunOutcome(status=m.SUCCEEDED, usage=queue.pop(0))

    monkeypatch.setitem(targets.RUNNERS, "agent", runner)
    monkeypatch.setattr(sequence.notify_policy, "tell", lambda *a, **k: None)
    steps = [{"kind": "agent"} for _ in usages]
    automation = {"target": {"kind": "sequence", "steps": steps}, "delivery": {"notify": False}}
    return asyncio.run(sequence.run(SimpleNamespace(), automation, {"run_id": "r1"}))


def test_sequence_sums_measured_steps(monkeypatch):
    a = {"input": 10, "output": 2, "cache": 3, "total": 15}
    b = {"input": 1, "output": 1, "cache": 0, "total": 2}
    assert _sequence(monkeypatch, [a, None, b]).usage == {"input": 11, "output": 3, "cache": 3, "total": 17}
    assert _sequence(monkeypatch, [None, None]).usage is None
