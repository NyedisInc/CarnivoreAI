
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

import httpx

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_crw_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_crw_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.core.catalog.token_store import CatalogSession, open_token_store
from tests.helpers.hosted_routes_app import hosted_proxy_app, route_responder

RATING_URL = "/catalog/items/example-owner/sme/rating"

PUT_OK = {
    "count": 3,
    "average": 4.67,
    "histogram": {"1": 0, "2": 0, "3": 0, "4": 1, "5": 2},
    "item_id": "example-owner/sme",
    "your_stars": 5,
}

DELETE_OK = {
    "count": 2,
    "average": 4.5,
    "histogram": {"1": 0, "2": 0, "3": 0, "4": 1, "5": 1},
    "item_id": "example-owner/sme",
    "removed": True,
}

REFRESHED = {
    "access_token": "SECOND-ACCESS-SECRET",
    "token_type": "bearer",
    "expires_in": 28800,
    "refresh_token": "SECOND-REFRESH-SECRET",
    "refresh_expires_in": 2592000,
    "login": "example-owner",
}


def sign_in(state: Path, *, access_in: int = 3600, refresh_in: int = 2592000) -> None:
    now = int(time.time())
    with open_token_store(state) as store:
        store.save(CatalogSession(
            login="example-owner",
            access_token="FIRST-ACCESS-SECRET",
            access_expires_at=now + access_in,
            refresh_token="FIRST-REFRESH-SECRET",
            refresh_expires_at=now + refresh_in,
        ))


def held(state: Path):
    with open_token_store(state) as store:
        return store.read()


def rating_responder(put=(200, PUT_OK), refresh=(200, REFRESHED)):
    return route_responder({
        "/auth/refresh": refresh,
        "/rating": put,
    })


class TestTheWriteIsForwardedWithTheHeldToken:

    def test_the_rating_goes_upstream_and_the_summary_comes_back(self, tmp_path):
        with hosted_proxy_app(tmp_path, responder=rating_responder()) as app:
            sign_in(app.state)
            answer = app.client.put(RATING_URL, json={"stars": 5, "text": "it reads well"})
        assert answer.status_code == 200
        assert answer.json()["your_stars"] == 5
        assert answer.json()["count"] == 3

    def test_it_is_addressed_to_the_hosted_RATING_path(self, tmp_path):
        with hosted_proxy_app(tmp_path, responder=rating_responder()) as app:
            sign_in(app.state)
            app.client.put(RATING_URL, json={"stars": 5})
            assert app.paths() == ["/api/v1/items/example-owner/sme/rating"]

    def test_the_bearer_really_is_the_token_this_machine_HOLDS(self, tmp_path):
        with hosted_proxy_app(tmp_path, responder=rating_responder()) as app:
            sign_in(app.state)
            app.client.put(RATING_URL, json={"stars": 5})
            sent = app.sent[0].headers.get("authorization")
        assert sent == "Bearer FIRST-ACCESS-SECRET"

    def test_the_stars_and_the_words_are_what_is_sent(self, tmp_path):
        with hosted_proxy_app(tmp_path, responder=rating_responder()) as app:
            sign_in(app.state)
            app.client.put(RATING_URL, json={"stars": 4, "text": "solid"})
            body = app.sent[0].content
        assert b'"stars":4' in body.replace(b" ", b"")
        assert b"solid" in body

    def test_withdrawing_a_rating_relays_the_removal(self, tmp_path):
        responder = route_responder({"/rating": (200, DELETE_OK)})
        with hosted_proxy_app(tmp_path, responder=responder) as app:
            sign_in(app.state)
            answer = app.client.delete(RATING_URL)
        assert answer.status_code == 200
        assert answer.json()["removed"] is True
        assert answer.json()["count"] == 2


