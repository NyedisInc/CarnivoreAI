from __future__ import annotations

import hashlib
import json
import sqlite3

from src.core.automations import models as m
from src.core.automations.store import AutomationStore
from src.core.automations.store_schema import MIGRATIONS, storage_for
from src.cplugs.sdk.storage import CplugStorage, StorageSpec

MASTER_RUNG_ONE_SHA256 = "f047adb0e5bab3e36a0ec8b64b524fa666f6196acb9a4e17164bc58409d5450e"
NOW = 1_800_000_000.0
RECIPE = {"kind": "recipe", "recipe": "scrooge", "params": {}}
DELIVERY = {"notify": True, "notify_on": None}


def _master_db(tmp_path):
    old = CplugStorage(tmp_path / "automations", StorageSpec(db="automations.db", migrations=MIGRATIONS[:1]), tmp_path)
    conn = old.connect(True)
    late_slot = NOW - m.GRACE_S - 3600
    conn.executemany("INSERT INTO automations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", [
        ("aut_on", "weekly scrooge", "weekly scrooge", 1, "0 7 * * 1", json.dumps(RECIPE), json.dumps(DELIVERY),
         late_slot, 4, "app", None, 1.0, 2.0),
        ("aut_off", "nightly", "nightly", 0, "0 3 * * *", json.dumps(RECIPE), json.dumps(DELIVERY), None, 1, "seed", "seed_k",
         1.0, 1.0),
    ])
    conn.execute("INSERT INTO runs (run_id, automation_id, trigger, slot_at, status, started_at, ended_at, report, "
                 "report_bytes, cost_usd, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                 ("run_ok", "aut_on", "schedule", 10.0, m.SUCCEEDED, 11.0, 12.0, json.dumps({"schema": "scrooge/1"}), 21, 0.42, 10.0))
    conn.execute("INSERT INTO runs (run_id, automation_id, trigger, slot_at, status, reason, skip_count, first_slot_at, "
                 "last_slot_at, ended_at, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                 ("run_skip", "aut_on", "schedule", 20.0, m.SKIPPED, m.R_MISSED, 2, 20.0, 30.0, 30.0, 20.0))
    conn.execute("INSERT INTO run_sessions (run_id, session_uuid, session_row_id, member_index) VALUES (?,?,?,?)",
                 ("run_ok", "uuid-1", 7, 0))
    conn.execute("INSERT INTO seed_tombstones VALUES (?,?)", ("seed_gone", 5.0))
    conn.commit()
    conn.close()


def test_master_rung_one_is_unchanged():
    assert hashlib.sha256(MIGRATIONS[0].encode()).hexdigest() == MASTER_RUNG_ONE_SHA256
    assert len(MIGRATIONS) == 4


def test_master_rows_survive_the_upgrade_with_skip(tmp_path):
    _master_db(tmp_path)
    store = AutomationStore(storage_for(tmp_path), clock=lambda: NOW, notify=lambda _t: None)
    on, off = store.get("aut_on"), store.get("aut_off")
    with sqlite3.connect(tmp_path / "automations" / "automations.db") as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 4
        assert db.execute("SELECT COUNT(*) FROM run_sessions").fetchone()[0] == 1
        assert db.execute("SELECT seed_key FROM seed_tombstones").fetchall() == [("seed_gone",)]
        assert db.execute("SELECT attempt FROM runs ORDER BY seq").fetchall() == [(1,), (1,)]

    assert (on["name"], on["revision"], on["enabled"], on["target"]) == ("weekly scrooge", 4, True, RECIPE)
    assert (off["name"], off["revision"], off["enabled"], off["seed_key"]) == ("nightly", 1, False, "seed_k")
    for row, creator in ((on, "app"), (off, "seed")):
        assert row["misfire"] == "skip" and row["updated_by"] == creator and row["created_actor"] == {"kind": creator}
        assert row["retry_max"] == 0 and row["max_runtime_s"] is None and row["description"] == "" and row["project_id"] is None
        assert store.changes(row["automation_id"]) == []

    runs = {r["run_id"]: r for r in store.runs("aut_on")}
    assert set(runs) == {"run_ok", "run_skip"}
    assert runs["run_ok"]["status"] == m.SUCCEEDED and runs["run_ok"]["cost_usd"] == 0.42
    assert store.run("run_ok")["report"] == {"schema": "scrooge/1"}
    assert runs["run_skip"]["skip_count"] == 2


def test_a_late_slot_on_an_upgraded_row_folds_a_skip(tmp_path):
    _master_db(tmp_path)
    store = AutomationStore(storage_for(tmp_path), clock=lambda: NOW, notify=lambda _t: None)
    assert store.claim_due(NOW, "boot_1") == []
    newest = store.runs("aut_on")[0]
    assert newest["run_id"] == "run_skip" and newest["skip_count"] == 3 and newest["reason"] == m.R_MISSED
