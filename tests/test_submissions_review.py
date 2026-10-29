
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from tests.helpers import hosted_catalog_fake as fake
from tests.helpers import submissions_harness as h

ABSENT_ID = "a" * 32

ADMIN_ROUTES = [
    ("GET", "/v1/submissions", None),
    ("GET", f"/v1/submissions/{ABSENT_ID}", None),
    ("POST", f"/v1/submissions/{ABSENT_ID}/approve", None),
    ("POST", f"/v1/submissions/{ABSENT_ID}/reject", '{"reason":"no"}'),
]


@pytest.fixture(scope="module")
def api():
    with fake.lambda_modules(h.JWT_TEST_SECRET) as namespace:
        fake.seed_index(namespace, {h.PUBLISHED_ITEM})
        yield namespace


@pytest.fixture(autouse=True)
def clean(api, monkeypatch):
    h.reset(api)
    monkeypatch.setattr(api.http_api, "ADMIN_GITHUB_USER_ID", h.ADMIN_ID)


def _stored(api, submission_id: str) -> dict:
    return api.tables[api.submissions.SUBMISSIONS_TABLE].stored(
        {"submission_id": submission_id}
    )


def _one_pending(api) -> str:
    response = h.submit(api)
    assert response["statusCode"] == 201, h.body_of(response)
    return h.body_of(response)["submission_id"]




@pytest.mark.parametrize("method,path,body", ADMIN_ROUTES)
def test_a_non_admin_is_refused_on_every_review_route(api, method, path, body):
    response = api.app.handler(
        h.event(method, path, body, h.token(api, h.OTHER_ID))
    )
    assert response["statusCode"] == 403, h.body_of(response)
    assert h.body_of(response)["code"] == "forbidden"
    assert h.storage_calls(api) == []


@pytest.mark.parametrize("method,path,body", ADMIN_ROUTES)
def test_an_unconfigured_admin_id_refuses_rather_than_admits(
    api, monkeypatch, method, path, body
):
    monkeypatch.setattr(api.http_api, "ADMIN_GITHUB_USER_ID", "")
    response = api.app.handler(
        h.event(method, path, body, h.token(api, h.ADMIN_ID))
    )
    assert response["statusCode"] == 503, h.body_of(response)
    assert h.body_of(response)["code"] == "admin_not_configured"
    assert h.storage_calls(api) == []


@pytest.mark.parametrize("method,path,body", ADMIN_ROUTES)
def test_the_admin_reaches_every_review_route(api, method, path, body):
    response = api.app.handler(
        h.event(method, path, body, h.token(api, h.ADMIN_ID))
    )
    assert response["statusCode"] not in (401, 403, 503), h.body_of(response)


@pytest.mark.parametrize("method,path,body", ADMIN_ROUTES)
def test_an_unauthenticated_caller_never_reaches_the_admin_check(
    api, method, path, body
):
    response = api.app.handler(h.event(method, path, body))
    assert response["statusCode"] == 401
    assert h.storage_calls(api) == []


def test_the_admin_is_decided_by_the_numeric_id_and_not_the_login(api):
    impostor = h.token(api, "999999", "example-owner")
    response = api.app.handler(h.event("GET", "/v1/submissions", None, impostor))
    assert response["statusCode"] == 403




def test_the_queue_lists_pending_submissions(api):
    _one_pending(api)
    response = api.app.handler(
        h.event("GET", "/v1/submissions", None, h.token(api, h.ADMIN_ID))
    )
    assert response["statusCode"] == 200
    body = h.body_of(response)
    assert body["status"] == "pending"
    assert body["count"] == 1
    assert body["submissions"][0]["name"] == "work"


def test_an_unknown_queue_status_is_refused(api):
    response = api.app.handler(h.event(
        "GET", "/v1/submissions", None, h.token(api, h.ADMIN_ID),
        {"status": "everything"},
    ))
    assert response["statusCode"] == 400


