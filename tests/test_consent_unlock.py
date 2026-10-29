
from __future__ import annotations

import os
import stat
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_cu_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_cu_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.api.catalog_consent import consent_carried, install_consent_satisfied
from src.core.skills import stage as stage_module
from src.core.skills.digest import digest_directory
from src.core.skills.install_types import CONSENT_REQUIRED
from src.core.skills.ledger_types import InstalledItem
from src.core.skills.records import read_sidecar
from src.core.skills.stage import FILE_MODE, stage_archive
from src.core.skills.validate import SCRIPTS_NOT_SUPPORTED, ArchiveRefused
from src.models.catalog_api import InstallConsent, InstalledUpdateRequest
from tests.helpers.catalog_app import catalog_app, ledger_rows
from tests.helpers.catalog_surface import (
    build_skill,
    fixture_trust_root,
    item_for,
    keypairs,
    publish_index,
    serve_archive,
)
from tests.helpers.minisign_keys import SKIP_REASON, minisign_binary

PUBLISHER = "alex"
NAME = "runner"
ITEM_ID = f"{PUBLISHER}/{NAME}"
GLOBAL = {"item_id": ITEM_ID, "scope": "global"}

BODY = b"---\nname: runner\n---\n# runner\n\nit runs things\n"

FILES = {
    "SKILL.md": BODY,
    "reference.md": b"# notes\n",
    "scripts/run.sh": b"#!/bin/sh\necho hello\n",
    "scripts/README.md": b"# what these do\n",
}
EXEC_PATHS = ("scripts/run.sh",)

pytestmark = pytest.mark.skipif(minisign_binary() is None, reason=SKIP_REASON)


@pytest.fixture
def served(tmp_path) -> Path:
    root = tmp_path / "served"
    root.mkdir()
    return root


@pytest.fixture
def keys(tmp_path):
    return keypairs(tmp_path / "keys")


def publish(tmp_path, served, keys, *, scripts: int = 2):
    index_kp, publisher_kp, _stranger = keys
    package = build_skill(
        tmp_path,
        publisher=PUBLISHER,
        name=NAME,
        files=FILES,
        exec_paths=EXEC_PATHS,
    )
    serve_archive(served, package.tar_bytes)
    publish_index(
        tmp_path,
        served,
        index_keypair=index_kp,
        publisher_keypair=publisher_kp,
        items=[
            item_for(package, publisher=PUBLISHER, name=NAME, scripts=scripts)
        ],
        serial=1,
    )
    return fixture_trust_root(index_kp, publisher_kp), package


def refusal(response) -> dict:
    return response.json()["detail"]


