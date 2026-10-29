
import json
import os
import tempfile

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_evi_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_evi_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.api import catalog_email_signin_routes as routes_module
from tests.helpers.hosted_routes_app import hosted_proxy_app, route_responder

POW = {"challenge": "v1.email_start.9999999999.1.salt.mac", "bits": 1, "expires_in": 120}
STARTED = {"session": "SESSION-SECRET", "destination": "a***@example.test", "expires_in": 900}
AUTHORIZED = {
    "access_token": "ACCESS-SECRET", "expires_in": 28800, "refresh_token": "REFRESH-SECRET",
    "refresh_expires_in": 2592000, "login": "ada@example.test", "provider": "email",
}


def test_the_email_verify_forwards_the_install_id(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_module, "_install_id", lambda request: "install-0001")
    responder = route_responder({"/pow": (200, POW), "/auth/email/start": (200, STARTED),
                                 "/auth/email/verify": (200, AUTHORIZED)})
    with hosted_proxy_app(tmp_path, responder=responder) as app:
        flow_id = app.client.post("/catalog/auth/email/start", json={"email": "ada@example.test"}).json()["flow_id"]
        done = app.client.post("/catalog/auth/email/verify", json={"flow_id": flow_id, "code": "12345678"})
    assert done.status_code == 200
    sent = json.loads(next(r for r in app.sent if r.url.path.endswith("/auth/email/verify")).content)
    assert sent["install_id"] == "install-0001"
