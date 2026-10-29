
from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import List

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.api import app_alerts_routes as routes  # noqa: E402
from src.api.auth import require_auth  # noqa: E402
from src.core.app_alerts import kinds, recheck, service  # noqa: E402
from src.core.db import db_path_for  # noqa: E402
from src.core.db_migration import ensure_db_migrated  # noqa: E402

BASE = "/api/v1/alerts"


@pytest.fixture()
def world(tmp_path: Path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    assert ensure_db_migrated(state).status == "ok"
    db = db_path_for(state)
    service.configure(db, None)
    monkeypatch.setattr(routes, "_db_path", lambda: db)
    monkeypatch.setattr(routes, "_state_dir", lambda: state)
    app = FastAPI()
    app.include_router(routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: None
    yield SimpleNamespace(client=TestClient(app), db=db, state=state)
    service.configure(None, None)


def _usb_alert(world) -> dict:
    return service.raise_alert("backup_health.usb_backup", source="backup_health", severity="warn",
                               title_key="app_alert.backup_health.usb_stale.title", db_path=world.db)


def test_the_listing_carries_source_kind_and_declared_actions(world):
    row = _usb_alert(world)
    listed = world.client.get(BASE).json()["alerts"][0]
    assert listed["id"] == row["id"] and listed["kind"] == "needs_you"
    assert listed["source_label_key"] == "app_alert.source.backup_health"
    assert [a["id"] for a in listed["actions"]] == ["recheck", "open_backups"]
    assert listed["actions"][0]["route"] == f"/alerts/{row['id']}/recheck"


def test_recheck_runs_the_producer_and_answers_the_alert_as_it_stands(world, monkeypatch):
    row = _usb_alert(world)
    ran: List[tuple] = []

    def fake_run_checks(state_dir, db_path, **_kw):
        ran.append((state_dir, db_path))
        service.resolve("backup_health.usb_backup", db_path=db_path)

    from src.core.backup_health import runner

    monkeypatch.setattr(runner, "run_checks", fake_run_checks)
    answer = world.client.post(f"{BASE}/{row['id']}/recheck")
    assert answer.status_code == 200 and answer.json()["state"] == "resolved"
    assert ran == [(world.state, world.db)]


def test_recheck_refuses_a_kind_with_no_recheck_and_an_unknown_id(world):
    other = service.raise_alert("pipeline.llm_all_down", source="save_pipeline", severity="error",
                                title_key="app_alert.pipeline.llm_all_down.title", db_path=world.db)
    assert world.client.post(f"{BASE}/{other['id']}/recheck").status_code == 409
    assert world.client.post(f"{BASE}/9999/recheck").status_code == 404
    assert not recheck.supports("pipeline.llm_all_down")


def test_open_system_settings_opens_only_the_allow_listed_pane(world, monkeypatch):
    seen: List[list] = []
    monkeypatch.setattr(routes.sys, "platform", "darwin")
    monkeypatch.setattr(routes.subprocess, "run", lambda cmd, **_kw: seen.append(cmd) or subprocess.CompletedProcess(cmd, 0, "", ""))
    ok = world.client.post(f"{BASE}/open-system-settings", json={"pane": "full_disk_access"})
    assert ok.status_code == 200 and ok.json() == {"opened": True, "pane": "full_disk_access"}
    assert seen == [["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"]]
    assert kinds.SYSTEM_PANES["full_disk_access"] == seen[0][1]
    assert world.client.post(f"{BASE}/open-system-settings", json={"pane": "https://evil.example"}).status_code == 422


def test_open_system_settings_reports_a_failed_open_and_other_platforms(world, monkeypatch):
    monkeypatch.setattr(routes.sys, "platform", "darwin")
    monkeypatch.setattr(routes.subprocess, "run", lambda cmd, **_kw: subprocess.CompletedProcess(cmd, 1, "", "no"))
    assert world.client.post(f"{BASE}/open-system-settings", json={"pane": "full_disk_access"}).status_code == 502
    monkeypatch.setattr(routes.sys, "platform", "linux")
    assert world.client.post(f"{BASE}/open-system-settings", json={"pane": "full_disk_access"}).status_code == 501