def mode_of(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def archive_of(tmp_path) -> Path:
    package = build_skill(
        tmp_path,
        publisher=PUBLISHER,
        name=NAME,
        files=FILES,
        exec_paths=EXEC_PATHS,
        label="direct",
    )
    path = tmp_path / "direct.tar.gz"
    path.write_bytes(package.tar_bytes)
    return path




def test_the_preview_lists_the_script_files_and_asks_for_consent(
    tmp_path, served, keys
):
    trust, _package = publish(tmp_path, served, keys)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        response = app.client.post("/catalog/install/preview", json=GLOBAL)
        assert app.staging_entries() != []

    assert response.status_code == 200, response.text
    sheet = response.json()
    assert sheet["requires_consent"] is True
    assert sorted(sheet["script_files"]) == [
        "scripts/README.md",
        "scripts/run.sh",
    ]
    listed = sorted(entry["path"] for entry in sheet["files"])
    assert listed == [
        "SKILL.md",
        "reference.md",
        "scripts/README.md",
        "scripts/run.sh",
    ]
    assert sheet["plan_token"]


def test_a_preview_of_a_skill_without_scripts_does_not_ask_for_consent(
    tmp_path, served, keys
):
    index_kp, publisher_kp, _stranger = keys
    package = build_skill(
        tmp_path, publisher=PUBLISHER, name=NAME, files={"SKILL.md": BODY}
    )
    serve_archive(served, package.tar_bytes)
    publish_index(
        tmp_path,
        served,
        index_keypair=index_kp,
        publisher_keypair=publisher_kp,
        items=[item_for(package, publisher=PUBLISHER, name=NAME)],
        serial=1,
    )
    trust = fixture_trust_root(index_kp, publisher_kp)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        response = app.client.post("/catalog/install/preview", json=GLOBAL)

    assert response.status_code == 200, response.text
    assert response.json()["requires_consent"] is False
    assert response.json()["script_files"] == []




def test_installing_with_no_consent_is_refused_as_consent_required(
    tmp_path, served, keys
):
    trust, _package = publish(tmp_path, served, keys)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        response = app.client.post("/catalog/install", json=GLOBAL)
        assert ledger_rows(app) == []
        assert app.roots.claude_skills().joinpath(NAME).exists() is False

    assert response.status_code == 409, response.text
    assert refusal(response)["code"] == CONSENT_REQUIRED


def test_a_consent_that_does_not_accept_scripts_is_refused(
    tmp_path, served, keys
):
    trust, package = publish(tmp_path, served, keys)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        body = dict(GLOBAL)
        body["consent"] = {
            "digest": package.digest,
            "body_sha": _sha_of(BODY),
            "scripts": False,
        }
        response = app.client.post("/catalog/install", json=body)
        assert ledger_rows(app) == []

    assert response.status_code == 409, response.text
    assert refusal(response)["code"] == CONSENT_REQUIRED


def test_a_consent_naming_another_manifest_is_refused(tmp_path, served, keys):
    trust, package = publish(tmp_path, served, keys)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        body = dict(GLOBAL)
        body["consent"] = {
            "digest": package.digest,
            "body_sha": _sha_of(b"# something else entirely\n"),
            "scripts": True,
        }
        response = app.client.post("/catalog/install", json=body)
        assert ledger_rows(app) == []
        assert app.staging_entries() == []

    assert response.status_code == 409, response.text
    assert refusal(response)["code"] == CONSENT_REQUIRED
    assert refusal(response)["body"] == BODY.decode()
    assert refusal(response)["body_sha"] == _sha_of(BODY)


def test_a_consent_naming_another_folder_digest_is_refused(
    tmp_path, served, keys
):
    trust, _package = publish(tmp_path, served, keys)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        body = dict(GLOBAL)
        body["consent"] = {
            "digest": "0" * 64,
            "body_sha": _sha_of(BODY),
            "scripts": True,
        }
        response = app.client.post("/catalog/install", json=body)
        assert ledger_rows(app) == []

    assert response.status_code == 409, response.text
    assert refusal(response)["code"] == CONSENT_REQUIRED


def test_a_consented_install_lands_with_the_exec_bit_on_the_script_alone(
    tmp_path, served, keys
):
    trust, package = publish(tmp_path, served, keys)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        body = dict(GLOBAL)
        body["consent"] = {
            "digest": package.digest,
            "body_sha": _sha_of(BODY),
            "scripts": True,
        }
        response = app.client.post("/catalog/install", json=body)
        assert response.status_code == 200, response.text

        claude = app.roots.claude_skills() / NAME
        codex = app.roots.codex_skills() / NAME
        for landed in (claude, codex):
            assert mode_of(landed / "scripts" / "run.sh") == 0o755
            assert mode_of(landed / "SKILL.md") == 0o644
            assert mode_of(landed / "reference.md") == 0o644
            assert mode_of(landed / "scripts" / "README.md") == 0o644

        sidecar = claude / ".carnivore-skill.json"
        assert sidecar.is_file()
        sidecar.unlink()
        landed_digest, _entries = digest_directory(claude)
        assert landed_digest == package.digest

        rows = ledger_rows(app)
        assert len(rows) == 1
        assert rows[0].consented_digest == package.digest
        assert rows[0].consented_body_sha == _sha_of(BODY)

        record = read_sidecar(codex)
        assert record is not None
        assert record.digest == package.digest


def test_the_consent_the_browser_builds_from_the_sheet_installs(
    tmp_path, served, keys
):
    trust, package = publish(tmp_path, served, keys)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        sheet = app.client.post("/catalog/install/preview", json=GLOBAL)
        assert sheet.status_code == 200, sheet.text
        shown = sheet.json()
        assert shown["requires_consent"] is True

        body = dict(GLOBAL)
        body["consent"] = {
            "digest": shown["digest"],
            "body_sha": shown["body_sha"],
            "scripts": True,
        }
        response = app.client.post("/catalog/install", json=body)
        assert response.status_code == 200, response.text

        landed = app.roots.claude_skills() / NAME / "scripts" / "run.sh"
        assert landed.is_file()
        assert mode_of(landed) == 0o755
        assert len(app.staging_entries()) == 1
        stored = ledger_rows(app)[0]

    assert shown["digest"] == package.digest
    assert stored.consented_digest == package.digest


def test_the_plan_token_from_the_preview_installs_without_a_second_fetch(
    tmp_path, served, keys
):
    trust, package = publish(tmp_path, served, keys)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        sheet = app.client.post("/catalog/install/preview", json=GLOBAL).json()
        fetches_after_preview = len(
            [p for p in app.server.seen() if "tar.gz" in p]
        )

        body = dict(GLOBAL)
        body["plan_token"] = sheet["plan_token"]
        body["consent"] = {
            "digest": sheet["digest_prefix"] and package.digest,
            "body_sha": _sha_of(BODY),
            "scripts": True,
        }
        response = app.client.post("/catalog/install", json=body)
        fetches_after_install = len(
            [p for p in app.server.seen() if "tar.gz" in p]
        )
        assert app.staging_entries() == []

    assert response.status_code == 200, response.text
    assert fetches_after_install == fetches_after_preview


def test_a_staged_copy_with_scripts_outranks_an_index_that_declares_none(
    tmp_path, served, keys
):
    trust, package = publish(tmp_path, served, keys)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        sheet = app.client.post("/catalog/install/preview", json=GLOBAL).json()
        assert sheet["requires_consent"] is True

        _republish_declaring_no_scripts(tmp_path, served, keys, package)
        app.clock.advance(301)
        assert app.client.post("/catalog/index/refresh").status_code == 200

        body = dict(GLOBAL)
        body["plan_token"] = sheet["plan_token"]
        response = app.client.post("/catalog/install", json=body)

        assert ledger_rows(app) == []
        assert not (app.roots.claude_skills() / NAME).exists()

    assert response.status_code == 409, response.text
    assert refusal(response)["code"] == SCRIPTS_NOT_SUPPORTED


def _republish_declaring_no_scripts(tmp_path, served, keys, package) -> None:
    index_kp, publisher_kp, _stranger = keys
    publish_index(
        tmp_path,
        served,
        index_keypair=index_kp,
        publisher_keypair=publisher_kp,
        items=[
            item_for(package, publisher=PUBLISHER, name=NAME, scripts=0)
        ],
        serial=2,
    )




SECOND_FILES = {
    "SKILL.md": BODY,
    "reference.md": b"# notes\n",
    "scripts/run.sh": b"#!/bin/sh\necho it is a different program now\n",
    "scripts/README.md": b"# what these do\n",
}
SECOND_COMMIT = "b" * 40


def publish_second(tmp_path, served, keys):
    index_kp, publisher_kp, _stranger = keys
    package = build_skill(
        tmp_path,
        publisher=PUBLISHER,
        name=NAME,
        files=SECOND_FILES,
        exec_paths=EXEC_PATHS,
        label="v2",
        commit=SECOND_COMMIT,
    )
    serve_archive(served, package.tar_bytes, commit=SECOND_COMMIT)
    publish_index(
        tmp_path,
        served,
        index_keypair=index_kp,
        publisher_keypair=publisher_kp,
        items=[
            item_for(
                package,
                publisher=PUBLISHER,
                name=NAME,
                scripts=2,
                version="2.0.0",
                commit=SECOND_COMMIT,
            )
        ],
        serial=2,
    )
    return package


def consented_install(app, package):
    body = dict(GLOBAL)
    body["consent"] = {
        "digest": package.digest,
        "body_sha": _sha_of(BODY),
        "scripts": True,
    }
    response = app.client.post("/catalog/install", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def offer_second(app):
    app.clock.advance(301)
    response = app.client.post("/catalog/index/refresh")
    assert response.status_code == 200, response.text


def update_with(app, row, consent):
    body = {"expected_revision": row["revision"]}
    if consent is not None:
        body["consent"] = consent
    return app.client.post(
        f"/catalog/installed/{row['install_id']}/update", json=body
    )


@pytest.mark.parametrize(
    "named, why",
    [
        ("old", "the digest of the folder they actually read"),
        ("fake", "a digest no folder in this catalog ever hashed to"),
    ],
)
def test_an_update_consenting_to_another_folder_is_refused(
    tmp_path, served, keys, named, why
):
    trust, first = publish(tmp_path, served, keys)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        row = consented_install(app, first)
        live = app.roots.claude_skills() / NAME / "scripts" / "run.sh"
        assert live.read_bytes() == FILES["scripts/run.sh"]

        second = publish_second(tmp_path, served, keys)
        assert second.digest != first.digest
        offer_second(app)

        response = update_with(
            app,
            row,
            {
                "digest": first.digest if named == "old" else "0" * 64,
                "body_sha": _sha_of(BODY),
                "scripts": True,
            },
        )

        assert live.read_bytes() == FILES["scripts/run.sh"], why
        assert mode_of(live) == 0o755
        assert ledger_rows(app)[0].version == "1.0.0"
        assert app.staging_entries() == []

    assert response.status_code == 409, response.text
    assert refusal(response)["code"] == CONSENT_REQUIRED


def test_an_update_consenting_to_the_new_folder_lands_the_new_script(
    tmp_path, served, keys
):
    trust, first = publish(tmp_path, served, keys)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        row = consented_install(app, first)
        second = publish_second(tmp_path, served, keys)
        offer_second(app)

        response = update_with(
            app,
            row,
            {
                "digest": second.digest,
                "body_sha": _sha_of(BODY),
                "scripts": True,
            },
        )
        assert response.status_code == 200, response.text

        for root in (app.roots.claude_skills(), app.roots.codex_skills()):
            landed = root / NAME / "scripts" / "run.sh"
            assert landed.read_bytes() == SECOND_FILES["scripts/run.sh"]
            assert mode_of(landed) == 0o755
            assert mode_of(root / NAME / "scripts" / "README.md") == 0o644
            assert mode_of(root / NAME / "SKILL.md") == 0o644

        stored = ledger_rows(app)[0]
        assert stored.version == "2.0.0"
        assert stored.consented_digest == second.digest
        assert app.staging_entries() == []


def test_an_update_with_no_consent_at_all_is_still_refused(
    tmp_path, served, keys
):
    trust, first = publish(tmp_path, served, keys)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        row = consented_install(app, first)
        second = publish_second(tmp_path, served, keys)
        offer_second(app)

        response = update_with(app, row, None)

        assert ledger_rows(app)[0].version == "1.0.0"

    assert response.status_code == 409, response.text
    sheet = refusal(response)
    assert sheet["code"] == CONSENT_REQUIRED
    assert len(sheet["digest"]) == 64
    assert sheet["digest"] == second.digest
    assert sheet["body_sha"] == _sha_of(BODY)




@pytest.mark.parametrize(
    "consent, expected",
    [
        (None, False),
        ({"digest": "d", "body_sha": "s", "scripts": False}, False),
        ({"digest": "other", "body_sha": "s", "scripts": True}, False),
        ({"digest": "d", "body_sha": "other", "scripts": True}, False),
        ({"digest": "d", "body_sha": "s", "scripts": True}, True),
    ],
)
def test_the_consent_rule_needs_all_three_to_match(consent, expected):
    answer = install_consent_satisfied(
        None if consent is None else InstallConsent(**consent),
        digest="d",
        body_sha="s",
    )

    assert answer is expected


def _installed_row(consented_body_sha):
    return InstalledItem(
        install_id="i1",
        item_id=ITEM_ID,
        kind="skill",
        publisher=PUBLISHER,
        name=NAME,
        version="1.0.0",
        digest="old-digest",
        scope="global",
        project_path="",
        auto_update=False,
        source_index_url="https://example.invalid/index.json",
        consented_digest="old-digest",
        consented_body_sha=consented_body_sha,
        publisher_key_id="K1",
        revision=1,
        installed_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        consent_via="sheet",
    )


@pytest.mark.parametrize(
    "consent, expected, claim",
    [
        (None, False, "no consent is a refusal"),
        (
            {"digest": "new", "body_sha": "sha", "scripts": False},
            False,
            "the script list was not accepted",
        ),
        (
            {"digest": "old", "body_sha": "sha", "scripts": True},
            False,
            "THE DEFECT: the old folder's digest, the new folder's text",
        ),
        (
            {"body_sha": "sha", "scripts": True},
            False,
            "a consent naming no folder at all names no folder",
        ),
        (
            {"digest": "new", "body_sha": "other", "scripts": True},
            False,
            "the text is not the text that staged",
        ),
        (
            {"digest": "new", "body_sha": "sha", "scripts": True},
            True,
            "all three name the bytes that staged",
        ),
    ],
)
def test_the_update_rule_for_a_script_bearing_version(consent, expected, claim):
    answer = consent_carried(
        _installed_row("sha"),
        InstalledUpdateRequest(expected_revision=1, consent=consent),
        "sha",
        scripts_present=True,
        digest="new",
    )

    assert answer is expected, claim


@pytest.mark.parametrize(
    "recorded, consent, expected, claim",
    [
        (
            "sha",
            None,
            True,
            "the text has not moved since the user read it",
        ),
        (
            None,
            {"body_sha": "sha"},
            True,
            "a row nobody was shown, and a caller that shows the new text",
        ),
        (
            "older",
            {"body_sha": "sha"},
            True,
            "the text moved and the caller showed the new one",
        ),
        (
            "older",
            None,
            False,
            "the text moved and nobody was shown it",
        ),
        (
            "older",
            {"body_sha": "other"},
            False,
            "consent to text that is not what staged",
        ),
        (
            None,
            None,
            False,
            "no record and no consent is not agreement",
        ),
    ],
)
def test_the_update_rule_for_a_version_without_scripts(
    recorded, consent, expected, claim
):
    answer = consent_carried(
        _installed_row(recorded),
        InstalledUpdateRequest(expected_revision=1, consent=consent),
        "sha",
        scripts_present=False,
        digest="unrelated",
    )

    assert answer is expected, claim




def test_the_extractor_still_refuses_scripts_by_default(tmp_path):
    archive = archive_of(tmp_path)

    with pytest.raises(ArchiveRefused) as raised:
        stage_archive(
            archive, tmp_path / "out", publisher=PUBLISHER, name=NAME
        )

    assert raised.value.code == SCRIPTS_NOT_SUPPORTED
    assert not (tmp_path / "out").exists()


def test_the_extractor_names_every_script_member_when_it_is_unlocked(tmp_path):
    archive = archive_of(tmp_path)

    staged = stage_archive(
        archive,
        tmp_path / "out",
        publisher=PUBLISHER,
        name=NAME,
        allow_scripts=True,
    )

    assert sorted(staged.archive.script_members) == [
        "scripts/README.md",
        "scripts/run.sh",
    ]
    assert mode_of(staged.path / "scripts" / "run.sh") == 0o755
    assert mode_of(staged.path / "scripts" / "README.md") == 0o644
    assert mode_of(staged.path / "SKILL.md") == 0o644


def test_the_exec_bit_write_is_proven_red_capable_by_mutation(
    tmp_path, monkeypatch
):
    archive = archive_of(tmp_path)
    monkeypatch.setattr(
        stage_module, "member_mode", lambda expected, *, allow_scripts: FILE_MODE
    )

    with pytest.raises(ArchiveRefused) as raised:
        stage_archive(
            archive,
            tmp_path / "out",
            publisher=PUBLISHER,
            name=NAME,
            allow_scripts=True,
        )

    assert "digest" in raised.value.detail
    assert not (tmp_path / "out").exists()


def _sha_of(body: bytes) -> str:
    import hashlib

    return hashlib.sha256(body).hexdigest()
