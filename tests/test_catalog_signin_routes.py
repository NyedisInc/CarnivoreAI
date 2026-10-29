
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import httpx

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_csi_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_csi_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.core.catalog.token_store import CatalogSession, open_token_store
from tests.helpers.hosted_routes_app import (
    hosted_proxy_app,
    json_responder,
    route_responder,
)

STARTED = {
    "device_code": "DEVICE-CODE-SECRET",
    "user_code": "WDJB-MJHT",
    "verification_uri": "https://github.com/login/device",
    "interval": 5,
    "expires_in": 900,
}

AUTHORIZED = {
    "access_token": "ACCESS-TOKEN-SECRET",
    "token_type": "bearer",
    "expires_in": 28800,
    "refresh_token": "REFRESH-TOKEN-SECRET",
    "refresh_expires_in": 2592000,
    "login": "example-owner",
}

PENDING = (
    428,
    {
        "code": "authorization_pending",
        "detail": "the user has not finished authorizing yet",
        "interval": 5,
    },
)

NOT_CONFIGURED = (
    503,
    {"code": "auth_not_configured", "detail": "github sign in is not configured yet"},
)


def sign_in_for_guard(state, *, access_in: int = 3600) -> None:
    import time

    now = int(time.time())
    with open_token_store(state) as store:
        store.save(CatalogSession(
            login="example-owner",
            access_token="ACCESS-TOKEN-SECRET",
            access_expires_at=now + access_in,
            refresh_token="REFRESH-TOKEN-SECRET",
            refresh_expires_at=now + 2592000,
        ))


def flow_responder(poll=(200, AUTHORIZED)):
    return route_responder(
        {"/auth/device/start": (200, STARTED), "/auth/device/poll": poll}
    )


class TestOpeningAFlow:

    def test_the_user_code_and_the_url_come_back(self, tmp_path):
        with hosted_proxy_app(tmp_path, responder=flow_responder()) as app:
            answer = app.client.post("/catalog/auth/device/start")
        assert answer.status_code == 200
        body = answer.json()
        assert body["user_code"] == "WDJB-MJHT"
        assert body["verification_uri"] == "https://github.com/login/device"
        assert body["interval"] == 5

    def test_the_DEVICE_CODE_NEVER_reaches_the_browser(self, tmp_path):
        with hosted_proxy_app(tmp_path, responder=flow_responder()) as app:
            answer = app.client.post("/catalog/auth/device/start")
        assert "DEVICE-CODE-SECRET" not in answer.text
        assert "device_code" not in answer.json()

    def test_a_flow_id_comes_back_instead(self, tmp_path):
        with hosted_proxy_app(tmp_path, responder=flow_responder()) as app:
            body = app.client.post("/catalog/auth/device/start").json()
        assert isinstance(body["flow_id"], str)
        assert body["flow_id"]
        assert body["flow_id"] != "DEVICE-CODE-SECRET"

    def test_no_github_app_is_relayed_with_its_own_code(self, tmp_path):
        responder = route_responder({"/auth/device/start": NOT_CONFIGURED})
        with hosted_proxy_app(tmp_path, responder=responder) as app:
            answer = app.client.post("/catalog/auth/device/start")
        assert answer.status_code == 503
        assert answer.json()["detail"]["code"] == "auth_not_configured"


class TestPolling:

    def test_the_poll_supplies_the_device_code_the_browser_never_had(self, tmp_path):
        with hosted_proxy_app(tmp_path, responder=flow_responder()) as app:
            flow_id = app.client.post("/catalog/auth/device/start").json()["flow_id"]
            app.client.post("/catalog/auth/device/poll", json={"flow_id": flow_id})
        assert b"DEVICE-CODE-SECRET" in app.sent[1].content

    def test_a_pending_poll_is_relayed_with_its_interval(self, tmp_path):
        with hosted_proxy_app(tmp_path, responder=flow_responder(poll=PENDING)) as app:
            flow_id = app.client.post("/catalog/auth/device/start").json()["flow_id"]
            answer = app.client.post(
                "/catalog/auth/device/poll", json={"flow_id": flow_id}
            )
        assert answer.status_code == 428
        assert answer.json()["detail"]["code"] == "authorization_pending"
        assert answer.json()["detail"]["interval"] == 5

    def test_an_authorized_poll_answers_the_login_and_nothing_secret(self, tmp_path):
        with hosted_proxy_app(tmp_path, responder=flow_responder()) as app:
            flow_id = app.client.post("/catalog/auth/device/start").json()["flow_id"]
            answer = app.client.post(
                "/catalog/auth/device/poll", json={"flow_id": flow_id}
            )
        assert answer.status_code == 200
        assert answer.json()["login"] == "example-owner"
        assert answer.json()["signed_in"] is True

    def test_an_unknown_flow_id_is_refused_and_sends_nothing_upstream(self, tmp_path):
        with hosted_proxy_app(tmp_path, responder=flow_responder()) as app:
            answer = app.client.post(
                "/catalog/auth/device/poll", json={"flow_id": "not-a-real-flow"}
            )
            assert app.sent == []
        assert answer.status_code == 400
        assert answer.json()["detail"]["code"] == "unknown_flow"


