
import os
import tempfile

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_gsi_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_gsi_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
import pytest

from src.api import catalog_email_signin_routes as email_routes
from tests.helpers.hosted_routes_app import hosted_proxy_app, route_responder


@pytest.fixture(autouse=True)
def _install_id_without_a_database(monkeypatch):
    monkeypatch.setattr(email_routes, "_install_id", lambda request: "install-0001")


STARTED = {
    "device_code": "GOOGLE-DEVICE-CODE-SECRET", "user_code": "ABC-DEF-GHI",
    "verification_uri": "https://www.google.com/device", "interval": 5, "expires_in": 1800,
}
POW = {"challenge": "v1.email_start.9999999999.1.salt.mac", "bits": 1, "expires_in": 120}
AUTHORIZED = {
    "access_token": "ACCESS-SECRET", "expires_in": 28800, "refresh_token": "REFRESH-SECRET",
    "refresh_expires_in": 2592000, "login": "ada@example.test", "provider": "google",
}
NOT_CONFIGURED = (503, {"code": "auth_not_configured", "detail": "google sign in is not configured yet"})


def responder(start=(200, STARTED), poll=(200, AUTHORIZED)):
    return route_responder({"/pow": (200, POW), "/auth/google/start": start, "/auth/google/poll": poll})


def test_start_solves_the_pow_and_keeps_the_device_code_on_the_server(tmp_path):
    with hosted_proxy_app(tmp_path, responder=responder()) as app:
        answer = app.client.post("/catalog/auth/google/start")
    assert answer.status_code == 200 and answer.json()["user_code"] == "ABC-DEF-GHI"
    assert "GOOGLE-DEVICE-CODE-SECRET" not in answer.text and answer.json()["flow_id"]
    assert app.paths() == ["/api/v1/pow", "/api/v1/auth/google/start"]
    assert b'"pow"' in app.sent[1].content


def test_poll_supplies_the_device_code_and_stores_a_session_without_returning_a_token(tmp_path):
    with hosted_proxy_app(tmp_path, responder=responder()) as app:
        flow_id = app.client.post("/catalog/auth/google/start").json()["flow_id"]
        answer = app.client.post("/catalog/auth/google/poll", json={"flow_id": flow_id})
    assert answer.status_code == 200 and answer.json()["login"] == "ada@example.test"
    assert "ACCESS-SECRET" not in answer.text and "REFRESH-SECRET" not in answer.text
    assert b"GOOGLE-DEVICE-CODE-SECRET" in app.sent[2].content
    assert app.paths()[-1] == "/api/v1/auth/google/poll"


def test_pending_and_unconfigured_are_relayed_with_their_codes(tmp_path):
    pending = (428, {"code": "authorization_pending", "detail": "wait", "interval": 5})
    with hosted_proxy_app(tmp_path, responder=responder(poll=pending)) as app:
        flow_id = app.client.post("/catalog/auth/google/start").json()["flow_id"]
        answer = app.client.post("/catalog/auth/google/poll", json={"flow_id": flow_id})
    assert answer.status_code == 428 and answer.json()["detail"]["interval"] == 5
    with hosted_proxy_app(tmp_path, responder=responder(start=NOT_CONFIGURED)) as app:
        answer = app.client.post("/catalog/auth/google/start")
    assert answer.status_code == 503 and answer.json()["detail"]["code"] == "auth_not_configured"


def test_an_unknown_flow_is_refused_before_anything_is_sent_upstream(tmp_path):
    with hosted_proxy_app(tmp_path, responder=responder()) as app:
        answer = app.client.post("/catalog/auth/google/poll", json={"flow_id": "nope"})
    assert answer.status_code == 400 and app.sent == []


def test_a_mailbox_proof_keeps_the_ticket_and_session_on_the_server_and_verifies_at_the_google_route(tmp_path):
    proof = (403, {"code": "mailbox_proof_required", "detail": "x", "ticket": "TICKET-SECRET.sig",
                   "destination": "a***@example.test", "expires_in": 900})
    routes = {"/pow": (200, POW), "/auth/google/start": (200, STARTED), "/auth/google/poll": proof,
              "/auth/google/mailbox/start": (200, {"session": "SESSION-SECRET", "destination": "a***@example.test",
                                                  "expires_in": 900}),
              "/auth/google/mailbox/verify": (200, AUTHORIZED), "/auth/email/verify": (200, AUTHORIZED)}
    with hosted_proxy_app(tmp_path, responder=route_responder(routes)) as app:
        flow_id = app.client.post("/catalog/auth/google/start").json()["flow_id"]
        answer = app.client.post("/catalog/auth/google/poll", json={"flow_id": flow_id})
        assert answer.status_code == 200 and answer.json()["signed_in"] is False
        offered = answer.json()["mailbox_proof"]
        assert offered["destination"] == "a***@example.test"
        assert "TICKET-SECRET" not in answer.text and "SESSION-SECRET" not in answer.text
        wrong_door = app.client.post("/catalog/auth/email/verify", json={"flow_id": offered["flow_id"], "code": "12345678"})
        assert wrong_door.status_code == 400
        done = app.client.post("/catalog/auth/google/mailbox/verify", json={"flow_id": offered["flow_id"], "code": "12345678"})
    assert done.status_code == 200 and done.json()["login"] == "ada@example.test"
    body = app.sent[-1].content
    assert b"TICKET-SECRET" in body and b"SESSION-SECRET" in body and app.paths()[-1] == "/api/v1/auth/google/mailbox/verify"
