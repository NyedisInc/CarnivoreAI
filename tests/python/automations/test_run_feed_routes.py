from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_rf_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_rf_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

import src.config  # noqa: E402,F401
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.api import automation_routes  # noqa: E402
from src.api.auth import require_auth  # noqa: E402
from src.core.automations import models as m  # noqa: E402
from src.core.automations import run_feed, session_tree, targets  # noqa: E402
from src.core.automations.store import AutomationStore  # noqa: E402
from src.core.automations.store_schema import storage_for  # noqa: E402

NOW = 1_800_000_000.0
H, D = 3600.0, 86400.0
LIVE_UUID, ASLEEP_UUID = "uuid-live-0001", "uuid-asleep-0002"
FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "automations" / "session_tree_cases.json"
INPUTS = {"projects": [{"id": 1, "name": "api"}, {"id": 2, "name": "site"}],
          "sessions": [{"session_uuid": LIVE_UUID, "tmux_name": "cloude_live", "name": None, "project_id": 1, "archived_at": None},
                       {"session_uuid": ASLEEP_UUID, "tmux_name": "cloude_asleep", "name": None, "project_id": 2, "archived_at": None}]}
SCROOGE = {"kind": "recipe", "recipe": "scrooge"}
FULL = {"stdout": "hello"}
BLANK = {"stdout": " "}


async def _runner(ctx, automation, run):
    return m.RunOutcome()


def _insert(conn, key, aid, number, status, trigger, host, *, ended=None, started=None, slot=None, report=None, empty=None):
    text = None if report is None else json.dumps(report)
    conn.execute("INSERT INTO runs (run_id, automation_id, trigger, status, slot_at, started_at, ended_at, created_at, report, "
                 "report_bytes, output_empty, number, host) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 (f"run_{key}", aid, trigger, status, slot, started, ended, NOW - 20 * D, text, len(text.encode()) if text else 0,
                  empty, number, host))


@pytest.fixture
def world(tmp_path, monkeypatch):
    for kind in m.TARGET_KINDS:
        monkeypatch.setitem(targets.RUNNERS, kind, _runner)
    store = AutomationStore(storage_for(tmp_path), clock=lambda: NOW, notify=lambda _t: None)
    app = FastAPI()
    app.include_router(automation_routes.router)
    app.state.automation_store = store
    app.dependency_overrides[require_auth] = lambda: None
    monkeypatch.setattr(session_tree, "read_inputs", lambda: INPUTS)
    msg = {"kind": "session_message", "session_uuid": LIVE_UUID, "text": "hi", "if_gone": "fail"}
    ids = {"alpha": store.create(name="alpha", cron="0 7 * * 1", target=SCROOGE, project_id=1)["automation_id"],
           "beta": store.create(name="beta", cron="0 7 * * 1", target=msg, project_id=2)["automation_id"],
           "gamma": store.create(name="gamma", cron="0 7 * * 1", target=SCROOGE)["automation_id"],
           "delta": store.create(name="delta", cron="0 7 * * 1", target=SCROOGE, project_id=99)["automation_id"]}
    a, b, g, d = ids["alpha"], ids["beta"], ids["gamma"], ids["delta"]
    conn = store._storage.connect(True)
    _insert(conn, "a3", a, 1, "succeeded", "run_now", "mac2", started=NOW - 10 * D - 120, ended=NOW - 10 * D, report=FULL, empty=0)
    _insert(conn, "g2", g, 1, "succeeded", "schedule", "mac2", started=NOW - 5 * D - 30, ended=NOW - 5 * D, report=BLANK, empty=1)
    _insert(conn, "b2", b, 1, "skipped", "schedule", None, slot=NOW - 3 * D)
    _insert(conn, "d1", d, 1, "succeeded", "schedule", "mac1", started=NOW - 2 * D - 10, ended=NOW - 2 * D)
    _insert(conn, "a2", a, 2, "failed", "schedule", "mac1", started=NOW - 30 * H - 5, ended=NOW - 30 * H)
    _insert(conn, "g3", g, 2, "failed", "schedule", "mac2", started=NOW - 12 * H - 5, ended=NOW - 12 * H)
    _insert(conn, "a1", a, 3, "succeeded", "schedule", "mac1", started=NOW - 2 * H - 60, ended=NOW - 2 * H, report=FULL, empty=0)
    _insert(conn, "b1", b, 2, "succeeded", "schedule", "mac2", started=NOW - H - 5, ended=NOW - H)
    _insert(conn, "g1", g, 3, "waiting_on_you", "schedule", "mac1", started=NOW - H)
    _insert(conn, "b3", b, 3, "running", "run_now", "mac1", started=NOW - 300)
    conn.commit()
    conn.close()
    return SimpleNamespace(app=app, client=TestClient(app), store=store, ids=ids)


