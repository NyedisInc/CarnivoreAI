
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import httpx

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_ces_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_ces_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
import json
import time

import pytest

from src.api import catalog_email_signin_routes as email_routes

from src.core.catalog.device_label import device_fields
from src.core.catalog.token_store import CatalogSession, open_token_store
from tests.helpers.hosted_routes_app import hosted_proxy_app, route_responder

START_URL = "/catalog/auth/email/start"
VERIFY_URL = "/catalog/auth/email/verify"
RATING_URL = "/catalog/items/example-owner/sme/rating"

CHALLENGE = {
    "session": "SESSION-SECRET",
    "expires_in": 900,
    "destination": "a***@example.test",
}

VERIFIED = {
    "access_token": "ACCESS-TOKEN-SECRET",
    "token_type": "bearer",
    "expires_in": 28800,
    "refresh_token": "REFRESH-TOKEN-SECRET",
    "refresh_expires_in": 2592000,
    "login": "ada@example.test",
    "provider": "email",
}

EMAIL_NOT_CONFIGURED = (
    503,
    {
        "code": "email_auth_not_configured",
        "detail": "email sign in is not configured yet",
    },
)

GITHUB_NOT_CONFIGURED = (
    503,
    {"code": "auth_not_configured", "detail": "github sign in is not configured yet"},
)

CODE_MISMATCH = (400, {"code": "code_mismatch", "detail": "that code is not right"})

CODE_EXPIRED = (410, {"code": "code_expired", "detail": "that code cannot be used"})

RATE_LIMITED = (429, {"code": "rate_limited", "detail": "too many", "retry_after": 600})


POW = {"challenge": "v1.email_start.9999999999.1.salt.mac", "bits": 1, "expires_in": 120}


@pytest.fixture(autouse=True)
def _install_id_without_a_database(monkeypatch):
    monkeypatch.setattr(email_routes, "_install_id", lambda request: "install-0001")


def email_responder(start=(200, CHALLENGE), verify=(200, VERIFIED)):
    return route_responder(
        {"/pow": (200, POW), "/auth/email/start": start, "/auth/email/verify": verify}
    )


def open_flow(app, email: str = "ada@example.test") -> str:
    return app.client.post(START_URL, json={"email": email}).json()["flow_id"]


def body_of(request: httpx.Request) -> dict:
    return json.loads(request.content.decode("utf-8"))


class TestStartingAFlow:

    def test_the_address_is_relayed_lowercased_and_trimmed(self, tmp_path):
        with hosted_proxy_app(tmp_path, responder=email_responder()) as app:
            app.client.post(START_URL, json={"email": "  Ada@Example.TEST  "})
            sent = body_of(app.sent[1])
        assert set(sent) == {"email", "pow"} and sent["email"] == "ada@example.test"
        assert sent["pow"].startswith(POW["challenge"] + "~")

    def test_it_is_addressed_to_the_hosted_email_start_path(self, tmp_path):
        with hosted_proxy_app(tmp_path, responder=email_responder()) as app:
            app.client.post(START_URL, json={"email": "ada@example.test"})
            assert app.paths() == ["/api/v1/pow", "/api/v1/auth/email/start"]

    def test_no_bearer_is_sent_because_nobody_is_signed_in_yet(self, tmp_path):
        with hosted_proxy_app(tmp_path, responder=email_responder()) as app:
            app.client.post(START_URL, json={"email": "ada@example.test"})
            assert app.sent[0].headers.get("authorization") is None

    def test_the_answer_carries_the_handle_the_mask_and_the_expiry(self, tmp_path):
        with hosted_proxy_app(tmp_path, responder=email_responder()) as app:
            answer = app.client.post(START_URL, json={"email": "ada@example.test"})
        assert answer.status_code == 200
        body = answer.json()
        assert body["destination"] == "a***@example.test"
        assert body["expires_in"] == 900
        assert isinstance(body["flow_id"], str) and body["flow_id"]
        assert set(body) == {"flow_id", "destination", "expires_in"}

    def test_a_challenge_with_no_session_is_a_502_not_a_flow(self, tmp_path):
        responder = email_responder(
            start=(200, {"expires_in": 900, "destination": "a***@example.test"})
        )
        with hosted_proxy_app(tmp_path, responder=responder) as app:
            answer = app.client.post(START_URL, json={"email": "ada@example.test"})
        assert answer.status_code == 502

    def test_a_transport_failure_is_a_502_and_not_a_started_flow(self, tmp_path):

        def refuse(_request):
            raise httpx.ConnectError("no route to host")

        with hosted_proxy_app(tmp_path, responder=refuse) as app:
            answer = app.client.post(START_URL, json={"email": "ada@example.test"})
        assert answer.status_code == 502


