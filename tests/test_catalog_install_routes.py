
from __future__ import annotations

import hashlib
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_cir_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_cir_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.api import catalog_consent
from src.core.catalog.index_cache import FORCE_REFRESH_FLOOR_SECONDS
from src.core.catalog.verify_types import KEY_UNTRUSTED
from src.core.skills.install_types import (
    ALREADY_INSTALLED,
    CHOICE_INSTALL_AS,
    CHOICE_REPLACE,
    CONSENT_REQUIRED,
    DIGEST_MISMATCH,
    NAME_TAKEN,
    PROJECT_PATH_INVALID,
    STALE_REVISION,
)
from src.core.skills.plan_tokens import MAX_OUTSTANDING_TOKENS
from src.core.skills.sweeper import MAX_CONCURRENT_STAGING
from src.core.skills.records import SIDECAR_NAME, read_sidecar
from tests.helpers.catalog_app import catalog_app, ledger_rows
from tests.helpers.catalog_fixture import sign_item_versions
from tests.helpers.catalog_surface import (
    FIXTURE_COMMIT,
    FIXTURE_REPO,
    build_skill,
    fixture_trust_root,
    item_for,
    open_and_list,
    keypairs,
    publish_index,
    serve_archive,
)
from tests.helpers.minisign_keys import SKIP_REASON, minisign_binary

PUBLISHER = "alex"
NAME = "sme"
ITEM_ID = f"{PUBLISHER}/{NAME}"
GLOBAL = {"item_id": ITEM_ID, "scope": "global"}

pytestmark = pytest.mark.skipif(minisign_binary() is None, reason=SKIP_REASON)


@pytest.fixture
def served(tmp_path) -> Path:
    root = tmp_path / "served"
    root.mkdir()
    return root


@pytest.fixture
def keys(tmp_path):
    return keypairs(tmp_path / "keys")


def _publish(
    tmp_path,
    served,
    keys,
    *,
    scripts: int = 0,
    body: bytes = b"---\nname: sme\n---\n# sme\n\nthe sme skill\n",
    extra_items=(),
    corrupt_archive: bool = False,
):
    index_kp, publisher_kp, _stranger = keys
    package = build_skill(
        tmp_path, publisher=PUBLISHER, name=NAME, files={"SKILL.md": body}
    )
    if corrupt_archive:
        other = build_skill(
            tmp_path,
            publisher=PUBLISHER,
            name=NAME,
            files={"SKILL.md": b"---\nname: sme\n---\n# not the same\n"},
            label="swapped",
        )
        serve_archive(served, other.tar_bytes)
    else:
        serve_archive(served, package.tar_bytes)

    publish_index(
        tmp_path,
        served,
        index_keypair=index_kp,
        publisher_keypair=publisher_kp,
        items=[
            item_for(package, publisher=PUBLISHER, name=NAME, scripts=scripts),
            *extra_items,
        ],
        serial=1,
    )
    return fixture_trust_root(index_kp, publisher_kp)


def _refusal(response):
    return response.json()["detail"]




def test_the_preview_returns_the_manifest_text_and_the_file_list(
    tmp_path, served, keys
):
    trust = _publish(tmp_path, served, keys)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        response = app.client.post("/catalog/install/preview", json=GLOBAL)
        left_behind = app.staging_entries()

    assert response.status_code == 200, response.text
    body = response.json()
    assert "the sme skill" in body["body"]
    assert [entry["path"] for entry in body["files"]] == ["SKILL.md"]
    assert body["total_bytes"] > 0
    assert body["publisher"] == PUBLISHER
    assert body["pinned"] is True
    assert body["index_host"] == "127.0.0.1"
    assert len(body["digest_prefix"]) == 12
    assert body["plan_token"]
    assert len(left_behind) == 1


