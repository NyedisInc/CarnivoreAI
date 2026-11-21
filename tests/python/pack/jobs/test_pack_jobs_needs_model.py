
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from src.core.pack.jobs import needs_model, policy as policy_mod
from src.core.pack.jobs.store import JobStore
from src.core.pack.jobs.place import PlaceView, place
from src.core.pack.placement import rule
from src.core.pack.placement.workload import resolve

A, B, C = "iid-a", "iid-b", "iid-c"
UID = "p1x23456"
SUITE = resolve({"kind": "suite"})
ON = SimpleNamespace(placement_mode="enhanced", placement_model=None)
OFF = SimpleNamespace(placement_mode="stats", placement_model=None)


@pytest.fixture(autouse=True)
def _clear() -> None:
    needs_model._cache.clear()


def snap(*, tools_: Dict[str, bool] | None = None, pegged: bool = False) -> Dict[str, Any]:
    out: Dict[str, Any] = {"load": {"cores": 10, "busy_cores": 0.0, "mem_total_gb": 32.0, "mem_available_gb": 28.0, "disk_free_gb": 200.0},
                           "reserve": {"level": "away", "cpu_pct": 10, "mem_pct": 10}, "toolchain": {}, "can": {"v": 1, "tools": dict(tools_ or {})}}
    if pegged:
        out["pressure"] = {"pegged": True, "why": "busy cores over the line", "mem": "normal"}
    return out


def mi(iid: str, label: str, snapshot: Dict[str, Any], is_self: bool = False) -> rule.MachineInput:
    return rule.MachineInput(iid, label, snapshot, True, is_self, is_self, True, None)


def the_view(*peers: rule.MachineInput) -> PlaceView:
    return PlaceView(mi(A, "home", snap(pegged=True), True), list(peers), {p.install_id: ["pack.jobs"] for p in peers}, master_id=A)


class Decide:

    def __init__(self, yes: List[str], delay: float = 0.0, fail: bool = False) -> None:
        self.yes, self.delay, self.fail, self.calls = yes, delay, fail, []

    async def __call__(self, ref: Any, *, state: Any, questions: Dict[str, Any]) -> Any:
        self.calls.append((state, questions))
        if self.fail:
            raise RuntimeError("boom")
        await asyncio.sleep(self.delay)
        words = [q["question"].rsplit("has ", 1)[1].rstrip("?") for q in questions.values()]
        return SimpleNamespace(answers={k: {"value": "yes" if w in self.yes else "no"} for k, w in zip(questions, words)})


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_off_unless_enhanced() -> None:
    d = Decide(["ffmpeg"])
    assert run(needs_model.suggest("render", [], ["ffmpeg"], decide=d, settings=OFF)) == []
    assert d.calls == []


def test_only_offered_words_and_never_hard() -> None:
    d = Decide(["ffmpeg", "blender", "bogus"])
    got = run(needs_model.suggest("render", ["ffmpeg"], ["ffmpeg", "gpu", "bogus"], decide=d, settings=ON))
    assert [n.text for n in got] == ["ffmpeg"]


def test_command_text_never_sent() -> None:
    d = Decide(["gpu"])
    run(needs_model.suggest("render", needs_model.programs_of("SECRET=hunter2 ffmpeg -i /Users/x/private.mov out"), ["gpu"], decide=d, settings=ON))
    blob = json.dumps(d.calls)
    assert "hunter2" not in blob and "private" not in blob and "ffmpeg" in blob


def test_timeout_and_failure_add_nothing() -> None:
    assert run(needs_model.suggest("suite", [], ["gpu"], decide=Decide(["gpu"], delay=1.0), timeout=0.05, settings=ON)) == []
    assert run(needs_model.suggest("suite", [], ["gpu"], decide=Decide(["gpu"], fail=True), settings=ON)) == []


def test_cached_ten_minutes() -> None:
    d, now = Decide(["gpu"]), [0.0]
    for t in (0.0, 599.0, 601.0):
        now[0] = t
        run(needs_model.suggest("suite", [], ["gpu"], decide=d, settings=ON, clock=lambda: now[0]))
    assert len(d.calls) == 2


def pol_for(tmp_path: Any) -> policy_mod.Policy:
    store = JobStore(tmp_path / "state")
    policy_mod.set_auto(store, UID, True)
    return policy_mod.get(store, UID)


def test_refine_orders_candidates_only(tmp_path: Any) -> None:
    plain, has = mi(B, "b", snap()), mi(C, "c", snap(tools_={"ffmpeg": True}))
    v = the_view(plain, has)
    pol = pol_for(tmp_path)
    first = place(SUITE, UID, pol, v)
    assert first.decision == "remote"
    d = Decide(["ffmpeg"])
    got = run(needs_model.refine(first, SUITE, UID, pol, v, {}, "suite", "pytest -q", decide=d, settings=ON))
    assert got.decision == "remote" and got.peer_install_id == C
    assert {r["install_id"] for r in got.why if r["candidate"]} == {B, C}
    assert d.calls


def test_refine_skips_here_and_single_candidate(tmp_path: Any) -> None:
    d = Decide(["ffmpeg"])
    v = the_view(mi(B, "b", snap(tools_={"ffmpeg": True})))
    pol = pol_for(tmp_path)
    first = place(SUITE, UID, pol, v)
    assert run(needs_model.refine(first, SUITE, UID, pol, v, {}, "suite", "x", decide=d, settings=ON)) is first
    here = first.__class__("here", None, None, "r")
    assert run(needs_model.refine(here, SUITE, UID, pol, v, {}, "suite", "x", decide=d, settings=ON)) is here
    assert d.calls == []