class TestSignedOutNothingIsSent:

    def test_a_signed_out_PUT_is_403_and_reaches_the_host_NEVER(self, tmp_path):
        with hosted_proxy_app(tmp_path, responder=rating_responder()) as app:
            answer = app.client.put(RATING_URL, json={"stars": 5})
            assert app.sent == []
        assert answer.status_code == 403
        assert answer.json()["detail"]["code"] == "unauthorized"

    def test_a_signed_out_DELETE_is_refused_the_same_way(self, tmp_path):
        with hosted_proxy_app(tmp_path, responder=rating_responder()) as app:
            answer = app.client.delete(RATING_URL)
            assert app.sent == []
        assert answer.status_code == 403

    def test_PAIRED_POSITIVE_signed_in_the_same_call_IS_forwarded(self, tmp_path):
        with hosted_proxy_app(tmp_path, responder=rating_responder()) as app:
            sign_in(app.state)
            answer = app.client.put(RATING_URL, json={"stars": 5})
            assert len(app.sent) == 1
        assert answer.status_code == 200


class TestTheTokenRotatesWhenItHasExpired:

    def test_an_expired_access_token_is_ROTATED_and_the_write_still_lands(self, tmp_path):
        with hosted_proxy_app(tmp_path, responder=rating_responder()) as app:
            sign_in(app.state, access_in=-10)
            answer = app.client.put(RATING_URL, json={"stars": 5})
            paths = app.paths()
        assert answer.status_code == 200
        assert paths == ["/api/v1/auth/refresh", "/api/v1/items/example-owner/sme/rating"]

    def test_the_write_carries_the_NEW_token_not_the_dead_one(self, tmp_path):
        with hosted_proxy_app(tmp_path, responder=rating_responder()) as app:
            sign_in(app.state, access_in=-10)
            app.client.put(RATING_URL, json={"stars": 5})
            rating_call = app.sent[1]
        assert rating_call.headers.get("authorization") == "Bearer SECOND-ACCESS-SECRET"  # secret-scan: allow synthetic fixture

    def test_the_rotated_pair_is_STORED_so_the_next_call_is_cheap(self, tmp_path):
        with hosted_proxy_app(tmp_path, responder=rating_responder()) as app:
            sign_in(app.state, access_in=-10)
            app.client.put(RATING_URL, json={"stars": 5})
            stored = held(app.state)
        assert stored is not None
        assert stored.access_token == "SECOND-ACCESS-SECRET"
        assert stored.refresh_token == "SECOND-REFRESH-SECRET"
        assert stored.access_expires_at > int(time.time())

    def test_a_LIVE_token_is_used_as_is_and_rotates_nothing(self, tmp_path):
        with hosted_proxy_app(tmp_path, responder=rating_responder()) as app:
            sign_in(app.state)
            app.client.put(RATING_URL, json={"stars": 5})
            paths = app.paths()
            stored = held(app.state)
        assert paths == ["/api/v1/items/example-owner/sme/rating"]
        assert stored is not None
        assert stored.access_token == "FIRST-ACCESS-SECRET"

    def test_a_refused_rotation_is_a_403_and_the_rating_is_NOT_attempted(self, tmp_path):
        refused = (401, {"code": "unauthorized", "detail": "the refresh token is not valid"})
        with hosted_proxy_app(
            tmp_path, responder=rating_responder(refresh=refused)
        ) as app:
            sign_in(app.state, access_in=-10)
            answer = app.client.put(RATING_URL, json={"stars": 5})
            paths = app.paths()
        assert answer.status_code == 403
        assert answer.json()["detail"]["code"] == "unauthorized"
        assert paths == ["/api/v1/auth/refresh"]

    def test_an_expired_REFRESH_token_sends_nothing_at_all(self, tmp_path):
        with hosted_proxy_app(tmp_path, responder=rating_responder()) as app:
            sign_in(app.state, access_in=-10, refresh_in=-10)
            answer = app.client.put(RATING_URL, json={"stars": 5})
            assert app.sent == []
        assert answer.status_code == 403


