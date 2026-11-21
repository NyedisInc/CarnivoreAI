
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.api import automation_log_routes, automation_routes
from tests.python.route_tests.harness import client_for


@pytest.fixture
def config_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from src.config import settings

    path = tmp_path / "config.json"
    path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(settings, "auth_config_file", str(path), raising=False)
    return path


def test_preview_lists_the_next_five_fires_of_a_good_cron() -> None:
    resp = client_for(automation_routes.router).post("/automations/schedule/preview", json={"cron": "0 9 * * *"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True and len(body["fires"]) == 5
    assert {"utc", "local"} <= set(body["fires"][0])


@pytest.mark.parametrize("cron,reason", [("* * * * *", "interval_under_15_min"), ("not a cron", "cron_invalid")])
def test_preview_refuses_what_the_scheduler_would_refuse(cron: str, reason: str) -> None:
    resp = client_for(automation_routes.router).post("/automations/schedule/preview", json={"cron": cron})
    assert resp.status_code == 200
    assert resp.json() == {"ok": False, "reason": reason}


def test_preview_needs_auth() -> None:
    resp = client_for(automation_routes.router, signed_in=False).post("/automations/schedule/preview", json={"cron": "0 9 * * *"})
    assert resp.status_code in (401, 403)


def test_log_settings_put_stores_the_rotation_in_config_json(config_file: Path) -> None:
    client = client_for(automation_log_routes.router)
    resp = client.put("/automation-log/settings", json={"rotate": "daily", "max_mb": 20, "keep": 3})
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"rotate": "daily", "max_mb": 20, "keep": 3}
    assert "daily" in json.dumps(json.loads(config_file.read_text()))


def test_log_settings_get_answers_the_rotation_shape() -> None:
    body = client_for(automation_log_routes.router).get("/automation-log/settings").json()
    assert set(body) == {"rotate", "max_mb", "keep"}


@pytest.mark.parametrize("body", [{"rotate": "weekly"}, {"max_mb": 0}, {"keep": 51}, {"surprise": 1}])
def test_log_settings_put_rejects_out_of_range_values(config_file: Path, body: dict) -> None:
    resp = client_for(automation_log_routes.router).put("/automation-log/settings", json=body)
    assert resp.status_code == 422
    assert config_file.read_text() == "{}"


def test_log_settings_put_is_a_503_when_config_json_is_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from src.config import settings

    missing = tmp_path / "absent.json"
    monkeypatch.setattr(settings, "auth_config_file", str(missing), raising=False)
    resp = client_for(automation_log_routes.router).put("/automation-log/settings", json={"rotate": "size"})
    assert resp.status_code == 503
    assert resp.json()["detail"]["code"] == "config_unwritable"
    assert not missing.exists()


def test_log_settings_need_auth() -> None:
    client = client_for(automation_log_routes.router, signed_in=False)
    assert client.get("/automation-log/settings").status_code in (401, 403)
    assert client.put("/automation-log/settings", json={}).status_code in (401, 403)
