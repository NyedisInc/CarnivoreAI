
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_cnr_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_cnr_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
import httpx

from src.core.catalog.token_store import CatalogSession, open_token_store
from tests.helpers.hosted_routes_app import hosted_proxy_app, route_responder

NOTE_URL = "/catalog/items/bundled/matrix/note"

POST_OK = {"item_id": "bundled/matrix", "created_at": "2026-09-22T00:00:00Z"}

REFRESHED = {
    "access_token": "SECOND-ACCESS-SECRET",
    "token_type": "bearer",
    "expires_in": 28800,
    "refresh_token": "SECOND-REFRESH-SECRET",
    "refresh_expires_in": 2592000,
    "login": "example-owner",
}


def sign_in(state: Path, *, access_in: int = 3600) -> None:
    now = int(time.time())
    with open_token_store(state) as store:
        store.save(CatalogSession(
            login="example-owner",
            access_token="FIRST-ACCESS-SECRET",
            access_expires_at=now + access_in,
            refresh_token="FIRST-REFRESH-SECRET",
            refresh_expires_at=now + 2592000,
        ))


def note_responder(post=(201, POST_OK)):
    return route_responder({"/note": post})


class TestTheNoteIsForwardedWithTheHeldToken:

    def test_the_note_goes_upstream_and_the_answer_comes_back(self, tmp_path):
        with hosted_proxy_app(
            tmp_path, responder=note_responder(), include_aggregator=True
        ) as app:
            sign_in(app.state)
            answer = app.client.post(NOTE_URL, json={"text": "the reds clash on ansi 3"})
        assert answer.status_code == 201
        assert answer.json()["item_id"] == "bundled/matrix"
        assert answer.json()["created_at"] == "2026-09-22T00:00:00Z"

    def test_it_is_addressed_to_the_hosted_NOTE_path(self, tmp_path):
        with hosted_proxy_app(
            tmp_path, responder=note_responder(), include_aggregator=True
        ) as app:
            sign_in(app.state)
            app.client.post(NOTE_URL, json={"text": "hello"})
        assert app.paths() == ["/api/v1/items/bundled/matrix/note"]

    def test_the_bearer_really_is_the_token_this_machine_HOLDS(self, tmp_path):
        with hosted_proxy_app(
            tmp_path, responder=note_responder(), include_aggregator=True
        ) as app:
            sign_in(app.state)
            app.client.post(NOTE_URL, json={"text": "hello"})
            sent = app.sent[0].headers.get("authorization")
        assert sent == "Bearer FIRST-ACCESS-SECRET"

    def test_the_text_is_what_is_sent_and_nothing_else(self, tmp_path):
        with hosted_proxy_app(
            tmp_path, responder=note_responder(), include_aggregator=True
        ) as app:
            sign_in(app.state)
            app.client.post(NOTE_URL, json={"text": "please add a lighter accent"})
            sent = json.loads(app.sent[0].content)
        assert sent == {"text": "please add a lighter accent"}

    def test_a_catalog_item_id_with_a_publisher_handle_works_too(self, tmp_path):
        with hosted_proxy_app(
            tmp_path, responder=note_responder(), include_aggregator=True
        ) as app:
            sign_in(app.state)
            answer = app.client.post(
                "/catalog/items/example-owner/sme/note", json={"text": "hello"}
            )
            assert app.paths() == ["/api/v1/items/example-owner/sme/note"]
        assert answer.status_code == 201


class TestSignedOutNothingIsSent:

    def test_a_signed_out_POST_is_403_and_reaches_the_host_NEVER(self, tmp_path):
        with hosted_proxy_app(
            tmp_path, responder=note_responder(), include_aggregator=True
        ) as app:
            answer = app.client.post(NOTE_URL, json={"text": "hello"})
            assert app.sent == []
        assert answer.status_code == 403
        assert answer.json()["detail"]["code"] == "unauthorized"

    def test_PAIRED_POSITIVE_signed_in_the_same_call_IS_forwarded(self, tmp_path):
        with hosted_proxy_app(
            tmp_path, responder=note_responder(), include_aggregator=True
        ) as app:
            sign_in(app.state)
            answer = app.client.post(NOTE_URL, json={"text": "hello"})
            assert len(app.sent) == 1
        assert answer.status_code == 201


class TestTheTokenRotatesWhenItHasExpired:

    def test_an_expired_access_token_is_ROTATED_and_the_note_still_lands(self, tmp_path):
        responder = route_responder({"/auth/refresh": (200, REFRESHED), "/note": (201, POST_OK)})
        with hosted_proxy_app(
            tmp_path, responder=responder, include_aggregator=True
        ) as app:
            sign_in(app.state, access_in=-10)
            answer = app.client.post(NOTE_URL, json={"text": "hello"})
            paths = app.paths()
        assert answer.status_code == 201
        assert paths == ["/api/v1/auth/refresh", "/api/v1/items/bundled/matrix/note"]
        assert app.sent[1].headers.get("authorization") == "Bearer SECOND-ACCESS-SECRET"  # secret-scan: allow synthetic fixture


