
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest
from structlog.testing import capture_logs

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_wsapi_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_wsapi_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.api.auth_routes import router as auth_router
from src.config import settings


@pytest.fixture()
def config_path(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"projects": [], "agents": {}}, indent=2))
    monkeypatch.setattr(settings, "auth_config_file", str(path))
    settings._auth_config_cache = None
    yield path
    settings._auth_config_cache = None


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(auth_router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: True
    return TestClient(app)


def _read(path: Path) -> dict:
    return json.loads(path.read_text())




def test_get_reports_unset_workspace_rather_than_omitting_it(client, config_path):
    body = client.get("/api/v1/config/settings").json()
    assert body["workspace"] == {
        "development_root": "",
        "default_shell": "",
        "default_editor": "",
        "env": {},
    }


def test_get_separates_the_bind_preference_from_the_address_in_force(
    client, config_path
):
    prefs = client.get("/api/v1/config/settings").json()["server_prefs"]
    assert "bind_host" in prefs
    assert "effective_bind_host" in prefs
    assert prefs["restart_required"] is True


def test_the_address_in_force_is_the_startup_record_not_the_configured_host(
    client, config_path, monkeypatch
):
    from src.config import settings

    monkeypatch.setenv("CLOUDE_BOUND_HOST", "127.0.0.1")
    monkeypatch.setattr(settings, "host", "0.0.0.0", raising=False)

    prefs = client.get("/api/v1/config/settings").json()["server_prefs"]
    assert prefs["effective_bind_host"] == "127.0.0.1"


def test_an_unmeasured_bind_is_null_rather_than_the_configured_host(
    client, config_path, monkeypatch
):
    from src.config import settings

    monkeypatch.delenv("CLOUDE_BOUND_HOST", raising=False)
    monkeypatch.setattr(settings, "host", "0.0.0.0", raising=False)

    prefs = client.get("/api/v1/config/settings").json()["server_prefs"]
    assert prefs["effective_bind_host"] is None


def test_get_says_tls_is_unavailable_rather_than_off(client, config_path):
    prefs = client.get("/api/v1/config/settings").json()["server_prefs"]
    assert prefs["tls_available"] is False




def test_saving_a_development_root_persists_it(client, config_path, tmp_path):
    resp = client.patch(
        "/api/v1/config/settings",
        json={"workspace": {"development_root": str(tmp_path)}},
    )
    assert resp.status_code == 200
    assert _read(config_path)["workspace"]["development_root"] == str(tmp_path)


def test_saving_env_replaces_the_whole_map_so_a_row_can_be_deleted(
    client, config_path
):
    client.patch(
        "/api/v1/config/settings", json={"workspace": {"env": {"A": "1", "B": "2"}}}
    )
    client.patch("/api/v1/config/settings", json={"workspace": {"env": {"A": "1"}}})
    assert _read(config_path)["workspace"]["env"] == {"A": "1"}


def test_an_omitted_field_is_left_untouched(client, config_path, tmp_path):
    client.patch(
        "/api/v1/config/settings",
        json={"workspace": {"development_root": str(tmp_path)}},
    )
    client.patch(
        "/api/v1/config/settings", json={"workspace": {"default_editor": "sh"}}
    )
    stored = _read(config_path)["workspace"]
    assert stored["development_root"] == str(tmp_path)
    assert stored["default_editor"].endswith("sh")


def test_a_warned_name_is_saved_and_named_back(client, config_path):
    resp = client.patch(
        "/api/v1/config/settings", json={"workspace": {"env": {"PATH": "/x"}}}
    )
    assert resp.status_code == 200
    assert _read(config_path)["workspace"]["env"] == {"PATH": "/x"}
    warnings = resp.json()["workspace_warnings"]
    assert len(warnings) == 1 and "PATH" in warnings[0]


def test_no_warnings_on_an_ordinary_name(client, config_path):
    resp = client.patch(
        "/api/v1/config/settings", json={"workspace": {"env": {"EDITOR": "vi"}}}
    )
    assert resp.json()["workspace_warnings"] == []


def test_bind_preference_persists(client, config_path):
    resp = client.patch(
        "/api/v1/config/settings", json={"server_prefs": {"bind_host": "0.0.0.0"}}
    )
    assert resp.status_code == 200
    assert _read(config_path)["server_prefs"]["bind_host"] == "0.0.0.0"


def test_tls_preference_persists_even_though_it_is_not_in_force(
    client, config_path
):
    client.patch(
        "/api/v1/config/settings", json={"server_prefs": {"tls_preferred": True}}
    )
    assert _read(config_path)["server_prefs"]["tls_preferred"] is True


def test_developer_mode_is_off_by_default_and_persists_and_is_read_back(client, config_path):
    from src.cplugs.host import developer_mode

    assert client.get("/api/v1/config/settings").json()["server_prefs"]["developer_mode"] is False
    assert developer_mode.is_on() is False
    resp = client.patch("/api/v1/config/settings", json={"server_prefs": {"developer_mode": True}})
    assert resp.status_code == 200 and resp.json()["server_prefs"]["developer_mode"] is True
    assert _read(config_path)["server_prefs"]["developer_mode"] is True
    assert developer_mode.is_on() is True


def _patch_and_capture_reason(client, payload: dict):
    with capture_logs() as logs:
        resp = client.patch("/api/v1/config/settings", json=payload)
    reasons = [entry["reason"] for entry in logs if entry.get("event") == "workspace_settings_rejected"]
    assert len(reasons) == 1, f"expected one workspace_settings_rejected event, got {logs}"
    return resp, reasons[0]




def test_a_missing_development_root_is_refused_and_named(
    client, config_path, tmp_path
):
    missing = tmp_path / "not-there"
    resp, reason = _patch_and_capture_reason(client, {"workspace": {"development_root": str(missing)}})
    assert resp.status_code == 400
    assert "does not exist" in reason and str(missing) in reason
    assert resp.json()["detail"]["code"] == "settings_invalid"
    assert str(tmp_path) not in str(resp.json()["detail"])
    assert "workspace" not in _read(config_path)


def test_a_non_executable_shell_is_refused(client, config_path, tmp_path):
    fake = tmp_path / "sh"
    fake.write_text("")
    fake.chmod(0o644)
    resp, reason = _patch_and_capture_reason(client, {"workspace": {"default_shell": str(fake)}})
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "settings_invalid"
    assert "not executable" in reason


def test_a_bad_env_name_is_refused_and_named(client, config_path):
    resp, reason = _patch_and_capture_reason(client, {"workspace": {"env": {"1BAD": "x"}}})
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "settings_invalid"
    assert "1BAD" in reason


def test_the_reserved_prefix_is_refused(client, config_path):
    resp, reason = _patch_and_capture_reason(client, {"workspace": {"env": {"CLOUDECODE_HOOK_TOKEN": "x"}}})
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "settings_invalid"
    assert "reserved" in reason


def test_a_refusal_writes_nothing_at_all(client, config_path, tmp_path):
    before = config_path.read_text()
    client.patch(
        "/api/v1/config/settings",
        json={
            "workspace": {
                "development_root": str(tmp_path),
                "env": {"BAD NAME": "x"},
            }
        },
    )
    assert config_path.read_text() == before


def test_an_unknown_workspace_key_is_rejected_not_merged(client, config_path):
    resp = client.patch(
        "/api/v1/config/settings", json={"workspace": {"nonsense": "x"}}
    )
    assert resp.status_code == 422




def test_an_older_build_ignores_these_keys_rather_than_crashing(config_path):
    from pydantic import BaseModel

    class OldAuthConfig(BaseModel):
        model_config = {"extra": "ignore"}
        config_version: int = 4

    parsed = OldAuthConfig(
        **{
            "config_version": 4,
            "workspace": {"development_root": "/x"},
            "server_prefs": {"bind_host": "0.0.0.0"},
        }
    )
    assert parsed.config_version == 4


def test_a_write_preserves_unknown_top_level_keys(client, config_path):
    data = _read(config_path)
    data["some_future_block"] = {"x": 1}
    config_path.write_text(json.dumps(data))
    settings._auth_config_cache = None

    client.patch(
        "/api/v1/config/settings", json={"workspace": {"env": {"A": "1"}}}
    )
    assert _read(config_path)["some_future_block"] == {"x": 1}


def test_no_config_version_bump_accompanies_this_feature(client, config_path):
    client.patch(
        "/api/v1/config/settings", json={"workspace": {"env": {"A": "1"}}}
    )
    assert "config_version" not in _read(config_path)
