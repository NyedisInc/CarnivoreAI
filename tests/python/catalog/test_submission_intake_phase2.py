
from __future__ import annotations

import json
import time

import pytest

from src.core.skills.digest import DigestEntry, digest_entries
from tests.helpers import hosted_catalog_fake as fake
from tests.helpers import submissions_harness as h


@pytest.fixture(scope="module")
def api():
    with fake.lambda_modules(h.JWT_TEST_SECRET) as namespace:
        fake.seed_index(namespace, {h.PUBLISHED_ITEM})
        yield namespace


@pytest.fixture(autouse=True)
def clean(api, monkeypatch):
    h.reset(api)
    monkeypatch.setattr(api.http_api, "ADMIN_GITHUB_USER_ID", h.ADMIN_ID)


def _set(api, submission_id: str, **fields) -> None:
    api.tables[api.submissions.SUBMISSIONS_TABLE].stored(
        {"submission_id": submission_id}).update(fields)


def _submit(api, version: str = "1.0.0", user: str = "", login: str = "harbor666") -> str:
    bearer = h.token(api, user, login) if user else None
    response = h.submit(api, h.submission(name="work", version=version), bearer)
    assert response["statusCode"] == 201, h.body_of(response)
    return h.body_of(response)["submission_id"]


def _approved(api) -> str:
    sid = _submit(api)
    _set(api, sid, status="approved")
    return sid


def _post(api, sid: str, action: str, owner: str = "worker-1", bearer=None):
    return api.app.handler(h.event(
        "POST", f"/v1/submissions/{sid}/{action}", json.dumps({"owner": owner}),
        bearer or h.token(api, h.ADMIN_ID)))


def _status(api, sid: str) -> str:
    return api.tables[api.submissions.SUBMISSIONS_TABLE].stored({"submission_id": sid})["status"]




def test_a_second_consumer_is_refused_while_a_claim_is_held(api):
    sid = _approved(api)
    first = _post(api, sid, "claim", "worker-1")
    assert first["statusCode"] == 200, h.body_of(first)
    assert _status(api, sid) == "publishing"
    second = _post(api, sid, "claim", "alex-mac")
    assert second["statusCode"] == 409
    assert h.body_of(second)["code"] == "claim_held"
    row = api.tables[api.submissions.SUBMISSIONS_TABLE].stored({"submission_id": sid})
    assert row["claim_owner"] == "worker-1"


def test_a_stale_claim_can_be_taken_over(api):
    sid = _approved(api)
    assert _post(api, sid, "claim", "worker-1")["statusCode"] == 200
    _set(api, sid, claimed_at_epoch=int(time.time()) - 2 * 60 * 60 - 5)
    taken = _post(api, sid, "claim", "alex-mac")
    assert taken["statusCode"] == 200, h.body_of(taken)
    assert api.tables[api.submissions.SUBMISSIONS_TABLE].stored(
        {"submission_id": sid})["claim_owner"] == "alex-mac"


def test_release_returns_the_row_to_approved_only_for_its_owner(api):
    sid = _approved(api)
    _post(api, sid, "claim", "worker-1")
    assert _post(api, sid, "release", "alex-mac")["statusCode"] == 409
    assert _status(api, sid) == "publishing"
    assert _post(api, sid, "release", "worker-1")["statusCode"] == 200
    assert _status(api, sid) == "approved"
    assert _post(api, sid, "claim", "alex-mac")["statusCode"] == 200


def test_only_an_approved_row_can_be_claimed_and_only_by_an_admin(api):
    sid = _submit(api)
    refused = _post(api, sid, "claim")
    assert refused["statusCode"] == 409 and h.body_of(refused)["code"] == "not_approved"
    _set(api, sid, status="approved")
    assert _post(api, sid, "claim", bearer=h.token(api, h.OTHER_ID))["statusCode"] == 403
    assert _post(api, sid, "claim", owner="bad owner!")["statusCode"] == 400
    assert _status(api, sid) == "approved"




def test_same_account_resubmit_with_the_same_version_after_gate_failed_is_accepted(api):
    first = _submit(api, "1.0.0")
    refused = h.submit(api, h.submission(name="work", version="1.0.0"))
    assert refused["statusCode"] == 409 and h.body_of(refused)["code"] == "version_exists"
    _set(api, first, status="gate_failed")
    again = h.submit(api, h.submission(name="work", version="1.0.0"))
    assert again["statusCode"] == 201, h.body_of(again)


def test_another_accounts_open_row_gives_name_pending(api):
    first = _submit(api, "1.0.0", user="777", login="someoneelse")
    other = h.submit(api, h.submission(name="work"), h.token(api, "888", "thirdparty"))
    assert other["statusCode"] == 409 and h.body_of(other)["code"] == "name_pending"
    _set(api, first, status="withdrawn")
    assert h.submit(api, h.submission(name="work"), h.token(api, "888", "thirdparty"))["statusCode"] == 201


def test_a_new_upload_supersedes_the_same_accounts_open_row(api):
    old = _submit(api, "1.0.0")
    new = _submit(api, "1.1.0")
    assert _status(api, old) == "superseded"
    assert _status(api, new) == "pending"
    row = api.tables[api.submissions.SUBMISSIONS_TABLE].stored({"submission_id": old})
    assert row["superseded_by"] == new
    assert api.submissions.bytes_state("superseded") == "pending"
    assert f"pending/{old}/files/SKILL.md" in api.s3.objects


def test_folder_digest_is_stored_and_matches_the_shared_digest_code(api):
    sid = _submit(api)
    row = api.tables[api.submissions.SUBMISSIONS_TABLE].stored({"submission_id": sid})
    body = h.skill_md("work").encode()
    import hashlib
    expected = digest_entries([DigestEntry("SKILL.md", "100644", hashlib.sha256(body).hexdigest())])
    assert row["folder_digest"] == expected