def test_the_preview_publishes_the_whole_digest_and_the_manifest_sha(
    tmp_path, served, keys
):
    manifest = b"---\nname: sme\n---\n# sme\n\nthe sme skill\n"
    trust = _publish(tmp_path, served, keys, body=manifest)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        response = app.client.post("/catalog/install/preview", json=GLOBAL)

    assert response.status_code == 200, response.text
    body = response.json()
    digest = body["digest"]
    assert len(digest) == 64
    assert set(digest) <= set("0123456789abcdef")
    assert digest.startswith(body["digest_prefix"])
    assert body["body_sha"] == hashlib.sha256(manifest).hexdigest()


def test_installing_a_scripts_bearing_version_with_no_consent_fetches_nothing(
    tmp_path, served, keys
):
    trust = _publish(tmp_path, served, keys, scripts=1)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        response = app.client.raw_post("/catalog/install", json=GLOBAL)
        assert app.staging_entries() == []
        archive_requests = [p for p in app.server.seen() if "tar.gz" in p]

    assert response.status_code == 409, response.text
    assert _refusal(response)["code"] == CONSENT_REQUIRED
    assert archive_requests == []


def test_an_item_signed_by_an_unpinned_key_is_refused_as_key_untrusted(
    tmp_path, served, keys
):
    index_kp, publisher_kp, stranger_kp = keys
    theirs = build_skill(
        tmp_path, publisher="stranger", name="other", label="theirs"
    )
    stranger_item = sign_item_versions(
        tmp_path, item_for(theirs, publisher="stranger", name="other"), stranger_kp
    )
    trust = _publish(tmp_path, served, keys, extra_items=(stranger_item,))
    serve_archive(served, theirs.tar_bytes)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        response = app.client.post(
            "/catalog/install/preview",
            json={"item_id": "stranger/other", "scope": "global"},
        )
        assert app.staging_entries() == []

    assert response.status_code == 409, response.text
    assert _refusal(response)["code"] == KEY_UNTRUSTED


def test_a_tarball_that_does_not_hash_to_the_signed_digest_is_refused(
    tmp_path, served, keys
):
    trust = _publish(tmp_path, served, keys, corrupt_archive=True)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        response = app.client.post("/catalog/install/preview", json=GLOBAL)
        left_behind = app.staging_entries()

    assert response.status_code == 409, response.text
    assert _refusal(response)["code"] == DIGEST_MISMATCH
    assert left_behind == []


def test_a_project_scope_with_no_path_is_a_400_not_a_500(tmp_path, served, keys):
    trust = _publish(tmp_path, served, keys)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        response = app.client.post(
            "/catalog/install/preview",
            json={"item_id": ITEM_ID, "scope": "project"},
        )
        assert app.staging_entries() == []

    assert response.status_code == 400, response.text




def test_an_install_lands_a_real_copy_in_both_roots_with_a_sidecar(
    tmp_path, served, keys
):
    trust = _publish(tmp_path, served, keys)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        response = app.client.post("/catalog/install", json=GLOBAL)
        claude = app.roots.claude_skills() / NAME
        codex = app.roots.codex_skills() / NAME
        rows = ledger_rows(app)
        left_behind = app.staging_entries()
        listed = open_and_list(app).json()

    assert response.status_code == 200, response.text
    assert response.json()["item_id"] == ITEM_ID
    assert response.json()["scope"] == "global"

    for landed in (claude, codex):
        assert landed.is_dir()
        assert landed.is_symlink() is False
        manifest = landed / "SKILL.md"
        assert manifest.is_symlink() is False
        assert b"the sme skill" in manifest.read_bytes()
        assert (landed / SIDECAR_NAME).is_file()
        record = read_sidecar(landed)
        assert record is not None
        assert record.publisher == PUBLISHER

    assert [row.item_id for row in rows] == [ITEM_ID]
    assert left_behind == []
    assert listed["items"][0]["installed"]["install_id"] == rows[0].install_id
    assert listed["items"][0]["installed"]["update_available"] is False


def test_a_preview_then_an_install_reuses_the_staged_copy(tmp_path, served, keys):
    trust = _publish(tmp_path, served, keys)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        preview = app.client.post("/catalog/install/preview", json=GLOBAL).json()
        downloads = [p for p in app.server.seen() if "tar.gz" in p]
        install = app.client.post(
            "/catalog/install", json={**GLOBAL, "plan_token": preview["plan_token"]}
        )
        after = [p for p in app.server.seen() if "tar.gz" in p]
        left_behind = app.staging_entries()

    assert install.status_code == 200, install.text
    assert len(after) == len(downloads), "the token should have saved a download"
    assert left_behind == []


