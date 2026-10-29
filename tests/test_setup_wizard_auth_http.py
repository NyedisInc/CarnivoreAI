
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_setuphttp_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_setuphttp_logs_"))
os.environ.setdefault("TOTP_SECRET", "JBSWY3DPEHPK3PXP")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-not-a-real-one-32b")

from src.api.auth import create_access_token  # noqa: E402
import src.api.setup_routes as setup_routes_module  # noqa: E402
from src.api.setup_routes import (  # noqa: E402
    page_router as setup_page_router,
    router as setup_router,
)
from src.config import settings  # noqa: E402


@pytest.fixture()
def instance(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"agents": {}}, indent=2))
    monkeypatch.setattr(settings, "auth_config_file", str(config_path))
    monkeypatch.setattr(settings, "host", "0.0.0.0")
    state_dir = tmp_path / "state"
    state_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(setup_routes_module, "_state_dir", lambda: state_dir)
    settings._auth_config_cache = None

    app = FastAPI()
    app.include_router(setup_router, prefix="/api/v1")
    app.include_router(setup_page_router)

    class Instance:
        client = TestClient(
            app,
            base_url=f"http://127.0.0.1:{settings.port}",
            client=("127.0.0.1", 50000),
        )
        remote_client = TestClient(app)
        path = config_path

        @staticmethod
        def complete_setup():
            (tmp_path / ".totp_paired").write_text("")

        @staticmethod
        def valid_token() -> str:
            token, _ = create_access_token()
            return token

    yield Instance()
    settings._auth_config_cache = None


