
from __future__ import annotations

import importlib.machinery
import importlib.util
from pathlib import Path

from src.core.computers import join_job
from src.core.federation import discovery

TESTSRV = Path(__file__).resolve().parents[3] / "scripts" / "testsrv"


def _testsrv():
    loader = importlib.machinery.SourceFileLoader("testsrv_fx3b", str(TESTSRV))
    spec = importlib.util.spec_from_loader("testsrv_fx3b", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def test_a_provisional_join_reads_linking_until_the_first_link(monkeypatch) -> None:
    monkeypatch.setattr(join_job, "_job", join_job.JoinJob(state="joined", main_label="nostromo"))
    monkeypatch.setattr(join_job, "first_run_state", lambda: "join_pending")
    assert join_job.window_status()["state"] == "linking"
    assert join_job.join_status()["state"] == "joined"
    monkeypatch.setattr(join_job, "first_run_state", lambda: "joined")
    assert join_job.window_status()["state"] == "joined"


def test_other_job_states_pass_through(monkeypatch) -> None:
    monkeypatch.setattr(join_job, "_job", join_job.JoinJob(state="connecting"))
    monkeypatch.setattr(join_job, "first_run_state", lambda: "join_pending")
    assert join_job.window_status()["state"] == "connecting"


def test_only_a_testslot_name_is_honored() -> None:
    slot = {"CARNIVORE_SETTINGS_ENV_FILE": "/slot/env"}
    assert discovery.testslot_instance_name({**slot, "CARNIVORE_TESTSRV_BONJOUR": "testslot_2"}) == "testslot_2"
    for bad in ("", "Adams-Mac-mini", "testslot", "testslot2", "testslot_1\n", "xtestslot_1"):
        assert discovery.testslot_instance_name({**slot, "CARNIVORE_TESTSRV_BONJOUR": bad}) is None
    assert discovery.testslot_instance_name({"CARNIVORE_TESTSRV_BONJOUR": "testslot_2"}) is None
    assert discovery.testslot_instance_name({}) is None


def test_bonjour_marker_sets_the_env_and_reset_clears_it(tmp_path, monkeypatch) -> None:
    ts = _testsrv()
    monkeypatch.setattr(ts, "ROOT", tmp_path)
    slot = ts.Slot(2)
    slot.dir.mkdir(parents=True)
    assert "CARNIVORE_TESTSRV_BONJOUR" not in ts.child_env(slot)
    assert ts.apply_bonjour_mode(slot, True) is True
    assert ts.child_env(slot)["CARNIVORE_TESTSRV_BONJOUR"] == "testslot_2"
    assert ts.apply_bonjour_mode(slot, True) is False
    assert "bonjour-mode" in ts.WIPED
    assert ts.apply_bonjour_mode(slot, False) is True
    assert "CARNIVORE_TESTSRV_BONJOUR" not in ts.child_env(slot)
