
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from tests.helpers import hosted_catalog_fake as fake
from tests.helpers import submissions_harness as h

TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")
YESTERDAY = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")


@pytest.fixture(scope="module")
def api():
    with fake.lambda_modules(h.JWT_TEST_SECRET) as namespace:
        fake.seed_index(namespace, {h.PUBLISHED_ITEM})
        yield namespace


@pytest.fixture(autouse=True)
def clean(api, monkeypatch):
    h.reset(api)
    monkeypatch.setattr(api.http_api, "ADMIN_GITHUB_USER_ID", h.ADMIN_ID)


def _users(api):
    table = api.tables.setdefault(
        api.store.USERS_TABLE, fake.FakeTable(api.store.USERS_TABLE, api.log)
    )
    api.store._resources[api.store.USERS_TABLE] = table
    return table




def test_the_positive_control_a_good_submission_is_stored(api):
    response = h.submit(api)
    assert response["statusCode"] == 201, h.body_of(response)
    submission_id = h.body_of(response)["submission_id"]
    assert len(submission_id) == 32
    assert f"pending/{submission_id}/files/SKILL.md" in api.s3.objects
    assert f"pending/{submission_id}/meta.json" in api.s3.objects
    row = api.tables[api.submissions.SUBMISSIONS_TABLE].stored(
        {"submission_id": submission_id}
    )
    assert row["status"] == "pending"
    assert row["item_id"] == "adoom666/work"
    assert row["submitted_by_login"] == "adoom666"
    assert len(row["content_sha256"]) == 64


def test_the_handle_comes_from_the_token_not_the_body(api):
    response = h.submit(
        api, h.submission(**{"handle": "someoneelse"}), h.token(api, "7", "MixedCase")
    )
    assert response["statusCode"] == 201, h.body_of(response)
    assert h.body_of(response)["item_id"] == "mixedcase/work"




@pytest.mark.parametrize("payload,code", [
    (h.submission(name="UPPER"), "submission_invalid"),
    (h.submission(name="../etc"), "submission_invalid"),
    (h.submission(name="ends."), "submission_invalid"),
    (h.submission(name=""), "submission_invalid"),
    (h.submission(name="security-review"), "name_reserved"),
    (json.dumps({"name": "work"}), "submission_invalid"),
    (json.dumps({"name": "work", "files": []}), "submission_invalid"),
    (h.submission(files=[{"path": "/etc/passwd", "content_base64": h.b64("x")}]),
     "submission_invalid"),
    (h.submission(files=[{"path": "../out", "content_base64": h.b64("x")}]),
     "submission_invalid"),
    (h.submission(files=[{"path": "a/../b", "content_base64": h.b64("x")}]),
     "submission_invalid"),
    (h.submission(files=[{"path": "café.md", "content_base64": h.b64("x")}]),
     "submission_invalid"),
    (h.submission(files=[{"path": "a\\b", "content_base64": h.b64("x")}]),
     "submission_invalid"),
    (h.submission(files=[{"path": "SKILL.md", "content_base64": "not base64!"}]),
     "submission_invalid"),
    (h.submission(files=[{"path": "README.md", "content_base64": h.b64("x")}]),
     "submission_invalid"),
    (h.submission(files=[
        {"path": "SKILL.md", "content_base64": h.b64(h.skill_md())},
        {"path": "skill.md", "content_base64": h.b64("dupe")},
     ]), "submission_invalid"),
    (h.submission(files=[
        {"path": "nested/SKILL.md", "content_base64": h.b64(h.skill_md())},
        {"path": "SKILL.md", "content_base64": h.b64(h.skill_md())},
     ]), "submission_invalid"),
    (h.submission(files=[
        {"path": "SKILL.md", "content_base64": h.b64("no front matter at all")},
     ]), "submission_invalid"),
    (h.submission(files=[
        {"path": "SKILL.md", "content_base64": h.b64(h.skill_md(name="other"))},
     ]), "submission_invalid"),
    (h.submission(files=[
        {"path": "SKILL.md", "content_base64": h.b64(h.skill_md(description=""))},
     ]), "submission_invalid"),
    (h.submission(files=[
        {"path": "SKILL.md", "content_base64": h.b64(h.skill_md())},
        {"path": "scripts/go.sh", "content_base64": h.b64("#!/bin/sh")},
     ]), "scripts_not_supported"),
    (h.submission(version="not-a-version"), "submission_invalid"),
])
def test_a_refusal_costs_no_storage_at_all(api, payload, code):
    response = h.submit(api, payload)
    assert response["statusCode"] in (400, 409), h.body_of(response)
    assert h.body_of(response)["code"] == code, h.body_of(response)
    assert api.s3.objects == {}
    assert h.storage_calls(api) == [], api.log


def test_an_unsigned_submission_is_refused_before_anything(api):
    response = api.app.handler(
        h.event("POST", "/v1/submissions", h.submission())
    )
    assert response["statusCode"] == 401
    assert h.storage_calls(api) == []




