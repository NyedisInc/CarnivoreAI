
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_lo_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_lo_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.core.skills import kinds
from src.core.skills.install_types import (
    CONSENT_REQUIRED,
    DIGEST_MISMATCH,
    LOADOUT_MANIFEST_INVALID,
    LOADOUT_MEMBER_UNKNOWN,
    SCOPE_NOT_SUPPORTED,
)
from src.core.skills.loadout_manifest import (
    LoadoutManifestInvalid,
    parse_loadout_manifest,
)
from src.models.catalog import CatalogItem
from tests.helpers.catalog_app import catalog_app, ledger_rows
from tests.helpers.catalog_surface import (
    build_loadout,
    build_plugin,
    build_skill,
    build_theme,
    fixture_trust_root,
    item_for,
    keypairs,
    loadout_item_for,
    member_ref,
    plugin_item_for,
    publish_index,
    serve_archive,
    theme_item_for,
)
from tests.helpers.minisign_keys import SKIP_REASON, minisign_binary

PUBLISHER = "alex"
LOADOUT = "python"
LOADOUT_ID = f"{PUBLISHER}/{LOADOUT}"
GLOBAL = {"item_id": LOADOUT_ID, "scope": "global"}

COMMIT_SKILL = "1" * 40
COMMIT_THEME = "2" * 40
COMMIT_PLUGIN = "3" * 40
COMMIT_LOADOUT = "4" * 40
COMMIT_SECOND = "5" * 40

pytestmark = pytest.mark.skipif(minisign_binary() is None, reason=SKIP_REASON)


@pytest.fixture
def served(tmp_path) -> Path:
    root = tmp_path / "served"
    root.mkdir()
    return root


@pytest.fixture
def keys(tmp_path):
    return keypairs(tmp_path / "keys")


def _publish_set(
    tmp_path,
    served,
    keys,
    *,
    members=None,
    plugin_scripts: int = 0,
    extra_items=(),
    manifest_digest_override=None,
    schema: str = "carnivore.catalog.loadout/1",
):
    index_kp, publisher_kp, _stranger = keys

    skill = build_skill(
        tmp_path, publisher=PUBLISHER, name="sme", commit=COMMIT_SKILL, label="s"
    )
    theme = build_theme(
        tmp_path, publisher=PUBLISHER, name="neon", commit=COMMIT_THEME, label="t"
    )
    plugin = build_plugin(
        tmp_path,
        publisher=PUBLISHER,
        name="toolbelt",
        commit=COMMIT_PLUGIN,
        label="p",
        files=(
            {"bin/run": b"#!/bin/sh\necho hi\n"} if plugin_scripts else None
        ),
        exec_paths=("bin/run",) if plugin_scripts else (),
    )

    if members is None:
        skill_ref = member_ref(skill, publisher=PUBLISHER, name="sme")
        if manifest_digest_override is not None:
            skill_ref = dict(skill_ref, digest=manifest_digest_override)
        members = [
            skill_ref,
            member_ref(theme, publisher=PUBLISHER, name="neon"),
            member_ref(plugin, publisher=PUBLISHER, name="toolbelt"),
        ]

    loadout = build_loadout(
        tmp_path,
        publisher=PUBLISHER,
        name=LOADOUT,
        members=members,
        commit=COMMIT_LOADOUT,
        label="l",
        schema=schema,
    )

    for package, commit in (
        (skill, COMMIT_SKILL),
        (theme, COMMIT_THEME),
        (plugin, COMMIT_PLUGIN),
        (loadout, COMMIT_LOADOUT),
    ):
        serve_archive(served, package.tar_bytes, commit=commit)

    items = [
        item_for(skill, publisher=PUBLISHER, name="sme", commit=COMMIT_SKILL),
        theme_item_for(theme, publisher=PUBLISHER, name="neon", commit=COMMIT_THEME),
        plugin_item_for(
            plugin,
            publisher=PUBLISHER,
            name="toolbelt",
            commit=COMMIT_PLUGIN,
            scripts=plugin_scripts,
        ),
        loadout_item_for(
            loadout, publisher=PUBLISHER, name=LOADOUT, commit=COMMIT_LOADOUT
        ),
    ]
    items.extend(extra_items)

    publish_index(
        tmp_path,
        served,
        index_keypair=index_kp,
        publisher_keypair=publisher_kp,
        items=items,
    )
    trust = fixture_trust_root(index_kp, publisher_kp)
    return trust, {
        "skill": skill,
        "theme": theme,
        "plugin": plugin,
        "loadout": loadout,
    }




def test_a_loadout_answers_its_own_manifest_folder_and_scopes():
    assert kinds.manifest_name(kinds.KIND_LOADOUT) == "loadout.json"
    assert kinds.archive_folder(kinds.KIND_LOADOUT) == "loadouts"
    assert kinds.scopes_for(kinds.KIND_LOADOUT) == ("global",)
    assert not kinds.scope_supported(kinds.KIND_LOADOUT, "project")


