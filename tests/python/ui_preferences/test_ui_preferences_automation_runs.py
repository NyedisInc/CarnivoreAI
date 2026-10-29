
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_ar_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_ar_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import preferences_routes
from src.api.preferences_routes import router as preferences_router
from src.core.ui_preferences_store import UiPreferencesStore

SEEN = "2026-10-16T12:30:05Z"
READ = ["run_a1", "run-b2", "C3"]


class _Manager:

    async def broadcast(self, text: str) -> None:
        json.loads(text)


@pytest.fixture
def client(tmp_path: Path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"agents": {"a": 1}}))
    app = FastAPI()
    app.include_router(preferences_router, prefix="/api/v1")
    app.state.ui_preferences_store = UiPreferencesStore(lambda: path)
    app.state.connection_manager = _Manager()
    app.dependency_overrides[preferences_routes.require_auth] = lambda: True
    with TestClient(app) as test_client:
        yield test_client


def _patch(client, changes, revision=None):
    body = {"changes": changes}
    if revision is not None:
        body["expected_revision"] = revision
    return client.patch("/api/v1/preferences", json=body)


def test_absent_before_any_write_then_round_trip_and_null_unsets(client):
    before = client.get("/api/v1/preferences").json()
    for field in ("automation_runs_seen_at", "automation_runs_read"):
        assert field not in before["values"]
    answer = _patch(client, {"automation_runs_seen_at": SEEN, "automation_runs_read": READ}, before["revision"])
    assert answer.status_code == 200, answer.text
    values = client.get("/api/v1/preferences").json()["values"]
    assert values["automation_runs_seen_at"] == SEEN and values["automation_runs_read"] == READ
    fractional = "2026-10-16T12:30:05.123Z"
    assert _patch(client, {"automation_runs_seen_at": fractional}).json()["values"]["automation_runs_seen_at"] == fractional
    assert _patch(client, {"automation_runs_read": []}).json()["values"]["automation_runs_read"] == []
    cleared = _patch(client, {"automation_runs_seen_at": None, "automation_runs_read": None}).json()["values"]
    assert "automation_runs_seen_at" not in cleared and "automation_runs_read" not in cleared


@pytest.mark.parametrize(
    "changes, leaked",
    [
        ({"automation_runs_seen_at": "yesterdayish"}, "yesterdayish"),
        ({"automation_runs_seen_at": "2026-10-16T12:30:05+02:00"}, "+02:00"),
        ({"automation_runs_seen_at": "2026-10-16T12:30:05"}, "2026-10-16T12:30:05"),
        ({"automation_runs_seen_at": "2026-13-45T99:99:99Z"}, "2026-13-45"),
        ({"automation_runs_read": [f"r{i}" for i in range(501)]}, "r500"),
        ({"automation_runs_read": ["dupe_id", "dupe_id"]}, "dupe_id"),
        ({"automation_runs_read": ["bad id!"]}, "bad id!"),
        ({"automation_runs_read": ["x" * 81]}, "x" * 81),
        ({"automation_runs_read": [""]}, "''"),
    ],
)
def test_a_bad_value_is_a_400_that_does_not_quote_it(client, changes, leaked):
    answer = _patch(client, changes)
    assert answer.status_code == 400
    assert leaked not in str(answer.json()["detail"])


def test_five_hundred_unique_ids_are_accepted(client):
    ids = [f"r{i}" for i in range(500)]
    assert _patch(client, {"automation_runs_read": ids}).json()["values"]["automation_runs_read"] == ids