def test_a_second_install_of_the_same_item_is_already_installed(
    tmp_path, served, keys
):
    trust = _publish(tmp_path, served, keys)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        first = app.client.post("/catalog/install", json=GLOBAL)
        second = app.client.post("/catalog/install", json=GLOBAL)
        left_behind = app.staging_entries()

    assert first.status_code == 200, first.text
    assert second.status_code == 409, second.text
    assert _refusal(second)["code"] == ALREADY_INSTALLED
    assert left_behind == []


def test_a_name_collision_offers_two_choices_and_install_as_succeeds(
    tmp_path, served, keys
):
    trust = _publish(tmp_path, served, keys)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        mine = app.roots.claude_skills() / NAME
        mine.mkdir(parents=True)
        (mine / "SKILL.md").write_text("# my own\n")

        refused = app.client.post("/catalog/install", json=GLOBAL)
        assert refused.status_code == 409, refused.text
        body = _refusal(refused)
        assert body["code"] == NAME_TAKEN
        actions = {choice["choice"] for choice in body["choices"]}
        assert actions == {CHOICE_INSTALL_AS, CHOICE_REPLACE}

        installed = app.client.post(
            "/catalog/install", json={**GLOBAL, "choice": CHOICE_INSTALL_AS}
        )
        renamed = app.roots.claude_skills() / f"{NAME}-carnivore"
        left_behind = app.staging_entries()
        kept = (mine / "SKILL.md").read_text()

    assert installed.status_code == 200, installed.text
    assert installed.json()["name"] == f"{NAME}-carnivore"
    assert renamed.is_dir()
    assert renamed.is_symlink() is False
    assert kept == "# my own\n", "install_as must not touch the user's folder"
    assert left_behind == []


def test_the_name_taken_preview_carries_the_sheet_as_well_as_the_choices(
    tmp_path, served, keys
):
    trust = _publish(tmp_path, served, keys)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        mine = app.roots.codex_skills() / NAME
        mine.mkdir(parents=True)
        (mine / "SKILL.md").write_text("# mine\n")

        response = app.client.post("/catalog/install/preview", json=GLOBAL)
        left_behind = app.staging_entries()

    assert response.status_code == 409, response.text
    body = _refusal(response)
    assert body["code"] == NAME_TAKEN
    assert "the sme skill" in body["body"]
    assert body["choices"]
    assert body["plan_token"], "the choice comes back with this token as its proof"
    assert len(left_behind) == 1, "the name_taken preview holds its copy for the choice"


def test_the_installed_listing_carries_every_row_with_its_badge(
    tmp_path, served, keys
):
    trust = _publish(tmp_path, served, keys)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        app.client.post("/catalog/install", json=GLOBAL)
        listing = app.client.get("/catalog/installed")

    assert listing.status_code == 200, listing.text
    items = listing.json()["items"]
    assert [item["item_id"] for item in items] == [ITEM_ID]
    assert items[0]["update_available"] is False
    assert items[0]["publisher_key_id"]


def test_an_unknown_item_is_a_404_and_stages_nothing(tmp_path, served, keys):
    trust = _publish(tmp_path, served, keys)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        response = app.client.post(
            "/catalog/install", json={"item_id": "alex/ghost", "scope": "global"}
        )
        assert app.staging_entries() == []

    assert response.status_code == 404, response.text


def test_an_unreachable_tarball_is_a_502_and_stages_nothing(
    tmp_path, served, keys
):
    trust = _publish(tmp_path, served, keys)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        app.server.status_overrides[
            f"/{FIXTURE_REPO}/tar.gz/{FIXTURE_COMMIT}"
        ] = 500
        response = app.client.post("/catalog/install", json=GLOBAL)
        left_behind = app.staging_entries()

    assert response.status_code == 502, response.text
    assert response.json()["detail"]["code"] == "index_unavailable"
    assert left_behind == []