def test_the_kinds_table_and_the_wire_literal_agree_about_loadout():
    literal = set(CatalogItem.model_fields["kind"].annotation.__args__)
    assert literal == set(kinds.KINDS)
    assert kinds.KIND_LOADOUT in literal




def test_a_manifest_naming_nothing_this_version_reads_is_refused():
    with pytest.raises(LoadoutManifestInvalid):
        parse_loadout_manifest(json.dumps({"schema": "other/1", "name": "x"}))


@pytest.mark.parametrize(
    "document",
    [
        "{not json",
        json.dumps([]),
        json.dumps({"schema": "carnivore.catalog.loadout/1", "name": "x"}),
        json.dumps(
            {"schema": "carnivore.catalog.loadout/1", "name": "x", "members": []}
        ),
    ],
    ids=["not-json", "not-object", "no-members", "empty-members"],
)
def test_a_manifest_that_is_not_a_member_list_is_refused(document):
    with pytest.raises(LoadoutManifestInvalid):
        parse_loadout_manifest(document)


def test_a_loadout_may_not_list_itself():
    body = json.dumps(
        {
            "schema": "carnivore.catalog.loadout/1",
            "name": "x",
            "members": [
                {"id": "alex/x", "version": "1.0.0", "digest": "a" * 64}
            ],
        }
    )
    with pytest.raises(LoadoutManifestInvalid, match="itself"):
        parse_loadout_manifest(body, own_id="alex/x")


def test_a_duplicate_member_is_refused_rather_than_folded():
    body = json.dumps(
        {
            "schema": "carnivore.catalog.loadout/1",
            "name": "x",
            "members": [
                {"id": "alex/sme", "version": "1.0.0", "digest": "a" * 64},
                {"id": "alex/sme", "version": "2.0.0", "digest": "b" * 64},
            ],
        }
    )
    with pytest.raises(LoadoutManifestInvalid, match="more than once"):
        parse_loadout_manifest(body)




def test_a_loadout_installs_every_member_and_records_the_set(
    tmp_path, served, keys
):
    trust, _packages = _publish_set(tmp_path, served, keys)
    with catalog_app(tmp_path, served, trust_root=trust) as app:
        answer = app.client.post("/catalog/install", json=GLOBAL)
        assert answer.status_code == 200, answer.text
        body = answer.json()

        assert body["complete"] is True
        states = {m["item_id"]: m["state"] for m in body["members"]}
        assert states == {
            f"{PUBLISHER}/sme": "installed",
            f"{PUBLISHER}/neon": "installed",
            f"{PUBLISHER}/toolbelt": "installed",
        }

        rows = {row.item_id: row for row in ledger_rows(app)}
        assert set(rows) == {
            LOADOUT_ID,
            f"{PUBLISHER}/sme",
            f"{PUBLISHER}/neon",
            f"{PUBLISHER}/toolbelt",
        }
        assert rows[LOADOUT_ID].kind == kinds.KIND_LOADOUT

        assert (app.roots.home / ".claude" / "skills" / "sme").is_dir()
        assert (app.roots.home / "themes" / "neon").is_dir()
        assert (app.roots.home / ".claude" / "skills" / "toolbelt").is_dir()


def test_a_loadout_lands_in_the_state_dir_and_never_among_the_themes(
    tmp_path, served, keys
):
    trust, _packages = _publish_set(tmp_path, served, keys)
    with catalog_app(tmp_path, served, trust_root=trust) as app:
        assert app.client.post("/catalog/install", json=GLOBAL).status_code == 200

        assert (app.roots.state / "loadouts" / LOADOUT).is_dir()
        assert (app.roots.state / "loadouts" / LOADOUT / "loadout.json").is_file()
        assert not (app.roots.home / "themes" / LOADOUT).exists()
        assert not (app.roots.home / ".claude" / "skills" / LOADOUT).exists()
        assert not (app.roots.home / ".codex" / "skills" / LOADOUT).exists()


def test_a_member_already_installed_is_a_no_op_and_not_a_failure(
    tmp_path, served, keys
):
    trust, _packages = _publish_set(tmp_path, served, keys)
    with catalog_app(tmp_path, served, trust_root=trust) as app:
        first = app.client.post(
            "/catalog/install",
            json={"item_id": f"{PUBLISHER}/sme", "scope": "global"},
        )
        assert first.status_code == 200, first.text

        answer = app.client.post("/catalog/install", json=GLOBAL)
        assert answer.status_code == 200, answer.text
        body = answer.json()

        states = {m["item_id"]: m["state"] for m in body["members"]}
        assert states[f"{PUBLISHER}/sme"] == "already_present"
        assert body["complete"] is True
        rows = [r for r in ledger_rows(app) if r.item_id == f"{PUBLISHER}/sme"]
        assert len(rows) == 1


