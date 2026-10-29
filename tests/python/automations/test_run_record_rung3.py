from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.core.automations import models as m
from src.core.automations import targets
from src.core.automations.report_empty import report_is_empty
from src.core.automations.store import AutomationStore
from src.core.automations.store_schema import MIGRATIONS, storage_for
from src.core.computers.this_label import this_label
from src.cplugs.sdk.storage import CplugStorage, StorageSpec

NOW = 1_800_000_000.0
RECIPE = {"kind": "command", "command": "true"}
DELIVERY = {"notify": True, "notify_on": None}
CASES = json.loads((Path(__file__).parents[2] / "fixtures" / "automations" / "report_empty_cases.json").read_text())


def _rung_two_db(tmp_path):
    old = CplugStorage(tmp_path / "automations", StorageSpec(db="automations.db", migrations=MIGRATIONS[:2]), tmp_path)
    conn = old.connect(True)
    for aid in ("aut_a", "aut_b"):
        conn.execute("INSERT INTO automations (automation_id, name, name_key, enabled, cron, target, delivery, revision, "
                     "created_by, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                     (aid, aid, aid, 0, "0 3 * * *", json.dumps(RECIPE), json.dumps(DELIVERY), 1, "app", 1.0, 1.0))
    rows = [("a1", "aut_a", json.dumps({"stdout": "x"})), ("b1", "aut_b", None), ("a2", "aut_a", json.dumps({"stdout": " "})),
            ("a3", "aut_a", json.dumps({"pruned": True})), ("b2", "aut_b", json.dumps({"command": "ls", "exit_code": 0})),
            ("a4", "aut_a", None)]
    for run_id, aid, report in rows:
        conn.execute("INSERT INTO runs (run_id, automation_id, trigger, status, report, report_bytes, created_at) "
                     "VALUES (?,?,?,?,?,?,?)", (run_id, aid, "schedule", m.SUCCEEDED, report, len(report or ""), 1.0))
    conn.commit()
    conn.close()


async def _runner(ctx, automation, run):
    return m.RunOutcome()


@pytest.fixture(autouse=True)
def _runners(monkeypatch):
    for kind in m.TARGET_KINDS:
        monkeypatch.setitem(targets.RUNNERS, kind, _runner)


def _store(tmp_path):
    return AutomationStore(storage_for(tmp_path), clock=lambda: NOW, notify=lambda _t: None)


def test_report_is_empty_matches_the_shared_fixture():
    for case in CASES:
        assert report_is_empty(case["report"]) is case["empty"], case["name"]


def test_upgrade_numbers_runs_and_flags_empty_output(tmp_path):
    _rung_two_db(tmp_path)
    store = _store(tmp_path)
    got = {r["run_id"]: r for r in store.runs("aut_a") + store.runs("aut_b")}
    assert [got[k]["number"] for k in ("a1", "a2", "a3", "a4")] == [1, 2, 3, 4]
    assert [got[k]["number"] for k in ("b1", "b2")] == [1, 2]
    assert {k: got[k]["output_empty"] for k in got} == {"a1": False, "a2": True, "a3": None, "a4": None, "b1": None, "b2": True}
    assert all(r["host"] is None and r["usage"] is None and r["delivered"] is None and r["attachments"] is None for r in got.values())
    nxt = store.insert_run("aut_a", "boot_1")
    assert nxt["number"] == 5 and nxt["host"] == this_label()


def test_new_runs_get_the_next_number_and_the_host(tmp_path):
    store = _store(tmp_path)
    created = store.create(name="n", cron="*/15 * * * *", target=RECIPE)
    aid = created["automation_id"]
    first = store.insert_run(aid, "boot_1")
    assert (first["number"], first["host"], first["output_empty"]) == (1, this_label(), None)
    store.update_run(first["run_id"], status=m.SUCCEEDED, ended_at=NOW, report={"command": "ls", "exit_code": 0})
    assert store.run(first["run_id"])["output_empty"] is True
    store.update_run(first["run_id"], report={"stdout": "x"})
    assert store.run(first["run_id"])["output_empty"] is False
    store.update_run(first["run_id"], report=None)
    assert store.run(first["run_id"])["output_empty"] is None
    skipped = store.finish_skip(store.insert_run(aid, "boot_1")["run_id"], m.R_MISSED)
    assert (store.run(skipped)["number"], store.run(skipped)["host"]) == (2, this_label())


def test_a_claimed_scheduled_run_gets_number_and_host(tmp_path):
    store = _store(tmp_path)
    created = store.create(name="n", cron="*/15 * * * *", target=RECIPE)
    with store._write() as tx:
        tx.execute("UPDATE automations SET enabled = 1, next_fire_at = ? WHERE automation_id = ?", (NOW - 1, created["automation_id"]))
    run = store.claim_due(NOW, "boot_1")[0]
    assert (run["number"], run["host"]) == (1, this_label())


def test_prune_keeps_numbers_and_the_next_insert_continues(tmp_path):
    store = _store(tmp_path)
    aid = store.create(name="n", cron="*/15 * * * *", target=RECIPE)["automation_id"]
    for _ in range(m.RUNS_KEPT + 3):
        run = store.insert_run(aid, "boot_1")
        store.update_run(run["run_id"], status=m.SUCCEEDED, ended_at=NOW)
    kept = [r["number"] for r in store.runs(aid, limit=m.RUNS_KEPT)]
    assert kept[0] == m.RUNS_KEPT + 3 and kept[-1] == 4 and len(kept) == m.RUNS_KEPT
    assert store.insert_run(aid, "boot_1")["number"] == m.RUNS_KEPT + 4