def test_nine_previews_that_nobody_installs_do_not_wedge_the_next_one(
    tmp_path, served, keys
):
    trust = _publish(tmp_path, served, keys)
    attempts = MAX_CONCURRENT_STAGING + 1

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        answers = [
            app.client.post("/catalog/install/preview", json=GLOBAL)
            for _ in range(attempts)
        ]
        store = app.services.catalog.staged_plans
        held = app.staging_entries()
        outstanding = store.outstanding()
        first_token = answers[0].json().get("plan_token")
        evicted, _swept = store.take(first_token)
        installed = app.client.post("/catalog/install", json=GLOBAL)

    assert [answer.status_code for answer in answers] == [200] * attempts, (
        answers[-1].text
    )
    assert MAX_OUTSTANDING_TOKENS < MAX_CONCURRENT_STAGING
    assert outstanding == MAX_OUTSTANDING_TOKENS
    assert len(held) == MAX_OUTSTANDING_TOKENS
    assert evicted is None, "the oldest token was evicted, not kept"
    assert installed.status_code == 200, installed.text


def test_a_preview_that_fails_after_planning_mints_no_token(
    tmp_path, served, keys, monkeypatch
):
    trust = _publish(tmp_path, served, keys)

    def explode(_path, _kind=None):
        raise RuntimeError("the manifest could not be read")

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        monkeypatch.setattr(catalog_consent, "preview_manifest", explode)
        with pytest.raises(RuntimeError):
            app.client.post("/catalog/install/preview", json=GLOBAL)
        left_behind = app.staging_entries()
        outstanding = app.services.catalog.staged_plans.outstanding()

    assert left_behind == []
    assert outstanding == 0


def test_a_token_whose_version_the_index_replaced_is_refused(
    tmp_path, served, keys
):
    index_kp, publisher_kp, _stranger = keys
    package = build_skill(
        tmp_path,
        publisher=PUBLISHER,
        name=NAME,
        files={"SKILL.md": b"---\nname: sme\n---\n# sme\n"},
    )
    serve_archive(served, package.tar_bytes)
    published = item_for(package, publisher=PUBLISHER, name=NAME)
    publish_index(
        tmp_path,
        served,
        index_keypair=index_kp,
        publisher_keypair=publisher_kp,
        items=[published],
        serial=1,
    )
    trust = fixture_trust_root(index_kp, publisher_kp)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        preview = app.client.post("/catalog/install/preview", json=GLOBAL)
        token = preview.json()["plan_token"]

        publish_index(
            tmp_path,
            served,
            index_keypair=index_kp,
            publisher_keypair=publisher_kp,
            items=[
                item_for(
                    package, publisher=PUBLISHER, name=NAME, version="1.1.0"
                )
            ],
            serial=2,
        )
        app.clock.advance(FORCE_REFRESH_FLOOR_SECONDS + 1.0)
        refreshed = app.client.post("/catalog/index/refresh")
        assert refreshed.json()["serial"] == 2, refreshed.text

        response = app.client.post(
            "/catalog/install", json={**GLOBAL, "plan_token": token}
        )
        left_behind = app.staging_entries()
        rows = ledger_rows(app)

    assert preview.json()["version"] == "1.0.0"
    assert response.status_code == 409, response.text
    assert _refusal(response)["code"] == STALE_REVISION
    assert rows == [], "a refused token must not install anything"
    assert left_behind == []




def _project_attempt(app, path) -> Any:
    return app.client.post(
        "/catalog/install/preview",
        json={"item_id": ITEM_ID, "scope": "project", "project_path": str(path)},
    )


def test_a_project_path_that_composes_a_global_root_is_refused(
    tmp_path, served, keys
):
    home = tmp_path / "roots" / "home"
    trust = _publish(tmp_path, served, keys)
    (home / ".agents" / "skills").mkdir(parents=True)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        response = app.client.post(
            "/catalog/install",
            json={
                "item_id": ITEM_ID,
                "scope": "project",
                "project_path": str(home),
            },
        )
        left_behind = app.staging_entries()
        landed = sorted(entry.name for entry in app.roots.claude_skills().iterdir())
        rows = ledger_rows(app)

    assert response.status_code == 409, response.text
    assert _refusal(response)["code"] == PROJECT_PATH_INVALID
    assert landed == [], "nothing may reach a global root through a project install"
    assert rows == []
    assert left_behind == []