def test_a_script_bearing_member_without_its_own_consent_refuses_alone(
    tmp_path, served, keys
):
    trust, _packages = _publish_set(tmp_path, served, keys, plugin_scripts=1)
    with catalog_app(tmp_path, served, trust_root=trust) as app:
        answer = app.client.post("/catalog/install", json=GLOBAL)
        assert answer.status_code == 200, answer.text
        body = answer.json()

        assert body["complete"] is False
        members = {m["item_id"]: m for m in body["members"]}
        refused = members[f"{PUBLISHER}/toolbelt"]
        assert refused["state"] == "refused"
        assert refused["code"] == CONSENT_REQUIRED

        assert members[f"{PUBLISHER}/sme"]["state"] == "installed"
        assert members[f"{PUBLISHER}/neon"]["state"] == "installed"
        assert (app.roots.home / ".claude" / "skills" / "sme").is_dir()
        assert not (app.roots.home / ".claude" / "skills" / "toolbelt").exists()

        installed = {row.item_id for row in ledger_rows(app)}
        assert f"{PUBLISHER}/toolbelt" not in installed
        assert LOADOUT_ID in installed


def test_the_partial_survives_into_the_listing(tmp_path, served, keys):
    trust, _packages = _publish_set(tmp_path, served, keys, plugin_scripts=1)
    with catalog_app(tmp_path, served, trust_root=trust) as app:
        assert app.client.post("/catalog/install", json=GLOBAL).status_code == 200

        listed = app.client.get("/catalog/installed")
        assert listed.status_code == 200, listed.text
        rows = {row["item_id"]: row for row in listed.json()["items"]}

        loadout = rows[LOADOUT_ID]
        assert loadout["complete"] is False
        refused = [m for m in loadout["members"] if m["state"] == "refused"]
        assert [m["item_id"] for m in refused] == [f"{PUBLISHER}/toolbelt"]

        assert rows[f"{PUBLISHER}/sme"]["members"] is None
        assert rows[f"{PUBLISHER}/sme"]["complete"] is None




def test_a_member_the_catalog_does_not_carry_refuses_the_whole_set(
    tmp_path, served, keys
):
    trust, packages = _publish_set(
        tmp_path,
        served,
        keys,
        members=[
            member_ref(
                build_skill(
                    tmp_path, publisher=PUBLISHER, name="sme", commit=COMMIT_SKILL,
                    label="s",
                ),
                publisher=PUBLISHER,
                name="sme",
            ),
            {"id": f"{PUBLISHER}/ghost", "version": "1.0.0", "digest": "c" * 64},
        ],
    )
    with catalog_app(tmp_path, served, trust_root=trust) as app:
        answer = app.client.post("/catalog/install", json=GLOBAL)
        assert answer.status_code == 409, answer.text
        assert answer.json()["detail"]["code"] == LOADOUT_MEMBER_UNKNOWN

        assert ledger_rows(app) == []
        assert not (app.roots.state / "loadouts" / LOADOUT).exists()
        assert not (app.roots.home / ".claude" / "skills" / "sme").exists()


def test_a_member_digest_the_catalog_disagrees_with_refuses_everything(
    tmp_path, served, keys
):
    trust, _packages = _publish_set(
        tmp_path, served, keys, manifest_digest_override="d" * 64
    )
    with catalog_app(tmp_path, served, trust_root=trust) as app:
        answer = app.client.post("/catalog/install", json=GLOBAL)
        assert answer.status_code == 409, answer.text
        assert answer.json()["detail"]["code"] == DIGEST_MISMATCH
        assert ledger_rows(app) == []


def test_a_manifest_this_version_cannot_read_refuses_the_whole_set(
    tmp_path, served, keys
):
    trust, _packages = _publish_set(tmp_path, served, keys, schema="other/9")
    with catalog_app(tmp_path, served, trust_root=trust) as app:
        answer = app.client.post("/catalog/install", json=GLOBAL)
        assert answer.status_code == 409, answer.text
        assert answer.json()["detail"]["code"] == LOADOUT_MANIFEST_INVALID
        assert ledger_rows(app) == []


def test_a_loadout_refuses_project_scope(tmp_path, served, keys):
    trust, _packages = _publish_set(tmp_path, served, keys)
    project = tmp_path / "project"
    project.mkdir()

    with catalog_app(
        tmp_path, served, trust_root=trust, projects=[project]
    ) as app:
        answer = app.client.post(
            "/catalog/install",
            json={
                "item_id": LOADOUT_ID,
                "scope": "project",
                "project_path": str(project),
            },
        )
        assert answer.status_code == 409, answer.text
        assert answer.json()["detail"]["code"] == SCOPE_NOT_SUPPORTED
        assert ledger_rows(app) == []
        assert app.staging_entries() == []




