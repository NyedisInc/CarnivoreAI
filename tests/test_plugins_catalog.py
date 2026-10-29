
from __future__ import annotations

import hashlib
import os
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_pc_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_pc_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.core.skills import kinds
from src.core.skills.install_types import CONSENT_REQUIRED
from src.models.catalog import CatalogItem
from tests.helpers.catalog_app import catalog_app, ledger_rows
from tests.helpers.catalog_surface import (
    build_plugin,
    build_skill,
    fixture_trust_root,
    keypairs,
    plugin_item_for,
    publish_index,
    serve_archive,
)
from tests.helpers.minisign_keys import SKIP_REASON, minisign_binary

PUBLISHER = "alex"
PLUGIN = "toolbelt"
PLUGIN_ID = f"{PUBLISHER}/{PLUGIN}"
GLOBAL = {"item_id": PLUGIN_ID, "scope": "global"}

MANIFEST = ".claude-plugin/plugin.json"

PLUGIN_COMMIT = "d" * 40

pytestmark = pytest.mark.skipif(minisign_binary() is None, reason=SKIP_REASON)


@pytest.fixture
def served(tmp_path) -> Path:
    root = tmp_path / "served"
    root.mkdir()
    return root


@pytest.fixture
def keys(tmp_path):
    return keypairs(tmp_path / "keys")


def _publish_plugin(
    tmp_path,
    served,
    keys,
    *,
    name: str = PLUGIN,
    files: dict | None = None,
    exec_paths: tuple = (),
    scripts: int = 0,
    label: str = "pkg",
):
    index_kp, publisher_kp, _stranger = keys
    package = build_plugin(
        tmp_path,
        publisher=PUBLISHER,
        name=name,
        files=files,
        exec_paths=exec_paths,
        commit=PLUGIN_COMMIT,
        label=label,
    )
    serve_archive(served, package.tar_bytes, commit=PLUGIN_COMMIT)
    publish_index(
        tmp_path,
        served,
        index_keypair=index_kp,
        publisher_keypair=publisher_kp,
        items=[
            plugin_item_for(
                package,
                publisher=PUBLISHER,
                name=name,
                scripts=scripts,
                commit=PLUGIN_COMMIT,
            )
        ],
        serial=1,
    )
    return fixture_trust_root(index_kp, publisher_kp), package


def _refusal(response):
    if response.status_code != 409:
        return None
    detail = response.json().get("detail")
    if isinstance(detail, dict):
        return detail.get("code")
    return None


def _consent_for(package) -> dict:
    manifest = (package.folder / MANIFEST).read_bytes()
    return {
        "digest": package.digest,
        "body_sha": hashlib.sha256(manifest).hexdigest(),
        "scripts": True,
    }


def _skills_root(app) -> Path:
    return app.roots.home / ".claude" / "skills"




def test_a_plugin_answers_its_own_manifest_folder_and_scopes():
    assert kinds.manifest_name(kinds.KIND_PLUGIN) == MANIFEST
    assert kinds.archive_folder(kinds.KIND_PLUGIN) == "plugins"
    assert kinds.scopes_for(kinds.KIND_PLUGIN) == ("global", "project")
    assert kinds.scope_supported(kinds.KIND_PLUGIN, "project")
    assert kinds.scope_supported(kinds.KIND_PLUGIN, "global")
    assert kinds.manifest_name(kinds.KIND_SKILL) == "SKILL.md"
    assert kinds.manifest_name(kinds.KIND_THEME) == "theme.json"


def test_the_kinds_table_and_the_wire_literal_agree_about_plugin():
    literal = set(CatalogItem.model_fields["kind"].annotation.__args__)
    assert "plugin" in literal
    assert literal == set(kinds.KINDS)


def test_a_plugin_manifest_is_the_first_one_that_is_not_a_basename():
    from src.core.skills.validate_types import (
        EXCLUDED_BASENAME_PREFIXES,
        EXCLUDED_BASENAMES,
        EXCLUDED_SEGMENTS,
    )

    assert "/" in MANIFEST, "a plugin's manifest is nested, unlike the other two"
    directory, basename = MANIFEST.split("/")
    assert directory not in EXCLUDED_SEGMENTS
    assert basename not in EXCLUDED_BASENAMES
    assert not basename.startswith(EXCLUDED_BASENAME_PREFIXES)




def test_a_signed_plugin_installs_into_the_skills_directory(tmp_path, served, keys):
    trust, package = _publish_plugin(tmp_path, served, keys)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        response = app.client.post("/catalog/install", json=GLOBAL)
        assert response.status_code == 200, response.text

        landed = _skills_root(app) / PLUGIN
        manifest = landed / MANIFEST
        assert manifest.is_file()
        assert not manifest.is_symlink()
        assert manifest.read_bytes() == (package.folder / MANIFEST).read_bytes()


def test_nothing_is_ever_written_into_the_directory_the_cli_owns(
    tmp_path, served, keys
):
    trust, _package = _publish_plugin(tmp_path, served, keys)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        cli_owned = app.roots.home / ".claude" / "plugins"
        assert not cli_owned.exists(), "precondition: the CLI dir is absent"

        response = app.client.post("/catalog/install", json=GLOBAL)
        assert response.status_code == 200, response.text

        assert (_skills_root(app) / PLUGIN / MANIFEST).is_file()
        assert not cli_owned.exists()


def test_a_plugin_gets_one_target_and_codex_is_not_one_of_them(
    tmp_path, served, keys
):
    trust, _package = _publish_plugin(tmp_path, served, keys)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        targets = app.roots.targets_for("plugin", "global", None)
        assert [t.harness for t in targets] == ["claude"]

        response = app.client.post("/catalog/install", json=GLOBAL)
        assert response.status_code == 200, response.text

        assert not (app.roots.home / ".codex" / "skills" / PLUGIN).exists()