class TestWhatTheHostRefuses:

    def test_an_empty_note_is_relayed_as_400_empty_note(self, tmp_path):
        refused = (400, {"code": "empty_note", "detail": "a note needs words"})
        with hosted_proxy_app(
            tmp_path, responder=note_responder(post=refused), include_aggregator=True
        ) as app:
            sign_in(app.state)
            answer = app.client.post(NOTE_URL, json={"text": ""})
        assert answer.status_code == 400
        assert answer.json()["detail"]["code"] == "empty_note"

    def test_an_over_length_note_is_relayed_as_400_note_too_long(self, tmp_path):
        refused = (400, {"code": "note_too_long", "detail": "1000 characters, no more"})
        with hosted_proxy_app(
            tmp_path, responder=note_responder(post=refused), include_aggregator=True
        ) as app:
            sign_in(app.state)
            answer = app.client.post(NOTE_URL, json={"text": "x" * 5000})
        assert answer.status_code == 400
        assert answer.json()["detail"]["code"] == "note_too_long"

    def test_the_hosts_own_401_is_a_403_so_the_APP_is_not_signed_out(self, tmp_path):
        refused = (401, {"code": "unauthorized", "detail": "the token is not valid"})
        with hosted_proxy_app(
            tmp_path, responder=note_responder(post=refused), include_aggregator=True
        ) as app:
            sign_in(app.state)
            answer = app.client.post(NOTE_URL, json={"text": "hello"})
        assert answer.status_code == 403
        assert answer.json()["detail"]["code"] == "unauthorized"

    def test_an_unknown_item_is_relayed_as_404(self, tmp_path):
        unknown = (404, {"code": "unknown_item", "detail": "the catalog has no such item"})
        with hosted_proxy_app(
            tmp_path, responder=note_responder(post=unknown), include_aggregator=True
        ) as app:
            sign_in(app.state)
            answer = app.client.post(NOTE_URL, json={"text": "hello"})
        assert answer.status_code == 404
        assert answer.json()["detail"]["code"] == "unknown_item"

    def test_the_daily_limit_is_relayed_as_429_rate_limited(self, tmp_path):
        limited = (429, {"code": "rate_limited", "detail": "today's ten notes are gone"})
        with hosted_proxy_app(
            tmp_path, responder=note_responder(post=limited), include_aggregator=True
        ) as app:
            sign_in(app.state)
            answer = app.client.post(NOTE_URL, json={"text": "hello"})
        assert answer.status_code == 429
        assert answer.json()["detail"]["code"] == "rate_limited"

    def test_an_unreachable_host_is_a_502_and_never_a_fake_success(self, tmp_path):
        def explode(_request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("no route to host")

        with hosted_proxy_app(
            tmp_path, responder=explode, include_aggregator=True
        ) as app:
            sign_in(app.state)
            answer = app.client.post(NOTE_URL, json={"text": "hello"})
        assert answer.status_code == 502
        assert answer.json()["detail"]["code"] == "unavailable"
        assert "item_id" not in answer.text


class TestAnItemIdIsStillNotAFreePathSegment:

    def test_an_encoded_traversal_is_refused_and_sends_nothing(self, tmp_path):
        with hosted_proxy_app(
            tmp_path, responder=note_responder(), include_aggregator=True
        ) as app:
            sign_in(app.state)
            answer = app.client.post(
                "/catalog/items/a/%2e%2e/%2e%2e/auth/refresh/note",
                json={"text": "hello"},
            )
            assert app.sent == []
        assert answer.status_code == 400
        assert answer.json()["detail"]["code"] == "bad_item_id"


class TestTheTokenNeverReachesTheBrowser:

    def test_no_note_response_prints_the_access_or_refresh_token(self, tmp_path):
        responder = route_responder({
            "/auth/refresh": (200, REFRESHED),
            "/note": (201, POST_OK),
        })
        with hosted_proxy_app(
            tmp_path, responder=responder, include_aggregator=True
        ) as app:
            sign_in(app.state, access_in=-10)
            body = app.client.post(NOTE_URL, json={"text": "hello"}).text
        for secret in (
            "FIRST-ACCESS-SECRET", "FIRST-REFRESH-SECRET",
            "SECOND-ACCESS-SECRET", "SECOND-REFRESH-SECRET",
        ):
            assert secret not in body


class TestNoLengthCheckHappensHere:

    def test_a_very_long_body_is_still_forwarded_not_refused_locally(self, tmp_path):
        with hosted_proxy_app(
            tmp_path, responder=note_responder(), include_aggregator=True
        ) as app:
            sign_in(app.state)
            answer = app.client.post(NOTE_URL, json={"text": "x" * 5000})
        assert answer.status_code == 201
