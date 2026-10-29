
from __future__ import annotations

import pytest

from src.core.skills.contents_view import default_cache
from tests.helpers.catalog_app import catalog_app
from tests.test_catalog_installed_routes import (  # noqa: F401
    BODY_V2,
    ITEM_ID,
    NAME,
    install,
    keys,
    pytestmark,
    publish_first,
    publish_second,
    refusal,
    served,
)


@pytest.fixture(autouse=True)
def cold_cache():
    default_cache.clear()
    yield
    default_cache.clear()


def test_contents_lists_files_and_returns_the_signed_skill_md(tmp_path, served, keys):
    trust = publish_first(tmp_path, served, keys)
    with catalog_app(tmp_path, served, trust_root=trust) as app:
        first = app.client.get(f"/catalog/contents/{ITEM_ID}")
        cached = app.client.get(f"/catalog/contents/{ITEM_ID}")
    assert first.status_code == 200, first.text
    body = first.json()
    assert "the sme skill" in body["body"]
    assert [f["path"] for f in body["files"]] == ["SKILL.md"]
    assert body["files"][0]["kind"] == "text"
    assert cached.json() == body


def test_contents_refuses_a_staged_digest_that_does_not_match_the_index(tmp_path, served, keys):
    trust = publish_first(tmp_path, served, keys)
    with catalog_app(tmp_path, served, trust_root=trust) as app:
        publish_second(tmp_path, served, keys, body=BODY_V2, corrupt_archive=True)
        app.clock.advance(301.0)
        response = app.client.get(f"/catalog/contents/{ITEM_ID}")
        left_behind = app.staging_entries()
    assert response.status_code == 409, response.text
    sheet = refusal(response)
    assert sheet["code"] == "digest_mismatch"
    assert "body" not in sheet and "files" not in sheet
    assert "reads your mail" not in response.text
    assert left_behind == []
    assert default_cache.get("0" * 64) is None


def test_the_update_sheet_diffs_the_installed_version_against_the_new_one(tmp_path, served, keys):
    trust = publish_first(tmp_path, served, keys)
    with catalog_app(tmp_path, served, trust_root=trust) as app:
        row = install(app)
        publish_second(tmp_path, served, keys, body=BODY_V2)
        app.clock.advance(301.0)
        refused = app.client.post(
            f"/catalog/installed/{row['install_id']}/update", json={"expected_revision": 1}
        )
    assert refused.status_code == 409, refused.text
    diff = refusal(refused)["diff"]
    assert (diff["from_version"], diff["to_version"]) == ("1.0.0", "2.0.0")
    by_path = {c["path"]: c for c in diff["changes"]}
    assert by_path["SKILL.md"]["status"] == "changed"
    assert "-the sme skill" in by_path["SKILL.md"]["diff"]
    assert "+now it also reads your mail" in by_path["SKILL.md"]["diff"]
    assert by_path["reference.md"]["status"] == "added"