def _keys(body):
    return [r["run_id"][4:] for r in body["runs"]]


def _feed(world, **params):
    response = world.client.get("/automations/runs", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_every_filter_alone_and_together(world):
    everything = _feed(world, limit=120)
    assert _keys(everything) == ["b3", "g1", "b1", "a1", "g3", "a2", "d1", "b2", "g2", "a3"]
    assert everything["total"] == 10 and everything["next_before"] is None
    assert _keys(_feed(world, status="failed")) == ["g3", "a2"]
    assert sorted(_keys(_feed(world, status=["failed", "skipped"]))) == ["a2", "b2", "g3"]
    assert _keys(_feed(world, automation_id=world.ids["alpha"])) == ["a1", "a2", "a3"]
    assert _keys(_feed(world, automation_id=world.ids["beta"], status="succeeded")) == ["b1"]
    assert _keys(_feed(world, trigger="run_now")) == ["b3", "a3"]
    assert _keys(_feed(world, host="mac2")) == ["b1", "g3", "g2", "a3"]
    assert _keys(_feed(world, host="mac2", no_host="true")) == ["b1", "g3", "b2", "g2", "a3"]
    assert _keys(_feed(world, no_host="true")) == ["b2"]
    assert _keys(_feed(world, host=["mac1", "mac2"], status="skipped")) == []
    assert _keys(_feed(world, counter="succeeded_24h")) == ["b1", "a1"]
    assert _keys(_feed(world, counter=["failed_24h", "running"])) == ["b3", "g3"]
    assert _keys(_feed(world, counter="succeeded_7d", automation_id=world.ids["beta"])) == ["b1"]
    assert _keys(_feed(world, counter="produced_nothing_7d")) == ["b1", "d1", "g2"]
    assert _keys(_feed(world, counter="waiting_on_you")) == ["g1"]
    assert _feed(world, status="failed", limit=1)["total"] == 2
    for bad in ({"counter": "nope"}, {"include": "everything"}, {"limit": 121}, {"limit": 0}):
        assert world.client.get("/automations/runs", params=bad).status_code == 422, bad


def test_total_and_next_before_across_pages(world):
    first = _feed(world, limit=4)
    assert _keys(first) == ["b3", "g1", "b1", "a1"] and first["total"] == 10 and first["next_before"] == "run_a1"
    second = _feed(world, limit=4, before=first["next_before"])
    assert _keys(second) == ["g3", "a2", "d1", "b2"] and second["total"] == 10 and second["next_before"] == "run_b2"
    third = _feed(world, limit=4, before=second["next_before"])
    assert _keys(third) == ["g2", "a3"] and third["next_before"] is None
    exact = _feed(world, limit=5, status=["succeeded"], before="run_g1")
    assert exact["total"] == 5 and exact["next_before"] is None


def test_reports_ride_only_with_include_and_stop_at_the_budget(world):
    plain = _feed(world)
    assert all("report" not in r and "report_omitted" not in r for r in plain["runs"])
    full = {r["run_id"]: r for r in _feed(world, include="report", limit=120)["runs"]}
    assert full["run_a1"]["report"] == FULL and full["run_a1"]["report_omitted"] is False
    assert full["run_b1"]["report"] is None and full["run_b1"]["report_omitted"] is False
    big = json.dumps("x" * 1_000_000)
    conn = world.store._storage.connect(True)
    for n in range(1, 7):
        _insert(conn, f"big{n}", world.ids["gamma"], 10 + n, "succeeded", "schedule", "mac2", ended=NOW + n)
        conn.execute("UPDATE runs SET report = ?, report_bytes = ? WHERE run_id = ?", (big, len(big), f"run_big{n}"))
    conn.commit()
    conn.close()
    rows = _feed(world, include="report", limit=6)["runs"]
    assert [r["run_id"] for r in rows] == [f"run_big{n}" for n in range(6, 0, -1)]
    assert [r["report_omitted"] for r in rows] == [False] * 4 + [True] * 2
    assert all("report" in r for r in rows[:4]) and all("report" not in r for r in rows[4:])
    per_automation = world.client.get(f"/automations/{world.ids['gamma']}/runs", params={"include": "report", "limit": 6}).json()["runs"]
    assert [r["report_omitted"] for r in per_automation] == [False] * 4 + [True] * 2
    assert "report" not in world.client.get(f"/automations/{world.ids['gamma']}/runs").json()["runs"][0]
    assert world.client.get(f"/automations/{world.ids['gamma']}/runs", params={"include": "x"}).status_code == 422


def test_run_counts_answers_the_eight_counters(world):
    world.app.dependency_overrides.pop(require_auth)
    assert world.client.get("/automations/run-counts").status_code == 401
    world.app.dependency_overrides[require_auth] = lambda: None
    response = world.client.get("/automations/run-counts")
    assert response.status_code == 200, response.text
    body = response.json()
    ids = world.ids
    expected = {"succeeded_24h": (2, ["alpha", "beta"]), "failed_24h": (1, ["gamma"]),
                "succeeded_7d": (4, ["alpha", "beta", "delta", "gamma"]), "failed_7d": (2, ["alpha", "gamma"]),
                "skipped_7d": (1, ["beta"]), "produced_nothing_7d": (3, ["beta", "delta", "gamma"]),
                "running": (1, ["beta"]), "waiting_on_you": (1, ["gamma"])}
    assert set(body["counters"]) == set(expected)
    for key, (count, names) in expected.items():
        assert body["counters"][key]["count"] == count, key
        assert sorted(body["counters"][key]["automation_ids"]) == sorted(ids[n] for n in names), key
    assert body["now"] == NOW and body["hosts"] == ["mac1", "mac2"] and body["has_unrecorded_host"] is True
    assert body["next_change_at"] == NOW + 12 * H


def test_automation_rows_carry_the_table_fields(world, monkeypatch, tmp_path):
    body = world.client.get("/automations").json()
    assert isinstance(body["tz"], str) and body["tz"]
    rows = {r["name"]: r for r in body["automations"]}
    assert len(rows) == 4
    alpha = rows["alpha"]
    assert [x["run_id"] for x in alpha["recent"]] == ["run_a1", "run_a2", "run_a3"]
    assert set(alpha["recent"][0]) == {"run_id", "number", "status", "reason", "trigger", "attempt", "slot_at", "started_at", "ended_at",
                                       "skip_count", "report_bytes", "output_empty"}
    assert alpha["recent"][0]["number"] == 3 and alpha["recent"][0]["output_empty"] is False
    assert (alpha["run_count"], alpha["newest_number"], alpha["median_took_s"], alpha["spends"]) == (3, 3, 90, True)
    assert alpha["newest_output_empty"] is False and rows["gamma"]["newest_output_empty"] is True
    assert rows["delta"]["newest_output_empty"] is True
    assert rows["beta"]["newest_output_empty"] is False and rows["beta"]["median_took_s"] == 5
    assert alpha["files_under"] == {"session_uuid": None, "project_id": 1}
    assert rows["beta"]["files_under"] == {"session_uuid": LIVE_UUID, "project_id": 1}
    assert rows["gamma"]["files_under"] == {"session_uuid": None, "project_id": None}
    assert rows["delta"]["files_under"] == {"session_uuid": None, "project_id": None}
    assert "tz" not in world.client.get("/automations", params={"group_by": "session"}).json()
    link = tmp_path / "usr" / "share" / "zoneinfo" / "Europe"
    link.mkdir(parents=True)
    (tmp_path / "localtime").symlink_to(link / "Paris")
    monkeypatch.setattr(run_feed, "LOCALTIME", str(tmp_path / "localtime"))
    assert world.client.get("/automations").json()["tz"] == "Europe/Paris"
    monkeypatch.setattr(run_feed, "LOCALTIME", str(tmp_path / "missing"))
    assert world.client.get("/automations").json()["tz"] == "UTC"


def test_file_of_agrees_with_the_session_tree_fixture():
    cases = json.loads(FIXTURE.read_text())["cases"]
    assert len(cases) > 1 and any(c["expected"] for c in cases)
    checked = 0
    for case in cases:
        tree = session_tree.build_tree(case["projects"], case["sessions"], case["automations"])
        filed = {}
        for node in tree:
            for a in node["automations"]:
                filed[a["name"]] = (node["session_uuid"], node["project_id"])
            for child in node["children"]:
                for a in child["automations"]:
                    filed[a["name"]] = (child["session_uuid"], child["project_id"])
        listed = {s["session_uuid"]: s for s in case["sessions"] if s.get("session_uuid") and not s.get("archived_at")}
        project_ids = {p["id"] for p in case["projects"]}
        for a in case["automations"]:
            got = session_tree.file_of(a, listed, project_ids)
            assert (got["session_uuid"], got["project_id"]) == filed[a["name"]], (case["name"], a["name"])
            checked += 1
    assert checked > 0
