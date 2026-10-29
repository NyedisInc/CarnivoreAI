from __future__ import annotations

import asyncio
import os
import sqlite3
import tempfile
from types import SimpleNamespace

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_rd_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_rd_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

import src.config  # noqa: E402,F401
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.api import automation_run_routes  # noqa: E402
from src.api.auth import require_auth  # noqa: E402
from src.core.app_alerts import ddl, service  # noqa: E402
from src.core.automations import delivered, recipes, targets  # noqa: E402
from src.core.automations.store import AutomationStore  # noqa: E402
from src.core.automations.store_schema import storage_for  # noqa: E402
from src.core.automations.targets import recipe as recipe_target  # noqa: E402
from src.core.automations import models as m  # noqa: E402

TARGET = {"kind": "recipe", "recipe": "scrooge", "params": {}}


@pytest.fixture
def world(tmp_path, monkeypatch):
    path = tmp_path / "alerts.db"
    with sqlite3.connect(path) as db:
        ddl.apply_v50(db)
    monkeypatch.setattr(service, "_connect", lambda _p: sqlite3.connect(path))
    monkeypatch.setattr(service, "_db_path", path)
    monkeypatch.setattr(service, "_publisher", None)
    monkeypatch.setattr(service, "_raised_listeners", [])
    monkeypatch.setattr(delivered, "alerts_db_path", lambda: path)

    async def boom(ctx, params):
        raise recipes.RecipeFailed("no_data")
    monkeypatch.setitem(recipes.REGISTRY, "scrooge", (recipes.REGISTRY["scrooge"][0], boom))
    for kind in m.TARGET_KINDS:
        monkeypatch.setitem(targets.RUNNERS, kind, recipe_target.run)
    store = AutomationStore(storage_for(tmp_path))
    app = FastAPI()
    app.include_router(automation_run_routes.router)
    app.dependency_overrides[require_auth] = lambda: None
    app.state.automation_store = store

    def fail_one(delivery):
        automation = store.create(name="weekly scrooge", cron="0 7 * * *", target=TARGET, delivery=delivery, enabled=False)
        run = store.insert_run(automation["automation_id"], "boot")
        asyncio.run(recipe_target.run(SimpleNamespace(app_state=None, store=store), automation, run))
        return run["run_id"]

    def alert_ids():
        with sqlite3.connect(path) as db:
            return [r[0] for r in db.execute("SELECT id FROM app_alerts")]
    return SimpleNamespace(store=store, client=TestClient(app), path=path, fail_one=fail_one, alert_ids=alert_ids)


def _read(world, run_id):
    return world.client.get(f"/automations/runs/{run_id}").json()


def test_run_records_its_alert_and_the_read_answers_its_state(world):
    run_id = world.fail_one({"notify": True, "notify_on": "failure"})
    assert len(world.alert_ids()) == 1
    stored = world.store.run(run_id)["delivered"]
    assert stored["channel"] == "alert" and stored["kind"] == "failed"
    assert stored["alert_key"] == f"automation.failed.{run_id}" and isinstance(stored["at"], float)
    assert "state" not in stored

    body = _read(world, run_id)["delivered"]
    assert body["state"] == "active" and body["state_at"] is None

    service.dismiss(world.path, world.alert_ids()[0])
    body = _read(world, run_id)["delivered"]
    assert body["state"] == "dismissed" and isinstance(body["state_at"], float)

    with sqlite3.connect(world.path) as db:
        db.execute("DELETE FROM app_alerts")
    body = _read(world, run_id)["delivered"]
    assert body["state"] == "gone" and body["state_at"] is None


def test_snoozed_alert_reads_snoozed_with_its_wake_time(world):
    run_id = world.fail_one({"notify": True, "notify_on": "failure"})
    service.snooze(world.path, world.alert_ids()[0], 30)
    body = _read(world, run_id)["delivered"]
    assert body["state"] == "snoozed" and isinstance(body["state_at"], float)


def test_delivery_off_leaves_delivered_null(world):
    run_id = world.fail_one({"notify": False})
    assert world.alert_ids() == []
    assert world.store.run(run_id)["delivered"] is None
    assert _read(world, run_id)["delivered"] is None