class TestTheAddressIsCheckedBeforeAnythingIsSent:

    def test_a_string_with_no_at_sign_is_refused_locally(self, tmp_path):
        with hosted_proxy_app(tmp_path, responder=email_responder()) as app:
            answer = app.client.post(START_URL, json={"email": "not-an-address"})
            assert app.sent == []
        assert answer.status_code == 400
        assert answer.json()["detail"]["code"] == "bad_email"

    def test_an_over_long_address_is_refused_locally(self, tmp_path):
        address = ("a" * 250) + "@b.test"
        with hosted_proxy_app(tmp_path, responder=email_responder()) as app:
            answer = app.client.post(START_URL, json={"email": address})
            assert app.sent == []
        assert answer.status_code == 400
        assert answer.json()["detail"]["code"] == "bad_email"

    def test_two_at_signs_and_inner_whitespace_are_refused_locally(self, tmp_path):
        with hosted_proxy_app(tmp_path, responder=email_responder()) as app:
            for address in ("a@b@c.test", "a b@c.test", "@b.test", "a@"):
                answer = app.client.post(START_URL, json={"email": address})
                assert answer.status_code == 400, address
                assert answer.json()["detail"]["code"] == "bad_email", address
            assert app.sent == []

    def test_PAIRED_POSITIVE_a_real_address_really_is_forwarded(self, tmp_path):
        with hosted_proxy_app(tmp_path, responder=email_responder()) as app:
            answer = app.client.post(START_URL, json={"email": "ada@example.test"})
            assert app.paths() == ["/api/v1/pow", "/api/v1/auth/email/start"]
        assert answer.status_code == 200


class TestVerifying:

    def test_the_browser_body_carries_only_the_handle_and_the_code(self, tmp_path):
        with hosted_proxy_app(tmp_path, responder=email_responder()) as app:
            flow_id = open_flow(app)
            browser_body = {"flow_id": flow_id, "code": "12345678"}
            app.client.post(VERIFY_URL, json=browser_body)
            upstream = body_of(app.sent[2])
        assert set(browser_body) == {"flow_id", "code"}
        assert upstream == {
            "email": "ada@example.test",
            "session": "SESSION-SECRET",
            "code": "12345678",
            "install_id": "install-0001",
            **device_fields(),
        }

    def test_a_successful_verify_names_the_account_and_the_provider(self, tmp_path):
        with hosted_proxy_app(tmp_path, responder=email_responder()) as app:
            flow_id = open_flow(app)
            answer = app.client.post(
                VERIFY_URL, json={"flow_id": flow_id, "code": "12345678"}
            )
        assert answer.status_code == 200
        assert answer.json() == {
            "signed_in": True,
            "login": "ada@example.test",
            "provider": "email",
            "email": "ada@example.test",
        }

    def test_an_unknown_flow_id_is_refused_and_sends_nothing_upstream(self, tmp_path):
        with hosted_proxy_app(tmp_path, responder=email_responder()) as app:
            answer = app.client.post(
                VERIFY_URL, json={"flow_id": "not-a-real-flow", "code": "12345678"}
            )
            assert app.sent == []
        assert answer.status_code == 400
        assert answer.json()["detail"]["code"] == "unknown_flow"

    def test_a_body_that_is_not_a_code_is_refused_before_the_attempt(self, tmp_path):
        with hosted_proxy_app(tmp_path, responder=email_responder()) as app:
            flow_id = open_flow(app)
            before = len(app.sent)
            for code in ("", "12ab5678", "1234567890123456789", "  "):
                answer = app.client.post(
                    VERIFY_URL, json={"flow_id": flow_id, "code": code}
                )
                assert answer.status_code == 400, code
                assert answer.json()["detail"]["code"] == "bad_code", code
            assert len(app.sent) == before

    def test_the_minted_pair_really_IS_stored_on_this_server(self, tmp_path):
        with hosted_proxy_app(tmp_path, responder=email_responder()) as app:
            flow_id = open_flow(app)
            app.client.post(VERIFY_URL, json={"flow_id": flow_id, "code": "12345678"})
            state = app.state
        with open_token_store(state) as store:
            held = store.read()
        assert held is not None
        assert held.access_token == "ACCESS-TOKEN-SECRET"
        assert held.refresh_token == "REFRESH-TOKEN-SECRET"
        assert held.login == "ada@example.test"


