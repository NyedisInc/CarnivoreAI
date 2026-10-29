
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import httpx

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_chr_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_chr_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from tests.helpers.hosted_routes_app import hosted_proxy_app, json_responder

SUMMARY = {
    "count": 2,
    "average": 4.5,
    "histogram": {"1": 0, "2": 0, "3": 0, "4": 1, "5": 1},
    "reviews": [
        {"login": "example-owner", "stars": 5, "text": "great", "updated_at": 1789000000},
        {"login": "someone", "stars": 4, "text": "good", "updated_at": 1788000000},
    ],
    "item_id": "example-owner/sme",
}


class TestTheReadIsForwarded:

    def test_the_hosted_body_comes_back_unchanged(self, tmp_path):
        with hosted_proxy_app(tmp_path, responder=json_responder(SUMMARY)) as app:
            answer = app.client.get("/catalog/items/example-owner/sme/ratings")
        assert answer.status_code == 200
        assert answer.json() == SUMMARY

    def test_an_explicit_null_review_field_remains_present(self, tmp_path: Path) -> None:
        summary = {**SUMMARY, "reviews": [{**SUMMARY["reviews"][0], "publisher": None}]}
        with hosted_proxy_app(tmp_path, responder=json_responder(summary)) as app:
            answer = app.client.get("/catalog/items/example-owner/sme/ratings")
        assert answer.status_code == 200
        assert answer.json() == summary

    def test_the_item_id_keeps_its_slash_on_the_way_upstream(self, tmp_path):
        with hosted_proxy_app(tmp_path, responder=json_responder(SUMMARY)) as app:
            app.client.get("/catalog/items/example-owner/sme/ratings")
            assert app.paths() == ["/api/v1/items/example-owner/sme/ratings"]

    def test_the_read_carries_no_bearer_because_it_needs_none(self, tmp_path):
        with hosted_proxy_app(tmp_path, responder=json_responder(SUMMARY)) as app:
            app.client.get("/catalog/items/example-owner/sme/ratings")
            assert app.sent[0].headers.get("authorization") is None

    def test_a_real_zero_comes_back_as_a_real_zero(self, tmp_path):
        empty = {
            "count": 0,
            "average": 0,
            "histogram": {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0},
            "reviews": [],
            "item_id": "example-owner/sme",
        }
        with hosted_proxy_app(tmp_path, responder=json_responder(empty)) as app:
            answer = app.client.get("/catalog/items/example-owner/sme/ratings")
        assert answer.status_code == 200
        assert answer.json()["count"] == 0
        assert answer.json()["reviews"] == []

    def test_an_omitted_reviews_key_is_NOT_turned_into_an_empty_list(self, tmp_path):
        without = {"count": 2, "average": 4.5, "item_id": "example-owner/sme"}
        with hosted_proxy_app(tmp_path, responder=json_responder(without)) as app:
            answer = app.client.get("/catalog/items/example-owner/sme/ratings")
        assert answer.json()["reviews"] is None


class TestWhenTheHostRefusesOrIsGone:

    def test_an_unreachable_host_is_a_502_and_not_an_empty_summary(self, tmp_path):

        def explode(_request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("no route to host")

        with hosted_proxy_app(tmp_path, responder=explode) as app:
            answer = app.client.get("/catalog/items/example-owner/sme/ratings")
        assert answer.status_code == 502
        assert answer.json()["detail"]["code"] == "unavailable"
        assert "count" not in answer.text

    def test_a_hosted_404_reaches_the_client_as_a_404_with_its_code(self, tmp_path):
        refusal = {"code": "unknown_item", "detail": "the catalog has no such item"}
        with hosted_proxy_app(
            tmp_path, responder=json_responder(refusal, status=404)
        ) as app:
            answer = app.client.get("/catalog/items/example-owner/nope/ratings")
        assert answer.status_code == 404
        assert answer.json()["detail"]["code"] == "unknown_item"

    def test_a_hosted_400_keeps_its_own_status(self, tmp_path):
        refusal = {"code": "bad_item_id", "detail": "that is not a valid item id"}
        with hosted_proxy_app(
            tmp_path, responder=json_responder(refusal, status=400)
        ) as app:
            answer = app.client.get("/catalog/items/NOPE/x/ratings")
        assert answer.status_code == 400
        assert answer.json()["detail"]["code"] == "bad_item_id"


class TestTheRouteIsActuallyMounted:

    def test_the_ratings_path_is_answered_by_the_RATINGS_route(self, tmp_path):
        with hosted_proxy_app(
            tmp_path, responder=json_responder(SUMMARY), include_aggregator=True
        ) as app:
            answer = app.client.get("/catalog/items/example-owner/sme/ratings")
            assert app.paths() == ["/api/v1/items/example-owner/sme/ratings"]
        assert answer.status_code == 200
        assert answer.json()["average"] == 4.5

    def test_the_sign_in_paths_are_answered_too(self, tmp_path):
        with hosted_proxy_app(
            tmp_path, responder=json_responder(SUMMARY), include_aggregator=True
        ) as app:
            assert app.client.get("/catalog/auth/session").status_code == 200
            assert app.client.post("/catalog/auth/signout").status_code == 200
            assert app.client.post("/catalog/auth/device/start").status_code != 404
            assert app.client.post(
                "/catalog/auth/device/poll", json={"flow_id": "nope"}
            ).status_code == 400

    def test_a_path_the_aggregator_never_had_is_still_a_404(self, tmp_path):
        with hosted_proxy_app(
            tmp_path, responder=json_responder(SUMMARY), include_aggregator=True
        ) as app:
            assert app.client.get("/catalog/auth/not_a_route").status_code == 404


class TestAnItemIdIsNotAFreePathSegment:

    def test_the_guard_itself_refuses_a_traversing_id(self):
        from fastapi import HTTPException

        from src.api.catalog_hosted_routes import _safe_item_id

        for hostile in ("a/../b", "../etc", "a//b", "a/./b", ""):
            try:
                _safe_item_id(hostile)
            except HTTPException as exc:
                assert exc.status_code == 400
                assert exc.detail["code"] == "bad_item_id"
            else:
                raise AssertionError(f"{hostile!r} was not refused")

    def test_the_guard_still_passes_an_ordinary_id(self):
        from src.api.catalog_hosted_routes import _safe_item_id

        assert _safe_item_id("example-owner/sme") == "example-owner/sme"
        assert _safe_item_id("example-owner/my.skill_v2-b") == "example-owner/my.skill_v2-b"

    def test_an_encoded_traversal_is_refused_and_sends_nothing_upstream(self, tmp_path):
        with hosted_proxy_app(tmp_path, responder=json_responder(SUMMARY)) as app:
            answer = app.client.get(
                "/catalog/items/a/%2e%2e/%2e%2e/auth/device/start/ratings"
            )
            assert app.sent == []
        assert answer.status_code == 400
        assert answer.json()["detail"]["code"] == "bad_item_id"

    def test_an_ordinary_id_with_a_slash_still_goes_through(self, tmp_path):
        with hosted_proxy_app(tmp_path, responder=json_responder(SUMMARY)) as app:
            answer = app.client.get("/catalog/items/example-owner/sme/ratings")
            assert app.paths() == ["/api/v1/items/example-owner/sme/ratings"]
        assert answer.status_code == 200