def test_the_declared_total_is_refused_before_a_single_decode(api, monkeypatch):
    decodes = []
    real_decode = api.validate_upload._decode

    def spy(*args, **kwargs):
        decodes.append(1)
        return real_decode(*args, **kwargs)

    monkeypatch.setattr(api.validate_upload, "_decode", spy)
    oversize = "A" * (api.validate_upload.MAX_SUBMISSION_BYTES + 1024)
    response = h.submit(api, h.submission(files=[
        {"path": "SKILL.md", "content_base64": h.b64(h.skill_md())},
        {"path": "big.bin", "content_base64": oversize},
    ]))
    assert response["statusCode"] == 413
    assert h.body_of(response)["code"] == "body_too_large"
    assert decodes == [], "the cap was checked AFTER decoding, not before"
    assert api.s3.objects == {}


def test_one_oversized_file_is_refused(api):
    big = h.b64("x" * (api.validate_upload.MAX_FILE_BYTES + 1))
    response = h.submit(api, h.submission(files=[
        {"path": "SKILL.md", "content_base64": h.b64(h.skill_md())},
        {"path": "big.bin", "content_base64": big},
    ]))
    assert response["statusCode"] == 413
    assert api.s3.objects == {}


def test_the_raw_body_cap_refuses_before_the_json_is_parsed(api):
    huge = "x" * (api.routes_submit.MAX_SUBMIT_BODY_BYTES + 1)
    response = h.submit(api, huge)
    assert response["statusCode"] == 413
    assert h.body_of(response)["code"] == "body_too_large"
    assert h.storage_calls(api) == []


def test_the_other_routes_keep_the_small_body_cap(api):
    assert api.http_api.MAX_BODY_BYTES == 8 * 1024
    assert api.routes_submit.MAX_SUBMIT_BODY_BYTES > api.http_api.MAX_BODY_BYTES
    response = api.app.handler(h.event(
        "PUT", "/v1/items/adoom666/alreadypublished/rating",
        json.dumps({"stars": 5, "text": "x" * (9 * 1024)}), h.token(api),
    ))
    assert response["statusCode"] == 413




def test_the_sixth_submission_in_a_day_is_refused_and_stores_nothing(api):
    _users(api).seed(
        {"user_id": h.OTHER_ID},
        {"submissions_day": TODAY, "submissions_today": 5},
    )
    response = h.submit(api)
    assert response["statusCode"] == 429
    assert h.body_of(response)["code"] == "rate_limited"
    assert api.s3.objects == {}


def test_yesterdays_submission_counter_is_reset_rather_than_refused(api):
    users = _users(api)
    users.seed(
        {"user_id": h.OTHER_ID},
        {"submissions_day": YESTERDAY, "submissions_today": 5},
    )
    assert h.submit(api)["statusCode"] == 201
    stored = users.stored({"user_id": h.OTHER_ID})
    assert stored["submissions_day"] == TODAY
    assert stored["submissions_today"] == 1


def test_the_vote_and_submission_counters_are_separate(api):
    _users(api).seed(
        {"user_id": h.OTHER_ID}, {"votes_day": TODAY, "votes_today": 50}
    )
    assert h.submit(api)["statusCode"] == 201




def test_an_own_published_item_is_accepted_as_a_new_version(api):
    response = h.submit(api, h.submission(name="alreadypublished", version="2.0.0"))
    assert response["statusCode"] == 201, h.body_of(response)
    assert h.body_of(response)["new_version"] is True
    row = api.tables[api.submissions.SUBMISSIONS_TABLE].stored(
        {"submission_id": h.body_of(response)["submission_id"]}
    )
    assert row["status"] == "pending" and row["new_version"] is True


def test_the_same_version_of_an_item_is_not_submitted_twice(api):
    assert h.submit(api, h.submission(name="work", version="1.0.0"))["statusCode"] == 201
    for row in api.tables[api.submissions.SUBMISSIONS_TABLE].items.values():
        row["status"] = "approved"
    response = h.submit(api, h.submission(name="work", version="1.0.0"))
    assert response["statusCode"] == 409
    assert h.body_of(response)["code"] == "version_exists"
    assert h.submit(api, h.submission(name="work", version="1.0.1"))["statusCode"] == 201


def test_an_unreadable_index_accepts_rather_than_refusing(api, monkeypatch):
    def unreachable(url, limit):
        raise OSError("no index")

    api.item_index.reset()
    monkeypatch.setattr(api.item_index, "_read_url", unreachable)
    try:
        response = h.submit(api, h.submission(name="alreadypublished"))
        assert response["statusCode"] == 201
        assert h.body_of(response)["new_version"] is False
    finally:
        fake.seed_index(api, {h.PUBLISHED_ITEM})


def test_a_queued_name_is_refused(api):
    assert h.submit(api)["statusCode"] == 201
    before = dict(api.s3.objects)
    api.log.clear()
    response = h.submit(api, h.submission(name="work"),
                        h.token(api, "999", "someoneelse"))
    assert response["statusCode"] == 409
    assert h.body_of(response)["code"] == "name_pending"
    assert api.s3.objects == before
