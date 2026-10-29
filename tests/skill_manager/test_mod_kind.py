
from __future__ import annotations

import os
import pathlib
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_mod_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_mod_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.api.catalog_consent import staged_plugin_declares_code
from src.api.catalog_one_click import REASON_KIND, one_click_precheck
from src.core.live_install_roots import HARNESS_MOD, LiveInstallRoots
from src.core.skills import kinds, manifest_rules
from src.core.skills.ledger import GLOBAL_PROJECT_PATH, SCOPE_GLOBAL, InstalledItem
from src.core.skills.updates import SCRIPTS_PRESENT, auto_update_eligible
from src.models.catalog import CatalogItem, ItemVersion
from src.models.catalog_api import InstallRequest
from tests.test_ports_conformance import StubSettingsReader

OLD_DIGEST = "a" * 64
NEW_DIGEST = "b" * 64
BODY_SHA = "c" * 64


@pytest.fixture
def home(tmp_path, monkeypatch) -> Path:
    fake = tmp_path / "home"
    fake.mkdir()
    monkeypatch.setattr(pathlib.Path, "home", classmethod(lambda cls: fake))
    monkeypatch.setenv("CODEX_HOME", str(fake / ".codex"))
    return fake


@pytest.fixture
def roots(tmp_path, home) -> LiveInstallRoots:
    return LiveInstallRoots(
        settings_reader=StubSettingsReader(pins=tmp_path / "p.json", cap=1, state=tmp_path / "state")
    )


def _version(**overrides) -> ItemVersion:
    fields = {
        "v": "2.0.0",
        "src": {"repo": "o/r", "path": "mods/pub/working-on", "commit": "d" * 40},
        "digest": NEW_DIGEST,
        "size": 10,
        "files": 1,
        "scripts": 0,
        "published_at": "2026-10-09T00:00:00Z",
        "sig": {"key_id": "RWkey", "sig": "c2ln", "tc": "", "gsig": "Z3NpZw=="},
    }
    fields.update(overrides)
    return ItemVersion(**fields)


def _row(kind: str) -> InstalledItem:
    return InstalledItem(
        install_id="i1", item_id="pub/working-on", kind=kind, publisher="pub", name="working-on",
        version="1.0.0", digest=OLD_DIGEST, scope=SCOPE_GLOBAL, project_path=GLOBAL_PROJECT_PATH,
        auto_update=True, source_index_url="https://example.invalid/index.json",
        consented_digest=OLD_DIGEST, consented_body_sha=BODY_SHA, publisher_key_id="RWkey",
        revision=1, installed_at="2026-10-09T00:00:00Z", updated_at="2026-10-09T00:00:00Z",
        consent_via="sheet",
    )


def test_the_kind_tables_all_know_mod():
    assert "mod" in CatalogItem.model_fields["kind"].annotation.__args__
    assert kinds.KIND_MOD in kinds.KINDS
    assert kinds.manifest_name("mod") == ".claude-plugin/plugin.json"
    assert kinds.archive_folder("mod") == "mods"
    assert kinds.scopes_for("mod") == ("global",)
    assert not kinds.scope_supported("mod", "project")
    for table in (manifest_rules.MANIFEST_SHAPE_FOR, manifest_rules.IDENTITY_KEY_FOR, manifest_rules.SCRIPT_KEY_FOR):
        assert "mod" in table
    assert manifest_rules.manifest_shape("mod") == manifest_rules.SHAPE_JSON
    assert manifest_rules.identity_key("mod") is None
    assert manifest_rules.script_key("mod") is None


def test_a_mod_has_one_global_target_under_claude_mods(roots, home):
    targets = roots.targets_for("mod", "global", None)
    assert [(t.harness, t.leaf_dir) for t in targets] == [(HARNESS_MOD, home / ".claude" / "mods")]
    with pytest.raises(ValueError):
        roots.targets_for("mod", "project", str(home))
    with pytest.raises(ValueError):
        roots.targets_for("mod", "global", str(home))
    assert roots.required_manifest("mod") == ".claude-plugin/plugin.json"


def test_mod_folders_are_found_by_harness_and_reported_when_present(roots, home):
    assert HARNESS_MOD not in roots.present_harnesses()
    (home / ".claude" / "mods" / "working-on").mkdir(parents=True)
    assert HARNESS_MOD in roots.present_harnesses()
    assert roots.root_listing(HARNESS_MOD) == ("working-on",)
    assert roots.trash_dir(HARNESS_MOD, "global", None) == home / ".claude" / ".carnivore-trash"


def test_a_mod_always_declares_code_even_with_an_empty_manifest(tmp_path):
    folder = tmp_path / "working-on"
    (folder / ".claude-plugin").mkdir(parents=True)
    (folder / ".claude-plugin" / "plugin.json").write_text('{"name": "working-on"}')
    assert staged_plugin_declares_code("mod", folder) is True
    assert manifest_rules.declares_script("mod", folder) is False


def test_a_mod_never_auto_updates_and_never_installs_in_one_click():
    assert auto_update_eligible(_row("skill"), _version(), BODY_SHA, verified=True, scripts_present=False).ok
    answer = auto_update_eligible(_row("mod"), _version(), BODY_SHA, verified=True, scripts_present=False)
    assert (answer.ok, answer.reason) == (False, SCRIPTS_PRESENT)

    item = CatalogItem(
        id="pub/working-on", kind="mod", name="working-on", publisher="pub", latest="2.0.0",
        card={"title": "working on", "brief": "x"}, fm={"description": "x"}, versions=[_version()],
    )
    body = InstallRequest(item_id=item.id, scope="global")
    assert one_click_precheck(item, item.versions[0], body) == REASON_KIND
