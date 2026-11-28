
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import pytest

from src.core.pack.jobs import needs_policy, policy as policy_mod, recipe
from src.core.pack.jobs.place import PlaceView, place
from src.core.pack.jobs.store import JobStore
from src.core.pack.jobs.types import CAP_JOBS, DepDir
from src.core.pack.placement import rule
from src.core.pack.placement.workload import resolve

A, B = "iid-a", "iid-b"
UID = "p1x23456"
SUITE = resolve({"kind": "suite"})
NPM_PROJECT = [DepDir("web/node_modules", "npm", {"web/package-lock.json": "ab12"}, None)]


def snap(load: float = 0.0, tools_: Optional[Dict[str, bool]] = None) -> Dict[str, Any]:
    return {"load": {"cores": 10, "busy_cores": load, "mem_total_gb": 32.0, "mem_available_gb": 28.0, "disk_free_gb": 200.0},
            "reserve": {"level": "away", "cpu_pct": 10, "mem_pct": 10}, "toolchain": {}, "can": {"v": 1, "tools": dict(tools_ or {})}}


def placed(me_load: float, peer_tools: Dict[str, bool], tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(needs_policy.snapshot, "dep_dirs_of", lambda root: NPM_PROJECT)
    store = JobStore(tmp_path / "state")
    policy_mod.set_auto(store, UID, True)
    filters = needs_policy.setup_filters(["/work/app"], None, False)
    me = rule.MachineInput(A, "mac", snap(me_load), True, True, True, True, None)
    peer = rule.MachineInput(B, "tower", snap(0.0, peer_tools), True, False, False, True, None)
    return place(SUITE, UID, policy_mod.get(store, UID), PlaceView(me, [peer], {B: [CAP_JOBS]}, A), filters=filters)


def test_a_project_whose_setup_runs_npm_is_refused_for_a_computer_without_npm_and_taken_by_one_with_it(tmp_path, monkeypatch) -> None:
    without = placed(9.5, {"node": True, "npm": False}, tmp_path, monkeypatch)
    assert without.decision == "here" and "tower" in without.reason and "lacks npm" in without.reason
    unreported = placed(9.5, {"git": True}, tmp_path, monkeypatch)
    assert unreported.decision == "here" and "has not reported whether it has npm" in unreported.reason
    with_npm = placed(9.5, {"node": True, "npm": True}, tmp_path, monkeypatch)
    assert (with_npm.decision, with_npm.peer_install_id) == ("remote", B)
    assert placed(0.0, {}, tmp_path, monkeypatch).decision == "here"


def test_a_failed_setup_step_names_its_position_and_program() -> None:
    steps = recipe.plan("/slot", NPM_PROJECT, {}, None)
    assert recipe.tools_needed(steps) == ["node", "npm"]
    assert recipe.failure_text(steps, 0) == "setup step 1 of 1 (npm) failed (see the setup log on that computer)"


def test_a_homebrew_install_of_node_also_meets_the_npm_setup_filter(tmp_path, monkeypatch) -> None:
    from src.core.pack.jobs.install import CAP_INSTALL
    from src.core.pack.jobs.place import install_candidates
    from src.core.pack.placement.needs import parse_need
    monkeypatch.setattr(needs_policy.snapshot, "dep_dirs_of", lambda root: NPM_PROJECT)
    store = JobStore(tmp_path / "state")
    policy_mod.set_auto(store, UID, True)
    filters = needs_policy.setup_filters(["/work/app"], None, False)
    peer_snap = snap(0.0, {"node": False, "npm": False})
    peer_snap["can"]["brew"] = True
    peer_snap["restrictions"] = {"may_install_tools": True}
    me = rule.MachineInput(A, "mac", snap(9.5), True, True, True, True, None)
    peer = rule.MachineInput(B, "tower", peer_snap, True, False, False, True, None)
    got = install_candidates(SUITE, UID, policy_mod.get(store, UID), PlaceView(me, [peer], {B: [CAP_JOBS, CAP_INSTALL]}, A),
                             needs=[parse_need("node")], filters=filters)
    assert got is not None and got.peer_install_id == B and got.install == ["node"]