class TestWhatTheHostRefuses:

    def test_the_daily_limit_is_relayed_as_429_rate_limited(self, tmp_path):
        limited = (429, {"code": "rate_limited", "detail": "the daily rating limit is reached"})
        with hosted_proxy_app(tmp_path, responder=rating_responder(put=limited)) as app:
            sign_in(app.state)
            answer = app.client.put(RATING_URL, json={"stars": 5})
        assert answer.status_code == 429
        assert answer.json()["detail"]["code"] == "rate_limited"

    def test_the_hosts_own_401_is_a_403_so_the_APP_is_not_signed_out(self, tmp_path):
        refused = (401, {"code": "unauthorized", "detail": "the token is not valid"})
        with hosted_proxy_app(tmp_path, responder=rating_responder(put=refused)) as app:
            sign_in(app.state)
            answer = app.client.put(RATING_URL, json={"stars": 5})
        assert answer.status_code == 403
        assert answer.json()["detail"]["code"] == "unauthorized"

    def test_an_unknown_item_is_relayed_as_404(self, tmp_path):
        unknown = (404, {"code": "unknown_item", "detail": "the catalog has no such item"})
        with hosted_proxy_app(tmp_path, responder=rating_responder(put=unknown)) as app:
            sign_in(app.state)
            answer = app.client.put(RATING_URL, json={"stars": 5})
        assert answer.status_code == 404
        assert answer.json()["detail"]["code"] == "unknown_item"

    def test_an_unreachable_host_is_a_502_and_never_a_fake_success(self, tmp_path):

        def explode(_request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("no route to host")

        with hosted_proxy_app(tmp_path, responder=explode) as app:
            sign_in(app.state)
            answer = app.client.put(RATING_URL, json={"stars": 5})
        assert answer.status_code == 502
        assert answer.json()["detail"]["code"] == "unavailable"
        assert "your_stars" not in answer.text


class TestTheBodyThisServerRefusesItself:

    def test_a_json_true_is_NOT_accepted_as_one_star(self, tmp_path):
        with hosted_proxy_app(tmp_path, responder=rating_responder()) as app:
            sign_in(app.state)
            answer = app.client.put(RATING_URL, json={"stars": True})
            assert app.sent == []
        assert answer.status_code == 400
        assert answer.json()["detail"]["code"] == "bad_request"

    def test_PAIRED_POSITIVE_a_real_integer_still_goes_through(self, tmp_path):
        with hosted_proxy_app(tmp_path, responder=rating_responder()) as app:
            sign_in(app.state)
            answer = app.client.put(RATING_URL, json={"stars": 5})
            assert len(app.sent) == 1
        assert answer.status_code == 200


class TestTheTokenNeverReachesTheBrowser:

    def test_no_rating_response_prints_the_access_or_refresh_token(self, tmp_path):
        with hosted_proxy_app(tmp_path, responder=rating_responder()) as app:
            sign_in(app.state, access_in=-10)
            bodies = [
                app.client.put(RATING_URL, json={"stars": 5}).text,
                app.client.delete(RATING_URL).text,
            ]
        for body in bodies:
            for secret in (
                "FIRST-ACCESS-SECRET", "FIRST-REFRESH-SECRET",
                "SECOND-ACCESS-SECRET", "SECOND-REFRESH-SECRET",
            ):
                assert secret not in body


class TestAnItemIdIsStillNotAFreePathSegment:

    def test_an_encoded_traversal_is_refused_and_sends_nothing(self, tmp_path):
        with hosted_proxy_app(tmp_path, responder=rating_responder()) as app:
            sign_in(app.state)
            answer = app.client.put(
                "/catalog/items/a/%2e%2e/%2e%2e/auth/refresh/rating", json={"stars": 5}
            )
            assert app.sent == []
        assert answer.status_code == 400
        assert answer.json()["detail"]["code"] == "bad_item_id"

    def test_PAIRED_POSITIVE_an_ordinary_id_with_its_slash_goes_through(self, tmp_path):
        with hosted_proxy_app(tmp_path, responder=rating_responder()) as app:
            sign_in(app.state)
            app.client.put(RATING_URL, json={"stars": 5})
            assert app.paths() == ["/api/v1/items/example-owner/sme/rating"]


class TestTheRoutesAreActuallyMounted:

    def test_the_write_paths_are_answered_by_the_WRITE_routes(self, tmp_path):
        with hosted_proxy_app(
            tmp_path, responder=rating_responder(), include_aggregator=True
        ) as app:
            sign_in(app.state)
            answer = app.client.put(RATING_URL, json={"stars": 5})
            assert app.paths() == ["/api/v1/items/example-owner/sme/rating"]
        assert answer.status_code == 200
        assert answer.json()["your_stars"] == 5