def test_a_project_scope_plugin_targets_that_project_s_skills_directory(tmp_path):
    from tests.test_skill_installer import FakeInstallRoots

    roots = FakeInstallRoots(tmp_path)
    project = tmp_path / "repo"
    project.mkdir()

    targets = roots.targets_for("plugin", "project", str(project))
    assert [t.harness for t in targets] == ["claude"]
    assert targets[0].leaf_dir == project.resolve() / ".claude" / "skills"

    global_targets = roots.targets_for("plugin", "global", None)
    assert global_targets[0].leaf_dir == roots.home / ".claude" / "skills"
    assert "plugins" not in global_targets[0].leaf_dir.parts




def test_the_consent_document_is_the_plugin_manifest(tmp_path, served, keys):
    trust, package = _publish_plugin(tmp_path, served, keys)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        response = app.client.post("/catalog/install/preview", json=GLOBAL)
        assert response.status_code == 200, response.text
        body = response.json()

        published = (package.folder / MANIFEST).read_bytes().decode()
        assert body["body"] == published
        assert '"name": "toolbelt"' in body["body"]
        assert MANIFEST in {entry["path"] for entry in body["files"]}
        assert body["body_sha"] == hashlib.sha256(
            (package.folder / MANIFEST).read_bytes()
        ).hexdigest()


def test_a_plugin_archive_without_its_manifest_is_refused(tmp_path):
    from src.core.skills.validate import ArchiveRefused, validate_archive

    package = build_skill(
        tmp_path,
        publisher=PUBLISHER,
        name=PLUGIN,
        files={"README.md": b"no manifest here\n"},
        folder="plugins",
        commit=PLUGIN_COMMIT,
    )
    archive = tmp_path / "plugin.tar.gz"
    archive.write_bytes(package.tar_bytes)

    with pytest.raises(ArchiveRefused) as excinfo:
        validate_archive(
            archive, publisher=PUBLISHER, name=PLUGIN, kind=kinds.KIND_PLUGIN
        )
    assert MANIFEST in str(excinfo.value)




def test_a_plugin_shipping_an_executable_is_refused_without_consent(
    tmp_path, served, keys
):
    trust, _package = _publish_plugin(
        tmp_path,
        served,
        keys,
        files={"bin/run": b"#!/bin/sh\necho hi\n"},
        exec_paths=("bin/run",),
        scripts=1,
    )

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        response = app.client.post("/catalog/install", json=GLOBAL)
        assert _refusal(response) == CONSENT_REQUIRED
        assert not (_skills_root(app) / PLUGIN).exists()


def test_a_plugin_shipping_an_executable_installs_with_consent(
    tmp_path, served, keys
):
    trust, package = _publish_plugin(
        tmp_path,
        served,
        keys,
        files={"bin/run": b"#!/bin/sh\necho hi\n"},
        exec_paths=("bin/run",),
        scripts=1,
    )

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        response = app.client.post(
            "/catalog/install", json={**GLOBAL, "consent": _consent_for(package)}
        )
        assert response.status_code == 200, response.text

        landed = _skills_root(app) / PLUGIN
        assert (landed / MANIFEST).is_file()
        script = landed / "bin" / "run"
        assert script.is_file()
        assert script.stat().st_mode & 0o111, "an executable member lost its bit"


def test_the_preview_names_every_executable_file(tmp_path, served, keys):
    trust, _package = _publish_plugin(
        tmp_path,
        served,
        keys,
        files={
            "bin/run": b"#!/bin/sh\ntrue\n",
            "bin/other": b"#!/bin/sh\ntrue\n",
            "scripts/setup.sh": b"#!/bin/sh\ntrue\n",
        },
        exec_paths=("bin/run", "bin/other", "scripts/setup.sh"),
        scripts=3,
    )

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        response = app.client.post("/catalog/install/preview", json=GLOBAL)
        assert response.status_code == 200, response.text

        listed = {entry["path"] for entry in response.json()["files"]}
        assert {"bin/run", "bin/other", "scripts/setup.sh"} <= listed
        assert MANIFEST in listed




def test_uninstalling_a_plugin_removes_the_folder_and_trashes_it(
    tmp_path, served, keys
):
    trust, _package = _publish_plugin(tmp_path, served, keys)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        assert app.client.post("/catalog/install", json=GLOBAL).status_code == 200
        landed = _skills_root(app) / PLUGIN
        assert (landed / MANIFEST).is_file()

        install_id = ledger_rows(app)[0].install_id
        removed = app.client.delete(f"/catalog/installed/{install_id}")
        assert removed.status_code == 200, removed.text

        assert not landed.exists()
        assert removed.json()["trashed"]
        assert not (app.roots.home / ".claude" / "plugins").exists()


def test_a_plugin_lands_on_the_same_path_a_skill_of_that_name_would(
    tmp_path, served, keys
):
    from src.core.skills.roots import target_dir

    trust, _package = _publish_plugin(tmp_path, served, keys)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        assert app.client.post("/catalog/install", json=GLOBAL).status_code == 200

        landed = _skills_root(app) / PLUGIN
        assert (landed / MANIFEST).is_file()

        skill_target = next(
            t
            for t in app.roots.targets_for("skill", "global", None)
            if t.harness == "claude"
        )
        assert target_dir(skill_target, PLUGIN) == landed

        assert landed.parent.name == "skills"
        assert "plugins" not in landed.parts
