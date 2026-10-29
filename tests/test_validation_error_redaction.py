
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest
import structlog

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_ver_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_ver_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.config import settings

CANARY = "zz-canary-value"

ACCOUNT_BODY = {
    "name": "Max main",
    "provider": "claude",
    "claude_config_dir": "~/.claude",
    "managed": False,
}

ACCOUNTS_URL = "/api/v1/provider-ledger/accounts"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from src.main import app

    path = tmp_path / "config.json"
    path.write_text(json.dumps({"projects": [], "agents": {}}, indent=2))
    monkeypatch.setattr(settings, "auth_config_file", str(path), raising=False)
    settings._auth_config_cache = None

    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(require_auth, None)
        settings._auth_config_cache = None


class TestTheValidationBodyNeverEchoesWhatWasSent:

    def test_a_refused_key_does_not_come_back_with_its_value(self, client):
        answer = client.put(
            f"{ACCOUNTS_URL}/max-main", json={**ACCOUNT_BODY, "token": CANARY}
        )

        assert answer.status_code == 400
        assert CANARY not in answer.text

    def test_it_still_names_the_key_it_refused(self, client):
        answer = client.put(
            f"{ACCOUNTS_URL}/max-main", json={**ACCOUNT_BODY, "token": CANARY}
        )

        entries = answer.json()["detail"]
        assert entries, "a refusal with no entries tells the form nothing"
        assert entries[0]["loc"] == ["body", "token"]
        assert entries[0]["msg"]
        assert entries[0]["type"] == "extra_forbidden"

    def test_no_entry_carries_an_input_or_a_context(self, client):
        answer = client.put(
            f"{ACCOUNTS_URL}/max-main", json={**ACCOUNT_BODY, "token": CANARY}
        )

        for entry in answer.json()["detail"]:
            assert set(entry) <= {"loc", "msg", "type"}, entry

    def test_the_canary_reaches_no_log_record_either(self, client):
        with structlog.testing.capture_logs() as captured:
            answer = client.put(
                f"{ACCOUNTS_URL}/max-main", json={**ACCOUNT_BODY, "token": CANARY}
            )

        assert answer.status_code == 400
        assert captured, "the request logged nothing, so the search proves nothing"
        assert CANARY not in repr(captured)

    def test_a_body_the_route_validates_itself_is_still_a_422(self, client):
        answer = client.put(f"{ACCOUNTS_URL}/Max_Main", json=ACCOUNT_BODY)

        assert answer.status_code == 422
        assert answer.json()["detail"]["code"] == "invalid_account"
