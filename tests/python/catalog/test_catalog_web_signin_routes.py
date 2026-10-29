
import json
import os
import tempfile

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_wsi_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_wsi_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
import pytest

from src.api import catalog_email_signin_routes as email_routes
from src.api import catalog_web_signin_routes as routes_module
from src.core.catalog import catalog_auth
from tests.helpers.hosted_routes_app import hosted_proxy_app, route_responder

POW = {"challenge": "v1.email_start.9999999999.1.salt.mac", "bits": 1, "expires_in": 120}
STARTED = {"flow_id": "FLOWID0123456789abcdef", "url": "https://api.test/v1/auth/web/go?f=x", "expires_in": 900, "interval": 3}
AUTHORIZED = {
    "access_token": "ACCESS-SECRET", "expires_in": 28800, "refresh_token": "REFRESH-SECRET",
    "refresh_expires_in": 2592000, "login": "ada@example.test", "provider": "google",
}
PENDING = (428, {"code": "authorization_pending", "detail": "wait", "interval": 3})
START_BODY = {"provider": "google", "src": "share_link",
              "consent": {"terms_version": "t1", "age_16_plus": True, "news": True}}


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    routes_module._flows._flows.clear()
    monkeypatch.setattr(routes_module, "_install_id", lambda request: "install-0001")
    monkeypatch.setattr(email_routes, "_install_id", lambda request: "install-0001")


def responder(poll=(200, AUTHORIZED), start=(200, STARTED), extra=None):
    routes = {"/pow": (200, POW), "/auth/web/start": start, "/auth/web/poll": poll, **(extra or {})}
    return route_responder(routes)


def sent_json(app, suffix):
    return json.loads(next(r for r in app.sent if r.url.path.endswith(suffix)).content)


def test_the_verifier_is_never_in_a_response_and_pending_then_done_stores_the_provider(tmp_path):
    answers = iter([PENDING, (200, AUTHORIZED)])

    def poll_responder(request):
        if request.url.path.endswith("/auth/web/poll"):
            status, body = next(answers)
            import httpx
            return httpx.Response(status, json=body)
        return responder()(request)

    with hosted_proxy_app(tmp_path, responder=poll_responder, include_aggregator=True) as app:
        started = app.client.post("/catalog/auth/web/start", json=START_BODY)
        assert started.status_code == 200 and started.json()["flow_id"] == STARTED["flow_id"]
        hosted_start = sent_json(app, "/auth/web/start")
        verifier = routes_module._flows.get(STARTED["flow_id"]).verifier
        assert verifier not in started.text and verifier not in json.dumps(hosted_start)
        assert hosted_start["challenge"] == routes_module.challenge_of(verifier)
        assert hosted_start["consent"]["news"] is True and "pow" in hosted_start
        pending = app.client.post("/catalog/auth/web/poll", json={"flow_id": STARTED["flow_id"]})
        assert pending.status_code == 200 and pending.json() == {"status": "pending", "interval": 3}
        assert verifier not in pending.text
        done = app.client.post("/catalog/auth/web/poll", json={"flow_id": STARTED["flow_id"]})
    assert done.status_code == 200 and done.json()["login"] == "ada@example.test"
    for secret in (verifier, "ACCESS-SECRET", "REFRESH-SECRET"):
        assert secret not in done.text
    polled = sent_json(app, "/auth/web/poll")
    assert polled["verifier"] == verifier and polled["install_id"] == "install-0001"
    assert catalog_auth.read_session(app.state).provider == "google"
    assert routes_module._flows.get(STARTED["flow_id"]) is None


def test_a_mailbox_proof_answers_the_google_proof_shape_and_keeps_secrets_server_side(tmp_path):
    proof = (403, {"code": "mailbox_proof_required", "detail": "x", "ticket": "TICKET-SECRET.sig",
                   "destination": "a***@example.test", "expires_in": 900})
    extra = {"/auth/google/mailbox/start": (200, {"session": "SESSION-SECRET", "destination": "a***@example.test",
                                                  "expires_in": 900})}
    with hosted_proxy_app(tmp_path, responder=responder(poll=proof, extra=extra), include_aggregator=True) as app:
        app.client.post("/catalog/auth/web/start", json=START_BODY)
        verifier = routes_module._flows.get(STARTED["flow_id"]).verifier
        answer = app.client.post("/catalog/auth/web/poll", json={"flow_id": STARTED["flow_id"]})
    assert answer.status_code == 200 and answer.json()["signed_in"] is False
    assert answer.json()["mailbox_proof"]["destination"] == "a***@example.test"
    for secret in ("TICKET-SECRET", "SESSION-SECRET", verifier):
        assert secret not in answer.text


def test_a_dead_flow_is_a_clear_error_and_an_unknown_one_never_goes_upstream(tmp_path):
    gone = (410, {"code": "flow_expired", "detail": "start again"})
    with hosted_proxy_app(tmp_path, responder=responder(poll=gone), include_aggregator=True) as app:
        app.client.post("/catalog/auth/web/start", json=START_BODY)
        sent = len(app.sent)
        dead = app.client.post("/catalog/auth/web/poll", json={"flow_id": STARTED["flow_id"]})
        again = app.client.post("/catalog/auth/web/poll", json={"flow_id": STARTED["flow_id"]})
    assert dead.status_code == 410 and dead.json()["detail"]["code"] == "flow_expired"
    assert again.status_code == 400 and again.json()["detail"]["code"] == "unknown_flow"
    assert len(app.sent) == sent + 1


@pytest.mark.parametrize("provider", ["google", "github"])
def test_a_mailbox_proof_starts_and_verifies_at_the_flows_own_provider_routes(tmp_path, provider):
    proof = (403, {"code": "mailbox_proof_required", "detail": "x", "ticket": "T.sig"})
    verified = dict(AUTHORIZED, provider=provider)
    extra = {
        f"/auth/{provider}/mailbox/start": (200, {"session": "S", "destination": "a***@example.test", "expires_in": 900}),
        f"/auth/{provider}/mailbox/verify": (200, verified),
    }
    with hosted_proxy_app(tmp_path, responder=responder(poll=proof, extra=extra), include_aggregator=True) as app:
        app.client.post("/catalog/auth/web/start", json=dict(START_BODY, provider=provider))
        shown = app.client.post("/catalog/auth/web/poll", json={"flow_id": STARTED["flow_id"]}).json()
        done = app.client.post("/catalog/auth/google/mailbox/verify",
                               json={"flow_id": shown["mailbox_proof"]["flow_id"], "code": "123456",
                                     "src": "share_link"})
        paths = [r.url.path for r in app.sent]
        assert sent_json(app, f"/auth/{provider}/mailbox/verify")["src"] == "share_link"
    assert done.status_code == 200 and done.json()["provider"] == provider
    assert any(p.endswith(f"/auth/{provider}/mailbox/start") for p in paths)
    assert any(p.endswith(f"/auth/{provider}/mailbox/verify") for p in paths)