def test_the_detail_route_returns_the_file_list_and_the_manifest(api):
    response = h.submit(api, h.submission(files=[
        {"path": "SKILL.md", "content_base64": h.b64(h.skill_md())},
        {"path": "reference/notes.md", "content_base64": h.b64("some notes")},
    ]))
    submission_id = h.body_of(response)["submission_id"]
    detail = api.app.handler(h.event(
        "GET", f"/v1/submissions/{submission_id}", None, h.token(api, h.ADMIN_ID)
    ))
    assert detail["statusCode"] == 200
    body = h.body_of(detail)
    assert sorted(entry["path"] for entry in body["files"]) == [
        "SKILL.md", "reference/notes.md",
    ]
    sizes = {entry["path"]: entry["size"] for entry in body["files"]}
    assert sizes["reference/notes.md"] == len("some notes")
    assert "description: does a thing" in body["skill_md"]
    assert "content_base64" not in json.dumps(body)


def test_an_unknown_submission_id_is_a_404(api):
    response = api.app.handler(h.event(
        "GET", f"/v1/submissions/{ABSENT_ID}", None, h.token(api, h.ADMIN_ID)
    ))
    assert response["statusCode"] == 404
    assert h.body_of(response)["code"] == "not_found"


def test_a_malformed_submission_id_never_becomes_a_key(api):
    response = api.app.handler(h.event(
        "GET", "/v1/submissions/..%2Fetc", None, h.token(api, h.ADMIN_ID)
    ))
    assert response["statusCode"] == 404
    assert h.storage_calls(api) == []




def test_approving_moves_the_objects_and_sets_the_status(api):
    submission_id = _one_pending(api)
    response = api.app.handler(h.event(
        "POST", f"/v1/submissions/{submission_id}/approve", None,
        h.token(api, h.ADMIN_ID),
    ))
    assert response["statusCode"] == 200, h.body_of(response)
    assert h.body_of(response)["objects_moved"] == 2
    assert f"approved/{submission_id}/files/SKILL.md" in api.s3.objects
    assert not any(key.startswith("pending/") for key in api.s3.objects)
    row = _stored(api, submission_id)
    assert row["status"] == "approved"
    assert row["decided_by"] == h.ADMIN_ID
    assert row["decided_at"]


def test_rejecting_moves_the_objects_and_records_the_reason(api):
    submission_id = _one_pending(api)
    response = api.app.handler(h.event(
        "POST", f"/v1/submissions/{submission_id}/reject",
        '{"reason":"the description is wrong"}', h.token(api, h.ADMIN_ID),
    ))
    assert response["statusCode"] == 200, h.body_of(response)
    assert f"rejected/{submission_id}/files/SKILL.md" in api.s3.objects
    assert not any(key.startswith("pending/") for key in api.s3.objects)
    row = _stored(api, submission_id)
    assert row["status"] == "rejected"
    assert row["reason"] == "the description is wrong"


def test_a_rejection_needs_a_reason(api):
    submission_id = _one_pending(api)
    response = api.app.handler(h.event(
        "POST", f"/v1/submissions/{submission_id}/reject", '{"reason":"  "}',
        h.token(api, h.ADMIN_ID),
    ))
    assert response["statusCode"] == 400


def test_a_second_decision_is_refused(api):
    submission_id = _one_pending(api)
    approve = h.event(
        "POST", f"/v1/submissions/{submission_id}/approve", None,
        h.token(api, h.ADMIN_ID),
    )
    assert api.app.handler(approve)["statusCode"] == 200
    second = api.app.handler(approve)
    assert second["statusCode"] == 409
    assert h.body_of(second)["code"] == "not_pending"


def test_a_decided_submission_leaves_the_pending_queue(api):
    submission_id = _one_pending(api)
    api.app.handler(h.event(
        "POST", f"/v1/submissions/{submission_id}/approve", None,
        h.token(api, h.ADMIN_ID),
    ))
    assert api.submissions.pending_names() == set()




def test_the_grammars_match_the_products_own(api):
    repo_root = Path(__file__).resolve().parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from src.models.catalog import PUBLISHER_RE, SKILL_NAME_RE, VERSION_RE
    from src.models.catalog_names import RESERVED_SKILL_NAMES

    assert api.validate_upload.SKILL_NAME_RE.pattern == SKILL_NAME_RE.pattern
    assert api.validate_upload.PUBLISHER_RE.pattern == PUBLISHER_RE.pattern
    assert api.validate_upload.VERSION_RE.pattern == VERSION_RE.pattern
    assert api.validate_upload.RESERVED_SKILL_NAMES == RESERVED_SKILL_NAMES