class TestProtectedOnceSetupIsComplete:

    def test_unauthenticated_state_is_refused_after_setup(self, instance):
        instance.complete_setup()
        resp = instance.client.get("/api/v1/setup/state")
        assert resp.status_code == 401, resp.text

    def test_unauthenticated_apply_is_refused_after_setup(self, instance):
        instance.complete_setup()
        resp = instance.client.post("/api/v1/setup/apply", json={"decisions": []})
        assert resp.status_code == 401, resp.text

    def test_a_garbage_token_is_refused(self, instance):
        instance.complete_setup()
        resp = instance.client.get(
            "/api/v1/setup/state",
            headers={"Authorization": "Bearer not-a-real-token"},
        )
        assert resp.status_code == 401, resp.text

    def test_a_valid_token_is_accepted(self, instance):
        instance.complete_setup()
        resp = instance.client.get(
            "/api/v1/setup/state",
            headers={"Authorization": f"Bearer {instance.valid_token()}"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["mode"] == "upgrade_review"

    def test_refusal_survives_config_claiming_setup_is_done(self, instance):
        instance.complete_setup()
        instance.path.write_text(
            json.dumps({"setup_complete": False, "first_run": True, "agents": {}})
        )
        resp = instance.client.get("/api/v1/setup/state")
        assert resp.status_code == 401, resp.text


class TestOpenWhileSetupIsIncomplete:

    def test_state_loads_without_a_credential(self, instance):
        resp = instance.client.get("/api/v1/setup/state")
        assert resp.status_code == 200, resp.text
        assert resp.json()["mode"] == "first_run"

    def test_it_reports_the_lockdown_rather_than_the_configured_address(
        self, instance, monkeypatch
    ):
        monkeypatch.setenv("CLOUDE_BOUND_HOST", "127.0.0.1")
        body = instance.client.get("/api/v1/setup/state").json()
        assert body["exposure"]["effective_host"] == "127.0.0.1"
        assert body["exposure"]["configured_host"] == "0.0.0.0"
        assert body["exposure"]["locked_down"] is True
        assert body["exposure"]["restart_required"] is True

    def test_an_unmeasured_bind_is_reported_as_unknown(self, instance, monkeypatch):
        monkeypatch.delenv("CLOUDE_BOUND_HOST", raising=False)
        body = instance.client.get("/api/v1/setup/state").json()
        assert body["exposure"]["effective_host"] is None
        assert body["exposure"]["effective_host_known"] is False
        assert body["exposure"]["restart_required"] is None
        assert body["exposure"]["configured_host"] == "0.0.0.0"

    def test_checks_preserve_the_third_outcome_over_the_wire(self, instance):
        instance.path.write_text("{not json at all")
        body = instance.client.get("/api/v1/setup/state").json()
        config_check = next(
            c for c in body["setup"]["checks"] if c["key"] == "config_file"
        )
        assert config_check["passed"] is None
        assert body["setup"]["status"] == "undetermined"

    def test_an_unreadable_config_is_not_reported_as_a_clean_plan(self, instance):
        instance.path.write_text("{not json at all")
        plan = instance.client.get("/api/v1/setup/state").json()["plan"]
        assert plan["unreadable"]
        assert plan["items"] == []


class TestRemoteVisitorBeforePairing:

    def test_a_non_loopback_client_is_refused_with_the_reason(self, instance):
        resp = instance.remote_client.get("/api/v1/setup/state")
        assert resp.status_code == 403, resp.text
        assert resp.json()["detail"]["reason"] == "setup_local_only"


class TestTheShell:

    def test_shell_is_served(self, instance):
        resp = instance.client.get("/setup")
        assert resp.status_code == 200
        assert "wizard-body" in resp.text

    def test_shell_leaks_no_state_after_setup(self, instance):
        instance.complete_setup()
        text = instance.client.get("/setup").text
        for leak in ("0.0.0.0", "JBSWY3DPEHPK3PXP", "totp_paired", "config.json"):
            assert leak not in text, f"the shell leaked {leak}"

    def test_the_mode_cannot_be_chosen_by_the_caller(self, instance):
        instance.complete_setup()
        for query in ("?mode=first_run", "?setup=1", "?first_run=true"):
            resp = instance.client.get("/api/v1/setup/state" + query)
            assert resp.status_code == 401, query


class TestPerItemDecisions:

    def test_an_unmentioned_item_is_never_changed(self, instance):
        original = json.loads(instance.path.read_text())
        original["jwt_expiry_minutes"] = 99
        instance.path.write_text(json.dumps(original))

        resp = instance.client.post("/api/v1/setup/apply", json={"decisions": []})
        assert resp.status_code == 200
        assert json.loads(instance.path.read_text())["jwt_expiry_minutes"] == 99

    def test_keep_leaves_the_value_alone(self, instance):
        original = json.loads(instance.path.read_text())
        original["jwt_expiry_minutes"] = 99
        instance.path.write_text(json.dumps(original))

        instance.client.post(
            "/api/v1/setup/apply",
            json={"decisions": [{"path": "jwt_expiry_minutes", "choice": "keep"}]},
        )
        assert json.loads(instance.path.read_text())["jwt_expiry_minutes"] == 99

    def test_take_new_adopts_only_that_item(self, instance):
        original = json.loads(instance.path.read_text())
        original["jwt_expiry_minutes"] = 99
        original["template_path"] = "/mine"
        instance.path.write_text(json.dumps(original))

        resp = instance.client.post(
            "/api/v1/setup/apply",
            json={"decisions": [{"path": "jwt_expiry_minutes", "choice": "take_new"}]},
        )
        assert resp.status_code == 200, resp.text
        written = json.loads(instance.path.read_text())
        assert written["jwt_expiry_minutes"] != 99
        assert written["template_path"] == "/mine"

    def test_apply_writes_a_backup_before_touching_anything(self, instance):
        original = json.loads(instance.path.read_text())
        original["jwt_expiry_minutes"] = 99
        instance.path.write_text(json.dumps(original))

        body = instance.client.post(
            "/api/v1/setup/apply",
            json={"decisions": [{"path": "jwt_expiry_minutes", "choice": "take_new"}]},
        ).json()
        assert body["backup"], body
        assert "BACKED_UP" in body["backup"]

    def test_an_invalid_choice_is_rejected(self, instance):
        resp = instance.client.post(
            "/api/v1/setup/apply",
            json={"decisions": [{"path": "x", "choice": "delete_everything"}]},
        )
        assert resp.status_code in (400, 422)
