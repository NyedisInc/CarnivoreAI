
from __future__ import annotations

import os
import tempfile

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_psra_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_psra_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

from fastapi.testclient import TestClient  # noqa: E402

from src.api.auth import require_auth  # noqa: E402
from src.main import app  # noqa: E402

PATHS = ["/api/v1/sessions/u1/send", "/api/v1/sessions/u1/send/check"]
BODY = {"machine": "nowhere", "mode": "copy"}


def _body(path: str) -> dict:
    return BODY if path.endswith("/send") else {"machine": BODY["machine"]}


FORGED = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4In0.AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"


@pytest.mark.parametrize("path", PATHS)
def test_no_token_is_refused(path: str) -> None:
    assert TestClient(app, raise_server_exceptions=False).post(path, json=_body(path)).status_code == 401


@pytest.mark.parametrize("path", PATHS)
def test_a_peer_or_forged_token_is_refused(path: str) -> None:
    headers = {"Authorization": f"Bearer {FORGED}"}
    assert TestClient(app, raise_server_exceptions=False).post(path, json=_body(path), headers=headers).status_code == 401


@pytest.mark.parametrize("path", PATHS)
def test_the_owner_reaches_the_handler(path: str) -> None:
    app.dependency_overrides[require_auth] = lambda: None
    try:
        response = TestClient(app, raise_server_exceptions=False).post(path, json=_body(path))
    finally:
        app.dependency_overrides.pop(require_auth, None)
    assert response.status_code not in (401, 403, 422), response.text
