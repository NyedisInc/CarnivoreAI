from __future__ import annotations

import asyncio
import sqlite3
from types import SimpleNamespace

import pytest

from src.core.app_alerts import ddl, service
from src.core.automations import models as m
from src.core.automations import recipes
from src.core.automations.targets import recipe as recipe_target
from src.core.notifications import types
from src.core.notifications.sources import alerts as alert_source


@pytest.fixture
def world(tmp_path, monkeypatch):
    path = tmp_path / "alerts.db"
    with sqlite3.connect(path) as db:
        ddl.apply_v50(db)

    def connect(_db_path):
        conn = sqlite3.connect(path)
        return conn
    monkeypatch.setattr(service, "_connect", connect)
    monkeypatch.setattr(service, "_db_path", path)
    monkeypatch.setattr(service, "_publisher", None)
    monkeypatch.setattr(service, "_raised_listeners", [])
    events = []
    service.on_raised(lambda row: events.append(alert_source.event_for(row)))

    async def fake(ctx, params):
        return {"schema": "scrooge/1"}, None
    monkeypatch.setitem(recipes.REGISTRY, "scrooge", (recipes.REGISTRY["scrooge"][0], fake))

    def rows():
        with sqlite3.connect(path) as db:
            return db.execute("SELECT dedupe_key, severity, title_key, params_json, actions_json FROM app_alerts").fetchall()
    return SimpleNamespace(rows=rows, events=events)


def _run(delivery, run_id="run_1"):
    automation = {"name": "weekly scrooge", "target": {"kind": "recipe", "recipe": "scrooge", "params": {}}, "delivery": delivery}
    return asyncio.run(recipe_target.run(SimpleNamespace(app_state=None), automation, {"run_id": run_id}))


def test_delivery_due_raises_one_in_app_alert(world):
    assert _run({"notify": True, "notify_on": "report"}).status == m.SUCCEEDED
    [(key, severity, title_key, params, actions)] = world.rows()
    assert key == "automation.report.run_1" and severity == "info" and title_key == "app_alert.automation.report.title"
    assert '"weekly scrooge"' in params and '"href": "#automations/run/run_1"' in actions
    assert [e.type_id for e in world.events] == ["automation_report"] and types.is_registered("automation_report")

    _run({"notify": False, "notify_on": "report"}, run_id="run_2")
    _run({"notify": True, "notify_on": "failure"}, run_id="run_3")
    assert len(world.rows()) == 1


def test_failed_blueprint_run_raises_one_alert(world, tmp_path, monkeypatch):
    from src.core.automations.store import AutomationStore
    from src.core.automations.store_schema import storage_for
    from src.core.automations import targets
    from src.core.automations.targets import blueprint
    monkeypatch.setitem(targets.RUNNERS, "blueprint_launch", blueprint.run)
    monkeypatch.setitem(targets.VALIDATORS, "blueprint_launch", lambda target: None)
    store = AutomationStore(storage_for(tmp_path))
    target = {"kind": "blueprint_launch", "blueprint_uuid": "bp-1", "members": None}
    automation = store.create(name="nightly", cron="0 7 * * *", target=target, enabled=False)
    run = store.insert_run(automation["automation_id"], "boot")
    blueprint.tell_failed(store, run)
    [(key, severity, title_key, params, actions)] = world.rows()
    assert key == f"automation.failed.{run['run_id']}" and severity == "warn" and title_key == "app_alert.automation.failed.title"
    assert '"nightly"' in params and [e.type_id for e in world.events] == ["automation_failed"]


def test_scheduler_decided_failure_raises_one_alert(world):
    automation = {"name": "nightly backup", "target": {"kind": "command"}, "delivery": {"notify": True, "notify_on": None}}
    assert recipe_target.tell_failure(automation, "run_9") is True
    [(key, severity, _title, params, _actions)] = world.rows()
    assert key == "automation.failed.run_9" and severity == "warn" and '"nightly backup"' in params
    assert recipe_target.tell_failure({**automation, "delivery": {"notify": False}}, "run_10") is False
    assert len(world.rows()) == 1


def test_sequence_tells_once_through_the_alert(world):
    from src.core.automations.targets import sequence

    automation = {"name": "two step", "target": {"kind": "sequence"}, "delivery": {"notify": True, "notify_on": None}}
    sequence._tell_once(automation, {"run_id": "run_s"}, m.RunOutcome(status=m.FAILED, reason="step_failed"))
    [(key, severity, _title, params, _actions)] = world.rows()
    assert key == "automation.failed.run_s" and severity == "warn" and '"two step"' in params


def test_send_notification_raises_its_own_notice_alert(world):
    from src.core.automations import system_actions

    answer, _ = asyncio.run(system_actions.send_notification(None, system_actions.NotifyParams(text="backups done")))
    assert answer == {"action": "send_notification", "sent": True}
    [(key, severity, title_key, params, actions)] = world.rows()
    assert key.startswith("automation.notice.") and severity == "info" and title_key == "app_alert.automation.notice.title"
    assert '"backups done"' in params and '"href": "#automations"' in actions
    assert [e.type_id for e in world.events] == ["automation_notice"] and types.is_registered("automation_notice")
