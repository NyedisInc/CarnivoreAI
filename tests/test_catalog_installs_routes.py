
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import httpx

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_cir_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_cir_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from tests.helpers.hosted_routes_app import hosted_proxy_app, json_responder

SUMMARY = {
    "count": 2,
    "by_version": {"1.0.0": 1, "1.1.0": 1},
    "item_id": "example-owner/sme",
}


class TestTheReadIsForwarded:

    def test_the_hosted_body_comes_back_unchanged(self, tmp_path):
        with hosted_proxy_app(tmp_path, responder=json_responder(SUMMARY)) as app:
            answer = app.client.get("/catalog/items/example-owner/sme/installs")
        assert answer.status_code == 200
        assert answer.json() == SUMMARY

    def test_the_item_id_keeps_its_slash_on_the_way_upstream(self, tmp_path):
        with hosted_proxy_app(tmp_path, responder=json_responder(SUMMARY)) as app:
            app.client.get("/catalog/items/example-owner/sme/installs")
            assert app.paths() == ["/api/v1/items/example-owner/sme/installs"]

    def test_the_read_carries_no_bearer_because_it_needs_none(self, tmp_path):
        with hosted_proxy_app(tmp_path, responder=json_responder(SUMMARY)) as app:
            app.client.get("/catalog/items/example-owner/sme/installs")
            assert app.sent[0].headers.get("authorization") is None

    def test_the_route_is_really_registered_in_the_assembled_table(self, tmp_path):
        with hosted_proxy_app(
            tmp_path, responder=json_responder(SUMMARY), include_aggregator=True
        ) as app:
            answer = app.client.get("/catalog/items/example-owner/sme/installs")
        assert answer.status_code == 200
        assert answer.json()["count"] == 2


class TestAMeasuredZeroAndAnOutageAreDifferentSENTENCES:

    def test_a_real_zero_comes_back_as_a_real_zero(self, tmp_path):
        empty = {"count": 0, "by_version": {}, "item_id": "example-owner/sme"}
        with hosted_proxy_app(tmp_path, responder=json_responder(empty)) as app:
            answer = app.client.get("/catalog/items/example-owner/sme/installs")
        assert answer.status_code == 200
        assert answer.json()["count"] == 0
        assert answer.json()["by_version"] == {}

    def test_an_unreachable_host_is_a_502_and_NOT_a_count_of_zero(self, tmp_path):

        def refuse(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("no route to host", request=request)

        with hosted_proxy_app(tmp_path, responder=refuse) as app:
            answer = app.client.get("/catalog/items/example-owner/sme/installs")
        assert answer.status_code == 502
        assert answer.json()["detail"]["code"] == "unavailable"
        assert "count" not in answer.json()

    def test_an_omitted_by_version_is_NOT_turned_into_an_empty_map(self, tmp_path):
        without = {"count": 2, "item_id": "example-owner/sme"}
        with hosted_proxy_app(tmp_path, responder=json_responder(without)) as app:
            answer = app.client.get("/catalog/items/example-owner/sme/installs")
        assert answer.status_code == 200
        assert answer.json()["by_version"] is None

    def test_an_omitted_count_is_NOT_turned_into_zero(self, tmp_path):
        without = {"item_id": "example-owner/sme"}
        with hosted_proxy_app(tmp_path, responder=json_responder(without)) as app:
            answer = app.client.get("/catalog/items/example-owner/sme/installs")
        assert answer.json()["count"] is None


class TestWhenTheHostRefuses:

    def test_an_unknown_item_reaches_the_client_as_a_404_with_its_code(self, tmp_path):
        refusal = {"code": "unknown_item", "detail": "the catalog has no such item"}
        with hosted_proxy_app(
            tmp_path, responder=json_responder(refusal, status=404)
        ) as app:
            answer = app.client.get("/catalog/items/example-owner/nope/installs")
        assert answer.status_code == 404
        assert answer.json()["detail"]["code"] == "unknown_item"

    def test_an_encoded_traversal_is_refused_and_sends_nothing_upstream(self, tmp_path):
        with hosted_proxy_app(tmp_path, responder=json_responder(SUMMARY)) as app:
            answer = app.client.get("/catalog/items/%2E%2E/auth/installs")
            assert app.sent == []
        assert answer.status_code == 400
        assert answer.json()["detail"]["code"] == "bad_item_id"


class TestTheBatchRead:

    @staticmethod
    def _echo(fail_when=None):
        import json

        def respond(request):
            ids = json.loads(request.content)["ids"]
            if fail_when and fail_when(ids):
                return httpx.Response(503, json={"code": "down", "detail": "x"})
            return httpx.Response(
                200, json={"items": {i: {"count": 0, "by_version": {"1.0.0": 0}} for i in ids}}
            )

        return respond

    def test_250_ids_make_two_hosted_posts_and_the_answers_merge(self, tmp_path):
        import json

        ids = [f"a/item{n}" for n in range(250)]
        with hosted_proxy_app(tmp_path, responder=self._echo()) as app:
            answer = app.client.post("/catalog/install-counts", json={"ids": ids + ids[:5]})
        assert answer.status_code == 200
        assert app.paths() == ["/api/v1/install-counts"] * 2
        assert [r.method for r in app.sent] == ["POST", "POST"]
        sizes = [len(json.loads(r.content)["ids"]) for r in app.sent]
        assert sizes == [200, 50]
        assert set(answer.json()["items"]) == set(ids)
        assert answer.json()["items"]["a/item7"] == {"count": 0, "by_version": {"1.0.0": 0}}

    def test_a_failed_chunk_leaves_its_ids_out(self, tmp_path):
        ids = [f"a/item{n}" for n in range(250)]
        with hosted_proxy_app(
            tmp_path, responder=self._echo(lambda got: len(got) == 200)
        ) as app:
            answer = app.client.post("/catalog/install-counts", json={"ids": ids})
        assert answer.status_code == 200
        assert set(answer.json()["items"]) == set(ids[200:])

    def test_every_chunk_failing_answers_as_the_per_item_route_does(self, tmp_path):
        with hosted_proxy_app(tmp_path, responder=self._echo(lambda got: True)) as app:
            answer = app.client.post("/catalog/install-counts", json={"ids": ["a/b"]})
        assert answer.status_code == 503

    def test_an_unsafe_id_is_refused_and_sends_nothing(self, tmp_path):
        with hosted_proxy_app(tmp_path, responder=self._echo()) as app:
            answer = app.client.post("/catalog/install-counts", json={"ids": ["a/../b"]})
        assert answer.status_code == 400
        assert app.sent == []

    def test_the_route_requires_auth(self):
        from src.api import catalog_hosted_routes
        from src.api.auth import require_auth

        route = next(
            r for r in catalog_hosted_routes.router.routes if r.path == "/catalog/install-counts"
        )
        assert require_auth in [d.call for d in route.dependant.dependencies]
