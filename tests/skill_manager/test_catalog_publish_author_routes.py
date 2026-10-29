
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_cpa_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_cpa_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.api import catalog_publish_author_routes as author_routes
from src.api.auth import require_auth
from src.core.catalog import submissions_watch
from src.core.catalog.token_store import CatalogSession, open_token_store
from tests.helpers import hosted_catalog_fake as fake
from tests.helpers import submissions_harness as h
from tests.helpers.hosted_routes_app import hosted_proxy_app, route_responder

FIXTURES = ROOT / "tests" / "fixtures" / "publish_page"
SID = "a" * 32


def golden(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def sign_in(state: Path) -> None:
    now = int(time.time())
    with open_token_store(state) as store:
        store.save(CatalogSession(
            login="bob", access_token="HELD-ACCESS-SECRET", access_expires_at=now + 3600,
            refresh_token="HELD-REFRESH-SECRET", refresh_expires_at=now + 86400,
        ))


@pytest.fixture
def written(monkeypatch):
    calls: list = []
    monkeypatch.setattr(submissions_watch, "after_write", lambda request: calls.append(request))
    return calls


def test_every_route_needs_auth() -> None:
    wanted = {
        ("POST", "/catalog/submissions/{submission_id}/appeal"),
        ("POST", "/catalog/submissions/{submission_id}/withdraw"),
        ("GET", "/catalog/submissions/limits"),
        ("GET", "/catalog/publish/rules"),
    }
    found = set()
    for route in author_routes.router.routes:
        for method in route.methods:
            found.add((method, route.path))
            assert any(d.call is require_auth for d in route.dependant.dependencies), route.path
    assert found == wanted


def test_appeal_relays_the_text_with_the_bearer_and_passes_the_refusals_through(tmp_path, written) -> None:
    sent = {"submission_id": SID, "status": "pending", "appeals": 1, "extra": "dropped"}
    with hosted_proxy_app(tmp_path, responder=route_responder({f"/submissions/{SID}/appeal": (200, sent)}), include_aggregator=True) as app:
        sign_in(app.state)
        answer = app.client.post(f"/catalog/submissions/{SID}/appeal", json={"text": "fixed it"})
        assert answer.status_code == 200
        assert answer.json() == {"submission_id": SID, "status": "pending", "appeals": 1}
        (request,) = app.sent
        assert request.url.path == f"/api/v1/submissions/{SID}/appeal"
        assert request.headers["authorization"] == "Bearer HELD-ACCESS-SECRET"
        assert json.loads(request.content) == {"text": "fixed it"}
        assert len(written) == 1
        assert "HELD-ACCESS-SECRET" not in answer.text
    for code in ("appeal_limit", "not_rejected", "kind_closed"):
        refusal = {"code": code, "detail": "no"}
        with hosted_proxy_app(tmp_path / code, responder=route_responder({"/appeal": (409, refusal)}), include_aggregator=True) as app:
            sign_in(app.state)
            answer = app.client.post(f"/catalog/submissions/{SID}/appeal", json={"text": "x"})
            assert answer.status_code == 409 and answer.json()["detail"]["code"] == code
    assert len(written) == 1, "a refused appeal changes nothing, so it names no topic"


def test_a_bad_id_or_an_empty_note_is_refused_before_any_relay(tmp_path, written) -> None:
    with hosted_proxy_app(tmp_path, responder=route_responder({}), include_aggregator=True) as app:
        sign_in(app.state)
        for bad in ("../x", "A" * 32, "abc", "g" * 32):
            assert app.client.post(f"/catalog/submissions/{bad}/withdraw").status_code in (404, 405)
        assert app.client.post(f"/catalog/submissions/{SID}/appeal", json={"text": ""}).status_code == 422
        assert app.sent == [] and written == []


def test_withdraw_relays_passes_not_withdrawable_and_notifies_once(tmp_path, written) -> None:
    ok = {"submission_id": SID, "status": "withdrawn"}
    with hosted_proxy_app(tmp_path, responder=route_responder({"/withdraw": (200, ok)}), include_aggregator=True) as app:
        sign_in(app.state)
        answer = app.client.post(f"/catalog/submissions/{SID}/withdraw")
        assert answer.status_code == 200 and answer.json() == {"submission_id": SID, "status": "withdrawn", "appeals": None}
        (request,) = app.sent
        assert request.url.path == f"/api/v1/submissions/{SID}/withdraw"
        assert request.headers["authorization"] == "Bearer HELD-ACCESS-SECRET"
        assert len(written) == 1
    refusal = {"code": "not_withdrawable", "detail": "no"}
    with hosted_proxy_app(tmp_path / "late", responder=route_responder({"/withdraw": (409, refusal)}), include_aggregator=True) as app:
        sign_in(app.state)
        answer = app.client.post(f"/catalog/submissions/{SID}/withdraw")
        assert answer.status_code == 409 and answer.json()["detail"]["code"] == "not_withdrawable"
    assert len(written) == 1


def test_limits_relays_the_hosted_answer_and_equals_the_golden(tmp_path) -> None:
    hosted = golden("hosted_limits.json")
    with hosted_proxy_app(tmp_path, responder=route_responder({"/submissions/limits": (200, {**hosted, "token": "x"})}), include_aggregator=True) as app:
        sign_in(app.state)
        answer = app.client.get("/catalog/submissions/limits")
        assert answer.status_code == 200
        assert answer.json() == golden("limits.json") == hosted
        (request,) = app.sent
        assert request.url.path == "/api/v1/submissions/limits"
        assert request.headers["authorization"] == "Bearer HELD-ACCESS-SECRET"


def test_limits_cut_down_what_the_host_did_not_send_to_null(tmp_path) -> None:
    with hosted_proxy_app(tmp_path, responder=route_responder({"/submissions/limits": (200, {"per_day": 5})}), include_aggregator=True) as app:
        sign_in(app.state)
        body = app.client.get("/catalog/submissions/limits").json()
        assert body["per_day"] == 5 and body["media_per_day"] is None and body["cooldown_until"] == ""


def test_rules_equal_the_golden_and_carry_no_path_or_token(tmp_path) -> None:
    with hosted_proxy_app(tmp_path, responder=route_responder({}), include_aggregator=True) as app:
        answer = app.client.get("/catalog/publish/rules")
        assert answer.status_code == 200
        assert answer.json() == golden("rules.json")
        assert app.sent == []
        assert str(ROOT) not in answer.text and "HELD" not in answer.text


def test_rules_open_flags_follow_the_policy_file(tmp_path, monkeypatch) -> None:
    policy = tmp_path / "policy.json"
    kinds = {"skill": "closed", "theme": "first_party", "claude-code-plugin": "closed", "mod": "open", "cplug": "open"}
    policy.write_text(json.dumps({"kinds": kinds}))
    monkeypatch.setattr(author_routes, "_POLICY_PATH", policy)
    with hosted_proxy_app(tmp_path, responder=route_responder({}), include_aggregator=True) as app:
        flags = {k["kind"]: k["open"] for k in app.client.get("/catalog/publish/rules").json()["kinds"]}
        assert flags == {"skills": False, "themes": False, "mods": True, "plugins": True}
        policy.write_text(json.dumps({"kinds": {**kinds, "cplug": "closed"}}))
        flags = {k["kind"]: k["open"] for k in app.client.get("/catalog/publish/rules").json()["kinds"]}
        assert flags["plugins"] is False
        policy.write_text("not json")
        assert app.client.get("/catalog/publish/rules").status_code == 503


def test_the_caps_are_the_hosts() -> None:
    with fake.lambda_modules(h.JWT_TEST_SECRET) as api:
        media, kinds = api.validate_media, api.validate_kinds
        caps = author_routes._HERO_CAPS
        assert caps["hero_max_bytes"] == media.MAX_BYTES
        assert (caps["hero_min_width"], caps["hero_min_height"]) == (media.MIN_WIDTH, media.MIN_HEIGHT)
        assert (caps["hero_max_side"], caps["hero_max_pixels"]) == (media.MAX_SIDE, media.MAX_PIXELS)
        assert (caps["hero_ratio_min"], caps["hero_ratio_max"]) == (media.RATIO_MIN, media.RATIO_MAX)
        mine = author_routes._kind_caps()
        for kind, limits in kinds.KIND_LIMITS.items():
            assert mine[f"{kind}_members"] == limits["members"], kind
            assert mine[f"{kind}_file_bytes"] == limits["file"], kind
            assert mine[f"{kind}_total_bytes"] == limits["total"], kind