def test_the_state_directory_is_not_a_project(tmp_path, served, keys):
    trust = _publish(tmp_path, served, keys)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        response = _project_attempt(app, app.state)
        left_behind = app.staging_entries()

    assert response.status_code == 409, response.text
    assert _refusal(response)["code"] == PROJECT_PATH_INVALID
    assert left_behind == []


def test_a_harness_dot_directory_under_home_is_not_a_project(
    tmp_path, served, keys
):
    trust = _publish(tmp_path, served, keys)
    dot_claude = tmp_path / "roots" / "home" / ".claude"

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        response = _project_attempt(app, dot_claude)
        left_behind = app.staging_entries()

    assert response.status_code == 409, response.text
    assert _refusal(response)["code"] == PROJECT_PATH_INVALID
    assert left_behind == []


def test_a_project_path_that_does_not_exist_is_refused(tmp_path, served, keys):
    trust = _publish(tmp_path, served, keys)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        response = _project_attempt(app, tmp_path / "no-such-directory")
        left_behind = app.staging_entries()

    assert response.status_code == 409, response.text
    assert _refusal(response)["code"] == PROJECT_PATH_INVALID
    assert left_behind == []


def test_a_real_directory_the_launcher_does_not_know_is_refused(
    tmp_path, served, keys
):
    trust = _publish(tmp_path, served, keys)
    stranger = tmp_path / "somebody-elses-checkout"
    stranger.mkdir()

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        response = _project_attempt(app, stranger)
        left_behind = app.staging_entries()

    assert response.status_code == 409, response.text
    assert _refusal(response)["code"] == PROJECT_PATH_INVALID
    assert not (stranger / ".claude").exists()
    assert left_behind == []


def test_a_known_project_is_accepted_and_installs_into_it(
    tmp_path, served, keys
):
    trust = _publish(tmp_path, served, keys)
    project = tmp_path / "checkout"
    (project / ".claude" / "skills").mkdir(parents=True)
    (project / ".agents" / "skills").mkdir(parents=True)

    with catalog_app(
        tmp_path, served, trust_root=trust, projects=[project]
    ) as app:
        preview = _project_attempt(app, project)
        installed = app.client.post(
            "/catalog/install",
            json={
                "item_id": ITEM_ID,
                "scope": "project",
                "project_path": str(project),
                "plan_token": preview.json()["plan_token"],
            },
        )
        left_behind = app.staging_entries()

    assert preview.status_code == 200, preview.text
    assert installed.status_code == 200, installed.text
    landed = project / ".claude" / "skills" / NAME
    assert landed.is_dir() and not landed.is_symlink()
    assert (landed / "SKILL.md").read_bytes().startswith(b"---")
    assert left_behind == []


def test_a_plan_token_is_consumed_by_the_install_that_claims_it(
    tmp_path, served, keys
):
    trust = _publish(tmp_path, served, keys)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        token = app.client.post(
            "/catalog/install/preview", json=GLOBAL
        ).json()["plan_token"]

        first = app.client.post(
            "/catalog/install", json={**GLOBAL, "plan_token": token}
        )
        outstanding = app.services.catalog.staged_plans.outstanding()

        before = len(app.server.seen())
        second = app.client.post(
            "/catalog/install", json={**GLOBAL, "plan_token": token}
        )
        refetched = len(app.server.seen()) > before
        left_behind = app.staging_entries()
        rows = ledger_rows(app)

    assert first.status_code == 200, first.text
    assert outstanding == 0, "claiming the token removed it"
    assert second.status_code == 409, second.text
    assert _refusal(second)["code"] == ALREADY_INSTALLED
    assert refetched, "a spent token buys nothing, so the bytes were fetched again"
    assert len(rows) == 1, "one install, one ledger row"
    assert left_behind == []