class TestATypoDoesNotCostAPersonTheirEmail:

    def test_a_wrong_code_keeps_the_flow_and_the_next_attempt_lands(self, tmp_path):
        answers = [CODE_MISMATCH, (200, VERIFIED)]

        def verify(_request):
            return answers.pop(0)

        with hosted_proxy_app(
            tmp_path, responder=email_responder(verify=verify)
        ) as app:
            flow_id = open_flow(app)
            first = app.client.post(
                VERIFY_URL, json={"flow_id": flow_id, "code": "11111111"}
            )
            second = app.client.post(
                VERIFY_URL, json={"flow_id": flow_id, "code": "12345678"}
            )
        assert first.status_code == 400
        assert first.json()["detail"]["code"] == "code_mismatch"
        assert second.status_code == 200
        assert second.json()["login"] == "ada@example.test"

    def test_an_expired_code_ENDS_the_flow_and_a_retry_sends_nothing(self, tmp_path):
        with hosted_proxy_app(
            tmp_path, responder=email_responder(verify=CODE_EXPIRED)
        ) as app:
            flow_id = open_flow(app)
            first = app.client.post(
                VERIFY_URL, json={"flow_id": flow_id, "code": "12345678"}
            )
            upstream_after_first = len(app.sent)
            second = app.client.post(
                VERIFY_URL, json={"flow_id": flow_id, "code": "12345678"}
            )
            upstream_after_second = len(app.sent)
        assert first.status_code == 410
        assert first.json()["detail"]["code"] == "code_expired"
        assert second.status_code == 400
        assert second.json()["detail"]["code"] == "unknown_flow"
        assert upstream_after_second == upstream_after_first


class TestRefusalsAreRelayedWholeAndToldApart:

    def test_the_email_503_is_its_own_code_not_the_github_one(self, tmp_path):
        with hosted_proxy_app(
            tmp_path, responder=email_responder(start=EMAIL_NOT_CONFIGURED)
        ) as app:
            answer = app.client.post(START_URL, json={"email": "ada@example.test"})
        assert answer.status_code == 503
        assert answer.json()["detail"]["code"] == "email_auth_not_configured"
        assert answer.json()["detail"]["code"] != GITHUB_NOT_CONFIGURED[1]["code"]

    def test_rate_limited_relays_whole_with_the_wait_it_carried(self, tmp_path):
        with hosted_proxy_app(
            tmp_path, responder=email_responder(start=RATE_LIMITED)
        ) as app:
            answer = app.client.post(START_URL, json={"email": "ada@example.test"})
        assert answer.status_code == 429
        assert answer.json()["detail"]["code"] == "rate_limited"
        assert answer.json()["detail"]["retry_after"] == 600

    def test_a_disabled_account_relays_its_own_403(self, tmp_path):
        disabled = (403, {"code": "account_disabled", "detail": "this account is off"})
        with hosted_proxy_app(
            tmp_path, responder=email_responder(verify=disabled)
        ) as app:
            flow_id = open_flow(app)
            answer = app.client.post(
                VERIFY_URL, json={"flow_id": flow_id, "code": "12345678"}
            )
        assert answer.status_code == 403
        assert answer.json()["detail"]["code"] == "account_disabled"

    def test_a_verified_answer_with_no_refresh_token_stores_NOTHING(self, tmp_path):
        partial = dict(VERIFIED)
        del partial["refresh_token"]
        with hosted_proxy_app(
            tmp_path, responder=email_responder(verify=(200, partial))
        ) as app:
            flow_id = open_flow(app)
            answer = app.client.post(
                VERIFY_URL, json={"flow_id": flow_id, "code": "12345678"}
            )
            state = app.state
        assert answer.status_code == 502
        with open_token_store(state) as store:
            assert store.read() is None