def test_the_preview_lists_every_member_with_what_it_is(tmp_path, served, keys):
    trust, _packages = _publish_set(tmp_path, served, keys, plugin_scripts=1)
    with catalog_app(tmp_path, served, trust_root=trust) as app:
        answer = app.client.post("/catalog/install/preview", json=GLOBAL)
        assert answer.status_code == 200, answer.text
        body = answer.json()

        assert "members" in body["body"]

        members = {m["item_id"]: m for m in body["loadout_members"]}
        assert set(members) == {
            f"{PUBLISHER}/sme",
            f"{PUBLISHER}/neon",
            f"{PUBLISHER}/toolbelt",
        }
        assert members[f"{PUBLISHER}/neon"]["kind"] == "theme"
        assert members[f"{PUBLISHER}/toolbelt"]["scripts"] == 1
        assert members[f"{PUBLISHER}/sme"]["scripts"] == 0
        assert members[f"{PUBLISHER}/sme"]["installed"] is False




def test_uninstalling_offers_back_only_the_members_nothing_else_claims(
    tmp_path, served, keys
):
    index_kp, publisher_kp, _stranger = keys

    skill = build_skill(
        tmp_path, publisher=PUBLISHER, name="sme", commit=COMMIT_SKILL, label="s"
    )
    theme = build_theme(
        tmp_path, publisher=PUBLISHER, name="neon", commit=COMMIT_THEME, label="t"
    )
    first = build_loadout(
        tmp_path,
        publisher=PUBLISHER,
        name=LOADOUT,
        members=[
            member_ref(skill, publisher=PUBLISHER, name="sme"),
            member_ref(theme, publisher=PUBLISHER, name="neon"),
        ],
        commit=COMMIT_LOADOUT,
        label="l",
    )
    second = build_loadout(
        tmp_path,
        publisher=PUBLISHER,
        name="rust",
        members=[member_ref(skill, publisher=PUBLISHER, name="sme")],
        commit=COMMIT_SECOND,
        label="l2",
    )

    for package, commit in (
        (skill, COMMIT_SKILL),
        (theme, COMMIT_THEME),
        (first, COMMIT_LOADOUT),
        (second, COMMIT_SECOND),
    ):
        serve_archive(served, package.tar_bytes, commit=commit)

    publish_index(
        tmp_path,
        served,
        index_keypair=index_kp,
        publisher_keypair=publisher_kp,
        items=[
            item_for(skill, publisher=PUBLISHER, name="sme", commit=COMMIT_SKILL),
            theme_item_for(
                theme, publisher=PUBLISHER, name="neon", commit=COMMIT_THEME
            ),
            loadout_item_for(
                first, publisher=PUBLISHER, name=LOADOUT, commit=COMMIT_LOADOUT
            ),
            loadout_item_for(
                second, publisher=PUBLISHER, name="rust", commit=COMMIT_SECOND
            ),
        ],
    )
    trust = fixture_trust_root(index_kp, publisher_kp)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        assert app.client.post("/catalog/install", json=GLOBAL).status_code == 200
        assert (
            app.client.post(
                "/catalog/install",
                json={"item_id": f"{PUBLISHER}/rust", "scope": "global"},
            ).status_code
            == 200
        )

        rows = {row.item_id: row for row in ledger_rows(app)}
        answer = app.client.delete(
            f"/catalog/installed/{rows[LOADOUT_ID].install_id}"
        )
        assert answer.status_code == 200, answer.text
        offered = answer.json()["removable_members"]

        assert offered == [f"{PUBLISHER}/neon"]

        after = {row.item_id for row in ledger_rows(app)}
        assert f"{PUBLISHER}/sme" in after
        assert f"{PUBLISHER}/neon" in after
        assert (app.roots.home / ".claude" / "skills" / "sme").is_dir()
        assert (app.roots.home / "themes" / "neon").is_dir()
        assert LOADOUT_ID not in after


def test_uninstalling_a_plain_skill_offers_nothing(tmp_path, served, keys):
    trust, _packages = _publish_set(tmp_path, served, keys)
    with catalog_app(tmp_path, served, trust_root=trust) as app:
        answer = app.client.post(
            "/catalog/install",
            json={"item_id": f"{PUBLISHER}/sme", "scope": "global"},
        )
        assert answer.status_code == 200, answer.text
        install_id = answer.json()["install_id"]

        removed = app.client.delete(f"/catalog/installed/{install_id}")
        assert removed.status_code == 200, removed.text
        assert removed.json()["removable_members"] == []