class TestTheTokenNeverReachesTheBrowser:

    def test_no_route_ever_prints_the_access_or_refresh_token(self, tmp_path):
        with hosted_proxy_app(tmp_path, responder=flow_responder()) as app:
            bodies = []
            flow_id = app.client.post("/catalog/auth/device/start").json()["flow_id"]
            bodies.append(app.client.post("/catalog/auth/device/start").text)
            bodies.append(
                app.client.post(
                    "/catalog/auth/device/poll", json={"flow_id": flow_id}
                ).text
            )
            bodies.append(app.client.get("/catalog/auth/session").text)
        for body in bodies:
            assert "ACCESS-TOKEN-SECRET" not in body
            assert "REFRESH-TOKEN-SECRET" not in body

    def test_and_the_token_really_WAS_stored_on_this_server(self, tmp_path):
        with hosted_proxy_app(tmp_path, responder=flow_responder()) as app:
            flow_id = app.client.post("/catalog/auth/device/start").json()["flow_id"]
            app.client.post("/catalog/auth/device/poll", json={"flow_id": flow_id})
            state = app.state
        with open_token_store(state) as store:
            held = store.read()
        assert held is not None
        assert held.access_token == "ACCESS-TOKEN-SECRET"
        assert held.refresh_token == "REFRESH-TOKEN-SECRET"
        assert held.login == "example-owner"


class TestTheSessionRoute:

    def test_signed_out_says_so_and_names_nobody(self, tmp_path):
        with hosted_proxy_app(tmp_path, responder=flow_responder()) as app:
            answer = app.client.get("/catalog/auth/session")
        assert answer.status_code == 200
        assert answer.json() == {"signed_in": False, "login": None, "provider": None, "email": None}

    def test_after_a_flow_it_names_the_account(self, tmp_path):
        with hosted_proxy_app(tmp_path, responder=flow_responder()) as app:
            flow_id = app.client.post("/catalog/auth/device/start").json()["flow_id"]
            app.client.post("/catalog/auth/device/poll", json={"flow_id": flow_id})
            answer = app.client.get("/catalog/auth/session")
        assert answer.json() == {
            "signed_in": True,
            "login": "example-owner",
            "provider": "github",
            "email": None,
        }

    def test_reading_the_session_talks_to_nobody(self, tmp_path):
        with hosted_proxy_app(tmp_path, responder=flow_responder()) as app:
            app.client.get("/catalog/auth/session")
            assert app.sent == []

    def test_signing_out_ends_it(self, tmp_path):
        with hosted_proxy_app(tmp_path, responder=flow_responder()) as app:
            flow_id = app.client.post("/catalog/auth/device/start").json()["flow_id"]
            app.client.post("/catalog/auth/device/poll", json={"flow_id": flow_id})
            answer = app.client.post("/catalog/auth/signout")
            state = app.state
        assert answer.json() == {"signed_in": False, "login": None, "provider": None, "email": None}
        with open_token_store(state) as store:
            assert store.read() is None


class TestNoWriteRouteIsStubbed:

    def test_the_REMAINING_hosted_write_is_absent_rather_than_faked(
        self, tmp_path
    ):
        with hosted_proxy_app(tmp_path, responder=flow_responder()) as app:
            for method, path in (
                ("post", "/catalog/items/example-owner/sme/installed"),
            ):
                answer = getattr(app.client, method)(path, json={})
                assert answer.status_code in (404, 405), f"{method} {path}"
            assert app.sent == []

    def test_the_write_that_DID_ship_is_present_and_really_sends(self, tmp_path):
        responder = route_responder({
            "/rating": (200, {"count": 1, "item_id": "example-owner/sme", "your_stars": 5}),
        })
        with hosted_proxy_app(tmp_path, responder=responder) as app:
            sign_in_for_guard(app.state)
            answer = app.client.put(
                "/catalog/items/example-owner/sme/rating", json={"stars": 5}
            )
            sent = app.paths()
        assert answer.status_code == 200
        assert sent == ["/api/v1/items/example-owner/sme/rating"]

    def test_the_read_that_DOES_exist_still_answers(self, tmp_path):
        with hosted_proxy_app(
            tmp_path, responder=json_responder({"count": 0, "item_id": "a/b"})
        ) as app:
            answer = app.client.get("/catalog/items/a/b/ratings")
        assert answer.status_code == 200