class TestTheSessionNeverReachesTheBrowser:

    def test_no_route_ever_prints_the_cognito_session_or_either_token(
        self, tmp_path
    ):
        with hosted_proxy_app(tmp_path, responder=email_responder()) as app:
            bodies = []
            started = app.client.post(START_URL, json={"email": "ada@example.test"})
            bodies.append(started.text)
            flow_id = started.json()["flow_id"]
            bodies.append(
                app.client.post(
                    VERIFY_URL, json={"flow_id": flow_id, "code": "12345678"}
                ).text
            )
            bodies.append(app.client.get("/catalog/auth/session").text)
            bodies.append(app.client.post("/catalog/auth/signout").text)
        for body in bodies:
            assert "SESSION-SECRET" not in body
            assert "ACCESS-TOKEN-SECRET" not in body
            assert "REFRESH-TOKEN-SECRET" not in body

    def test_and_the_session_really_WAS_held_here_and_used(self, tmp_path):
        with hosted_proxy_app(tmp_path, responder=email_responder()) as app:
            flow_id = open_flow(app)
            app.client.post(VERIFY_URL, json={"flow_id": flow_id, "code": "12345678"})
            upstream = body_of(app.sent[2])
        assert upstream["session"] == "SESSION-SECRET"

    def test_the_start_response_model_has_no_session_field_at_all(self, tmp_path):
        from src.models.catalog_signin import EmailStartResponse

        assert "session" not in EmailStartResponse.model_fields
        assert set(EmailStartResponse.model_fields) == {
            "flow_id",
            "destination",
            "expires_in",
        }


class TestWhatTheSignedInSessionReports:

    def test_an_email_login_reads_as_the_email_provider(self, tmp_path):
        with hosted_proxy_app(tmp_path, responder=email_responder()) as app:
            flow_id = open_flow(app)
            app.client.post(VERIFY_URL, json={"flow_id": flow_id, "code": "12345678"})
            answer = app.client.get("/catalog/auth/session")
        assert answer.json() == {
            "signed_in": True,
            "login": "ada@example.test",
            "provider": "email",
            "email": "ada@example.test",
        }

    def test_a_github_login_reads_as_the_github_provider(self, tmp_path):
        now = int(time.time())
        with hosted_proxy_app(tmp_path, responder=email_responder()) as app:
            with open_token_store(app.state) as store:
                store.save(
                    CatalogSession(
                        login="example-owner",
                        access_token="ACCESS-TOKEN-SECRET",
                        access_expires_at=now + 3600,
                        refresh_token="REFRESH-TOKEN-SECRET",
                        refresh_expires_at=now + 2592000,
                    )
                )
            answer = app.client.get("/catalog/auth/session")
        assert answer.json() == {
            "signed_in": True,
            "login": "example-owner",
            "provider": "github",
            "email": None,
        }

    def test_signed_out_names_no_provider_either(self, tmp_path):
        with hosted_proxy_app(tmp_path, responder=email_responder()) as app:
            answer = app.client.get("/catalog/auth/session")
        assert answer.json() == {"signed_in": False, "login": None, "provider": None, "email": None}


class TestNothingDownstreamHadToChange:

    def test_after_an_email_sign_in_the_rating_write_sends_the_held_bearer(
        self, tmp_path
    ):
        put_ok = {
            "count": 1,
            "average": 5.0,
            "histogram": {"1": 0, "2": 0, "3": 0, "4": 0, "5": 1},
            "item_id": "example-owner/sme",
            "your_stars": 5,
        }
        responder = route_responder(
            {
                "/pow": (200, POW),
                "/auth/email/start": (200, CHALLENGE),
                "/auth/email/verify": (200, VERIFIED),
                "/rating": (200, put_ok),
            }
        )
        with hosted_proxy_app(tmp_path, responder=responder) as app:
            flow_id = open_flow(app)
            app.client.post(VERIFY_URL, json={"flow_id": flow_id, "code": "12345678"})
            answer = app.client.put(RATING_URL, json={"stars": 5})
            bearer = app.sent[-1].headers.get("authorization")
        assert answer.status_code == 200
        assert bearer == "Bearer ACCESS-TOKEN-SECRET"


class TestTheRouterIsReallyRegistered:

    def test_both_email_routes_are_reachable_through_the_whole_app(self, tmp_path):
        with hosted_proxy_app(
            tmp_path, responder=email_responder(), include_aggregator=True
        ) as app:
            started = app.client.post(START_URL, json={"email": "ada@example.test"})
            verified = app.client.post(
                VERIFY_URL,
                json={"flow_id": started.json()["flow_id"], "code": "12345678"},
            )
        assert started.status_code == 200
        assert verified.status_code == 200
