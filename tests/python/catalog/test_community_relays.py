
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_ccr_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_ccr_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
import httpx
import pytest

from src.core.catalog.token_store import CatalogSession, open_token_store
from tests.helpers.hosted_routes_app import hosted_proxy_app

ITEM = "/catalog/items/acme/sme"
CID = "1750000000000abcdef"

COMMENT = {
    "comment_id": CID, "parent_id": None,
    "author": {"handle": "ann", "publisher": False, "author_id": "LEAK-ID", "email": "a@b.c"},
    "body": "nice", "created_at": 1, "edited": False, "edited_at": None,
    "author_id": "LEAK-ID", "email": "a@b.c",
}
PROFILE = {"handle": "ann", "joined": "2026-01-01", "bio": "", "links": [], "items": [],
           "publisher": False, "github_login": None, "email": "a@b.c", "user_id": "LEAK-ID"}


def sign_in(state: Path) -> None:
    now = int(time.time())
    with open_token_store(state) as store:
        store.save(CatalogSession(
            login="ann", access_token="ACCESS-SECRET", access_expires_at=now + 3600,
            refresh_token="REFRESH-SECRET", refresh_expires_at=now + 100000,
        ))


def responder(status: int = 200, body=None):
    payload = {"comment": COMMENT, "comments": [COMMENT], "cursor": None, "reported": True,
               "deleted": True, "comment_id": CID, "notify_replies": True, **PROFILE} \
        if body is None else body
    return lambda _req: httpx.Response(status, json=payload)


WRITES = [
    ("post", ITEM + "/comments", {"body": "hi"}),
    ("put", f"{ITEM}/comments/{CID}", {"body": "hi"}),
    ("delete", f"{ITEM}/comments/{CID}", None),
    ("post", "/catalog/reports", {"kind": "comment", "item_id": "acme/sme",
                                   "comment_id": CID, "reason": "spam"}),
    ("put", "/catalog/me/profile", {"bio": "x"}),
    ("put", "/catalog/me/mail-preference", {"notify_replies": False}),
]


def call(app, verb, url, body):
    fn = getattr(app.client, verb)
    return fn(url, json=body) if body is not None else fn(url)


@pytest.mark.parametrize("verb,url,body", WRITES)
def test_signed_out_writes_are_refused_before_any_outbound_call(tmp_path, verb, url, body):
    with hosted_proxy_app(tmp_path, responder=responder()) as app:
        answer = call(app, verb, url, body)
        assert app.sent == []
    assert answer.status_code == 403
    assert answer.json()["detail"]["code"] == "unauthorized"


@pytest.mark.parametrize("verb,url,body", WRITES)
def test_writes_attach_the_stored_bearer(tmp_path, verb, url, body):
    with hosted_proxy_app(tmp_path, responder=responder()) as app:
        sign_in(app.state)
        answer = call(app, verb, url, body)
        assert answer.status_code in (200, 201)
        assert [r.headers.get("authorization") for r in app.sent] == ["Bearer ACCESS-SECRET"]


def test_reads_work_signed_out_and_carry_no_bearer(tmp_path):
    with hosted_proxy_app(tmp_path, responder=responder()) as app:
        thread = app.client.get(ITEM + "/comments?cursor=abc")
        profile = app.client.get("/catalog/profiles/ann")
        assert thread.status_code == 200 and profile.status_code == 200
        assert len(app.sent) == 2
        assert all("authorization" not in r.headers for r in app.sent)
        assert "cursor=abc" in str(app.sent[0].url)
    assert thread.json()["comments"][0]["body"] == "nice"
    assert profile.json()["handle"] == "ann"


def test_reading_your_own_comments_needs_a_sign_in(tmp_path):
    with hosted_proxy_app(tmp_path, responder=responder()) as app:
        assert app.client.get("/catalog/me/comments").status_code == 403
        assert app.sent == []
        sign_in(app.state)
        assert app.client.get("/catalog/me/comments").status_code == 200
        assert app.sent[0].headers["authorization"] == "Bearer ACCESS-SECRET"


def test_a_registration_check_403_passes_through_with_its_code(tmp_path):
    gate = {"code": "handle_required", "detail": "choose a handle first"}
    with hosted_proxy_app(tmp_path, responder=responder(403, gate)) as app:
        sign_in(app.state)
        answer = app.client.post(ITEM + "/comments", json={"body": "hi"})
    assert answer.status_code == 403
    assert answer.json()["detail"]["code"] == "handle_required"


def test_a_revoked_session_401_signs_out_locally(tmp_path):
    revoked = {"code": "session_revoked", "detail": "signed out"}
    with hosted_proxy_app(tmp_path, responder=responder(401, revoked)) as app:
        sign_in(app.state)
        answer = app.client.post(ITEM + "/comments", json={"body": "hi"})
        with open_token_store(app.state) as store:
            held = store.read()
        follow = app.client.post(ITEM + "/comments", json={"body": "hi"})
        assert len(app.sent) == 1
    assert answer.status_code == 403
    assert held is None
    assert follow.json()["detail"]["code"] == "unauthorized"


def test_a_revoked_answer_never_clears_a_pair_saved_while_the_request_was_out(tmp_path):
    revoked = {"code": "session_revoked", "detail": "signed out"}
    holder = {}

    def newer_pair_lands_then_revoked(_request):
        with open_token_store(holder["state"]) as store:
            store.save(CatalogSession(
                login="ann", access_token="NEWER-ACCESS", access_expires_at=int(time.time()) + 3600,
                refresh_token="NEWER-REFRESH", refresh_expires_at=int(time.time()) + 100000))
        return httpx.Response(401, json=revoked)

    with hosted_proxy_app(tmp_path, responder=newer_pair_lands_then_revoked) as app:
        sign_in(app.state)
        holder["state"] = app.state
        app.client.post(ITEM + "/comments", json={"body": "hi"})
        with open_token_store(app.state) as store:
            held = store.read()
    assert held is not None and held.access_token == "NEWER-ACCESS"


def test_responses_carry_no_author_id_or_email(tmp_path):
    with hosted_proxy_app(tmp_path, responder=responder()) as app:
        sign_in(app.state)
        answers = [
            app.client.get(ITEM + "/comments"),
            app.client.get("/catalog/profiles/ann"),
            app.client.get("/catalog/me/comments"),
            app.client.post(ITEM + "/comments", json={"body": "hi"}),
            app.client.put("/catalog/me/profile", json={"bio": "x"}),
        ]
    text = json.dumps([a.json() for a in answers])
    assert "LEAK-ID" not in text and "a@b.c" not in text
    assert "author_id" not in text and "email" not in text


def test_a_traversal_segment_never_reaches_the_host(tmp_path):
    with hosted_proxy_app(tmp_path, responder=responder()) as app:
        sign_in(app.state)
        assert app.client.delete(f"{ITEM}/comments/..").status_code in (400, 404, 405)
        assert app.client.get("/catalog/profiles/..%2Fme").status_code in (400, 404)
        assert app.sent == []


def test_the_routes_are_registered_in_the_aggregator(tmp_path):
    with hosted_proxy_app(tmp_path, responder=responder(), include_aggregator=True) as app:
        assert app.client.get(ITEM + "/comments").status_code == 200
        assert app.paths() == ["/api/v1/items/acme/sme/comments"]
