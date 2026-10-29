
from __future__ import annotations

import hashlib
import os
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_tc_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_tc_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from pydantic import ValidationError

from src.api import themes_routes as themes_routes_mod
from src.core import (
    theme_catalog_consent,
    theme_script_consent,
    theme_script_digest,
)
from src.core.skills import kinds
from src.core.skills.install_types import (
    CONSENT_REQUIRED,
    NAME_RESERVED,
    SCOPE_NOT_SUPPORTED,
)
from src.models.catalog_names import is_first_party_publisher
from src.models.catalog import (
    BUNDLED_THEME_NAMES,
    FIRST_PARTY_THEME_NAMES,
    FIRST_PARTY_THEME_PUBLISHER,
    RESERVED_THEME_NAMES,
    RETIRED_THEME_NAMES,
    CatalogItem,
    is_reserved_name,
)
from tests.helpers.catalog_app import catalog_app, ledger_rows
from tests.helpers.catalog_surface import (
    build_skill,
    build_theme,
    fixture_trust_root,
    keypairs,
    publish_index,
    serve_archive,
    theme_item_for,
)
from tests.helpers.minisign_keys import SKIP_REASON, minisign_binary

PUBLISHER = "nyedis"
THEME = "neon"
THEME_ID = f"{PUBLISHER}/{THEME}"
GLOBAL = {"item_id": THEME_ID, "scope": "global"}

THEME_COMMIT = "c" * 40

EFFECTS_V1 = b"export function start() { /* v1 */ }\n"
EFFECTS_V2 = b"export function start() { /* v2, different bytes */ }\n"

pytestmark = pytest.mark.skipif(minisign_binary() is None, reason=SKIP_REASON)


@pytest.fixture
def served(tmp_path) -> Path:
    root = tmp_path / "served"
    root.mkdir()
    return root


@pytest.fixture
def keys(tmp_path):
    return keypairs(tmp_path / "keys")


def _publish_theme(
    tmp_path,
    served,
    keys,
    *,
    name: str = THEME,
    effects: bytes | None = None,
    scripts: int = 0,
    label: str = "pkg",
    publisher: str = PUBLISHER,
):
    index_kp, publisher_kp, _stranger = keys
    package = build_theme(
        tmp_path,
        publisher=publisher,
        name=name,
        effects=effects,
        commit=THEME_COMMIT,
        label=label,
    )
    serve_archive(served, package.tar_bytes, commit=THEME_COMMIT)
    publish_index(
        tmp_path,
        served,
        index_keypair=index_kp,
        publisher_keypair=publisher_kp,
        items=[
            theme_item_for(
                package,
                publisher=publisher,
                name=name,
                scripts=scripts,
                commit=THEME_COMMIT,
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
    manifest = (package.folder / "theme.json").read_bytes()
    return {
        "digest": package.digest,
        "body_sha": hashlib.sha256(manifest).hexdigest(),
        "scripts": True,
    }




def test_the_kinds_table_and_the_wire_literal_cannot_drift():
    literal = set(CatalogItem.model_fields["kind"].annotation.__args__)
    assert literal == set(kinds.KINDS)


def test_a_kind_this_version_does_not_know_is_still_refused():
    with pytest.raises(ValidationError):
        CatalogItem(
            id=f"{PUBLISHER}/x",
            kind="bundle",
            name="x",
            publisher=PUBLISHER,
            latest="1.0.0",
            card={"title": "x", "brief": "x"},
            fm={"description": "x"},
            versions=[],
        )


def test_a_theme_answers_theme_json_and_its_own_folder():
    assert kinds.manifest_name(kinds.KIND_THEME) == "theme.json"
    assert kinds.archive_folder(kinds.KIND_THEME) == "themes"
    assert kinds.scopes_for(kinds.KIND_THEME) == ("global",)
    assert not kinds.scope_supported(kinds.KIND_THEME, "project")
    assert kinds.manifest_name(kinds.KIND_SKILL) == "SKILL.md"
    assert kinds.scope_supported(kinds.KIND_SKILL, "project")


@pytest.mark.parametrize("kind", ["bundle", "workspace", "", "SKILL"])
def test_an_unknown_kind_raises_rather_than_defaulting(kind):
    for call in (kinds.manifest_name, kinds.archive_folder, kinds.scopes_for):
        with pytest.raises(ValueError):
            call(kind)


def test_a_bundled_theme_name_is_reserved_and_a_skill_of_that_name_is_not():
    assert is_reserved_name("matrix", "theme")
    assert not is_reserved_name("matrix", "skill")
    assert is_reserved_name("  Matrix  ", "theme")
    bundled = {
        path.parent.name
        for path in (ROOT / "client" / "css" / "themes").glob("*/theme.json")
    }
    assert bundled <= set(RESERVED_THEME_NAMES)
    assert set(BUNDLED_THEME_NAMES) <= bundled
    assert len(BUNDLED_THEME_NAMES) == 12
    assert len(FIRST_PARTY_THEME_NAMES) == 16
    assert len(RETIRED_THEME_NAMES) == 11
    assert len(RESERVED_THEME_NAMES) == 39


def test_first_party_theme_names_are_free_only_for_the_first_party_handle():
    assert not is_reserved_name("snes", "theme", FIRST_PARTY_THEME_PUBLISHER)
    assert is_reserved_name("snes", "theme", "someone")
    assert is_reserved_name("snes", "theme")
    assert is_reserved_name("snes", "theme", "example-owner")
    assert is_first_party_publisher(" Nyedis ") and not is_first_party_publisher("example-owner")
    assert not is_first_party_publisher(None)
    assert is_reserved_name("matrix", "theme", FIRST_PARTY_THEME_PUBLISHER)
    assert is_reserved_name("ascii-raven", "theme", FIRST_PARTY_THEME_PUBLISHER)
    assert is_reserved_name("ascii-raven", "theme", "someone")
    for free in ("cannabis", "black_market"):
        assert free not in RESERVED_THEME_NAMES
        assert not is_reserved_name(free, "theme", "someone")
        assert not is_reserved_name(free, "theme", FIRST_PARTY_THEME_PUBLISHER)
    assert not is_reserved_name("snes", "skill", "someone")


def test_a_first_party_theme_verifies_and_a_community_one_is_refused(
    tmp_path, served, keys
):
    trust, _package = _publish_theme(
        tmp_path, served, keys, name="snes", publisher="nyedis"
    )
    with catalog_app(tmp_path, served, trust_root=trust) as app:
        response = app.client.post(
            "/catalog/install", json={"item_id": "nyedis/snes", "scope": "global"}
        )
        assert response.status_code == 200, response.text
        assert len(ledger_rows(app)) == 1

    for n, handle in enumerate(("someone", "example-owner")):
        served2 = tmp_path / f"served{n}"
        served2.mkdir()
        trust, _package = _publish_theme(
            tmp_path, served2, keys, name="snes", publisher=handle, label=f"pkg{n}"
        )
        with catalog_app(tmp_path, served2, trust_root=trust) as app:
            response = app.client.post(
                "/catalog/install", json={"item_id": f"{handle}/snes", "scope": "global"}
            )
            assert response.status_code in (404, 409)
            if response.status_code == 409:
                assert _refusal(response) == NAME_RESERVED
            assert all(r.item_id != f"{handle}/snes" for r in ledger_rows(app))




def test_a_signed_theme_installs_into_the_themes_directory(tmp_path, served, keys):
    trust, package = _publish_theme(tmp_path, served, keys)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        response = app.client.post("/catalog/install", json=GLOBAL)
        assert response.status_code == 200, response.text

        landed = app.roots.themes_dir() / THEME
        manifest = landed / "theme.json"
        assert manifest.is_file()
        assert landed.is_symlink() is False
        assert b'"id": "neon"' in manifest.read_bytes()
        assert (landed / ".carnivore-skill.json").is_file()

        rows = ledger_rows(app)
        assert len(rows) == 1
        assert rows[0].kind == "theme"
        assert rows[0].digest == package.digest

        with app.services.catalog.ledger() as ledger:
            targets = ledger.targets(rows[0].install_id)
        assert [target.harness for target in targets] == ["app"]
        assert targets[0].path == str(landed)

        assert app.staging_entries() == []


def test_a_theme_install_names_the_themes_topic_and_hello_lists_it(
    tmp_path, served, keys, monkeypatch
):
    from src.core import resource_push
    from src.core.resource_push.topics import all_topics

    named: list = []
    monkeypatch.setattr(resource_push, "notify", named.append)
    trust, _package = _publish_theme(tmp_path, served, keys)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        assert app.client.post("/catalog/install", json=GLOBAL).status_code == 200

    assert "themes" in named
    assert "themes" in all_topics()


def test_an_installed_theme_is_listed_by_the_themes_endpoint(
    tmp_path, served, keys, monkeypatch
):
    trust, _package = _publish_theme(tmp_path, served, keys)
    empty_bundled = tmp_path / "bundled"
    empty_bundled.mkdir()

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        monkeypatch.setattr(
            themes_routes_mod, "_bundled_themes_root", lambda: empty_bundled
        )
        monkeypatch.setattr(
            themes_routes_mod, "_user_themes_root", lambda: app.roots.themes_dir()
        )

        assert app.client.post("/catalog/install", json=GLOBAL).status_code == 200

        listed = app.client.get("/themes")
        assert listed.status_code == 200
        ids = [manifest["id"] for manifest in listed.json()]
        assert ids == [THEME]
        assert listed.json()[0]["source"] == "user"


def test_a_theme_refuses_project_scope(tmp_path, served, keys):
    trust, _package = _publish_theme(tmp_path, served, keys)
    project = tmp_path / "project"
    project.mkdir()

    with catalog_app(tmp_path, served, trust_root=trust, projects=[project]) as app:
        response = app.client.post(
            "/catalog/install",
            json={
                "item_id": THEME_ID,
                "scope": "project",
                "project_path": str(project),
            },
        )
        assert response.status_code == 409
        assert _refusal(response) == SCOPE_NOT_SUPPORTED
        assert ledger_rows(app) == []
        assert app.staging_entries() == []


def test_a_theme_preview_shows_theme_json_as_the_consent_document(
    tmp_path, served, keys
):
    trust, _package = _publish_theme(tmp_path, served, keys)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        sheet = app.client.post("/catalog/install/preview", json=GLOBAL)
        assert sheet.status_code == 200, sheet.text
        body = sheet.json()
        assert '"cssVars"' in body["body"]
        assert [entry["path"] for entry in body["files"]] == ["theme.json"]
        assert body["warnings"] == []


def test_a_theme_archive_without_its_manifest_is_archive_invalid(tmp_path):
    from src.core.skills.stage import stage_archive
    from src.core.skills.validate import ArchiveRefused

    package = build_skill(
        tmp_path,
        publisher=PUBLISHER,
        name=THEME,
        files={"SKILL.md": b"---\nname: neon\n---\n# neon\n"},
        commit=THEME_COMMIT,
        folder=kinds.archive_folder(kinds.KIND_THEME),
        label="bad",
    )
    archive = tmp_path / "theme.tar.gz"
    archive.write_bytes(package.tar_bytes)

    with pytest.raises(ArchiveRefused) as refused:
        stage_archive(
            archive,
            tmp_path / "as-theme",
            publisher=PUBLISHER,
            name=THEME,
            kind=kinds.KIND_THEME,
        )
    assert refused.value.code == "archive_invalid"
    assert "theme.json" in refused.value.detail


def test_a_reserved_theme_name_never_reaches_an_install(tmp_path, served, keys):
    trust, _package = _publish_theme(tmp_path, served, keys, name="matrix")

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        response = app.client.post(
            "/catalog/install",
            json={"item_id": f"{PUBLISHER}/matrix", "scope": "global"},
        )
        assert response.status_code in (404, 409)
        if response.status_code == 409:
            assert _refusal(response) == NAME_RESERVED
        assert ledger_rows(app) == []




def test_a_theme_shipping_a_script_is_refused_without_consent(
    tmp_path, served, keys
):
    trust, package = _publish_theme(
        tmp_path, served, keys, effects=EFFECTS_V1, scripts=1
    )

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        response = app.client.post("/catalog/install", json=GLOBAL)
        assert response.status_code == 409
        assert _refusal(response) == CONSENT_REQUIRED
        assert ledger_rows(app) == []


def test_a_theme_shipping_a_script_installs_with_consent(tmp_path, served, keys):
    trust, package = _publish_theme(
        tmp_path, served, keys, effects=EFFECTS_V1, scripts=1
    )

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        consent = _consent_for(package)
        response = app.client.post(
            "/catalog/install", json={**GLOBAL, "consent": consent}
        )
        assert response.status_code == 200, response.text

        landed = app.roots.themes_dir() / THEME
        assert (landed / "effects.js").read_bytes() == EFFECTS_V1
        assert ledger_rows(app)[0].kind == "theme"


def test_a_grant_naming_other_bytes_is_dropped_when_the_catalog_writes(
    tmp_path, served, keys
):
    trust, package = _publish_theme(
        tmp_path, served, keys, effects=EFFECTS_V1, scripts=1
    )
    stale = hashlib.sha256(b"whatever the previous copy was").hexdigest()

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        app.prefs.update(
            {"theme_script_consent": {THEME: {"decision": "always", "digest": stale}}}
        )
        assert app.prefs.read()["values"]["theme_script_consent"][THEME]

        consent = _consent_for(package)
        assert (
            app.client.post(
                "/catalog/install", json={**GLOBAL, "consent": consent}
            ).status_code
            == 200
        )

        held = app.prefs.read()["values"].get("theme_script_consent") or {}
        assert THEME not in held, "a grant for bytes that are gone must not survive"


def test_a_denial_is_never_dropped_by_an_install(tmp_path, served, keys):
    trust, package = _publish_theme(
        tmp_path, served, keys, effects=EFFECTS_V1, scripts=1
    )

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        app.prefs.update({"theme_script_consent": {THEME: {"decision": "never"}}})

        consent = _consent_for(package)
        assert (
            app.client.post(
                "/catalog/install", json={**GLOBAL, "consent": consent}
            ).status_code
            == 200
        )

        held = app.prefs.read()["values"]["theme_script_consent"]
        assert held[THEME] == {"decision": "never"}


def test_a_matching_grant_survives_a_write_of_the_same_bytes(tmp_path, served, keys):
    trust, package = _publish_theme(
        tmp_path, served, keys, effects=EFFECTS_V1, scripts=1
    )

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        consent = _consent_for(package)
        assert (
            app.client.post(
                "/catalog/install", json={**GLOBAL, "consent": consent}
            ).status_code
            == 200
        )

        landed = app.roots.themes_dir() / THEME
        matching = theme_script_digest.digest_theme_folder(landed)
        assert matching is not None
        app.prefs.update(
            {
                "theme_script_consent": {
                    THEME: {"decision": "always", "digest": matching}
                }
            }
        )

        dropped = theme_catalog_consent.drop_stale_effects_grant(
            app.prefs, THEME, landed
        )

        assert dropped is False, "a grant naming the folder on disk is not stale"
        held = app.prefs.read()["values"]["theme_script_consent"]
        assert held[THEME] == {"decision": "always", "digest": matching}




def test_stale_grant_is_true_only_for_an_always_whose_bytes_moved():
    digest = "a" * 64
    other = "b" * 64
    assert theme_catalog_consent.stale_grant(
        {"decision": "always", "digest": digest}, other
    )
    assert not theme_catalog_consent.stale_grant(
        {"decision": "always", "digest": digest}, digest
    )
    assert not theme_catalog_consent.stale_grant({"decision": "never"}, other)
    assert not theme_catalog_consent.stale_grant(None, other)
    assert not theme_catalog_consent.stale_grant({}, other)
    assert not theme_catalog_consent.stale_grant(
        {"decision": "always", "digest": "short"}, other
    )
    assert not theme_catalog_consent.stale_grant({"decision": "always"}, other)


def test_the_effects_digest_is_read_through_the_manifest(tmp_path):
    from src.core.skills.digest import digest_directory

    folder = tmp_path / "neon"
    folder.mkdir()
    (folder / "theme.json").write_text('{"id": "neon", "effects": "custom.js"}')
    (folder / "custom.js").write_bytes(EFFECTS_V1)

    taken = theme_catalog_consent.effects_digest_of(folder)
    assert taken == digest_directory(folder)[0]
    assert taken != hashlib.sha256(EFFECTS_V1).hexdigest()

    (folder / "theme.json").write_text('{"id": "neon"}')
    assert theme_catalog_consent.effects_digest_of(folder) is None
    (folder / "theme.json").write_text("not json")
    assert theme_catalog_consent.effects_digest_of(folder) is None


def test_the_ladder_still_refuses_a_changed_script_on_its_own():
    granted = "a" * 64
    served_now = "b" * 64
    decision = theme_script_consent.decide(
        declares_script=True,
        source="user",
        served_digest=served_now,
        record={"decision": "always", "digest": granted},
    )
    assert decision.may_run is False
    assert decision.outcome == theme_script_consent.PROMPT_CHANGED




def test_uninstalling_a_theme_drops_the_pins_that_named_it(tmp_path, served, keys):
    trust, _package = _publish_theme(tmp_path, served, keys)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        assert app.client.post("/catalog/install", json=GLOBAL).status_code == 200

        themes = app.services.themes
        themes.set_pin("cloude_a", THEME)
        themes.set_pin("cloude_b", THEME)
        themes.set_pin("cloude_c", "dracula")

        install_id = ledger_rows(app)[0].install_id
        removed = app.client.delete(f"/catalog/installed/{install_id}")
        assert removed.status_code == 200, removed.text

        assert themes.get_pin("cloude_a") is None
        assert themes.get_pin("cloude_b") is None
        assert themes.get_pin("cloude_c") == "dracula"
        assert removed.json()["trashed"]


def test_discarding_a_theme_leaves_the_project_dotfile_alone(tmp_path):
    from src.core.sessions.theme_store import ThemeStore

    project = tmp_path / "project"
    project.mkdir()
    store = ThemeStore(pin_path=lambda: tmp_path / "pinned_themes.json")
    store.set_pin("cloude_a", THEME)
    store.set_project_theme(project, THEME)

    assert store.discard_theme(THEME) == ["cloude_a"]
    assert store.get_pin("cloude_a") is None
    assert store.get_project_theme(project) == THEME


def test_discarding_a_theme_nobody_pinned_writes_nothing(tmp_path):
    store = ThemeStoreFactory(tmp_path)
    assert store.discard_theme("neon") == []
    assert store.discard_theme(None) == []
    assert store.discard_theme("") == []


def ThemeStoreFactory(tmp_path):
    from src.core.sessions.theme_store import ThemeStore

    return ThemeStore(pin_path=lambda: tmp_path / "pinned_themes.json")




def test_a_rewritten_sibling_makes_the_stored_grant_stale(tmp_path):
    folder = tmp_path / "neon"
    folder.mkdir()
    entry = b"import './helper.js';\nexport function start() {}\n"
    (folder / "theme.json").write_text('{"id": "neon", "effects": "effects.js"}')
    (folder / "effects.js").write_bytes(entry)
    (folder / "helper.js").write_bytes(b"export const ok = 1;\n")
    granted = theme_catalog_consent.effects_digest_of(folder)
    assert granted is not None

    (folder / "helper.js").write_bytes(b"export const ok = 1; fetch('/steal');\n")
    assert (folder / "effects.js").read_bytes() == entry

    assert theme_catalog_consent.stale_grant(
        {"decision": "always", "digest": granted},
        theme_catalog_consent.effects_digest_of(folder),
    ), "a rewritten sibling must not inherit a grant"




def _staged(tmp_path, files, *, name=THEME):
    from src.core.skills.stage import stage_archive
    from tests.helpers.catalog_surface import ARCHIVE_FOLDER_THEME

    package = build_skill(
        tmp_path,
        publisher=PUBLISHER,
        name=name,
        files=files,
        folder=ARCHIVE_FOLDER_THEME,
        label="staged",
    )
    archive = tmp_path / "archive.tar.gz"
    archive.write_bytes(package.tar_bytes)
    return stage_archive(
        archive,
        tmp_path / "dest",
        publisher=PUBLISHER,
        name=name,
        kind=kinds.KIND_THEME,
    )


def test_a_theme_json_that_is_not_json_is_refused_at_stage_time(tmp_path):
    from src.core.skills.validate import ARCHIVE_INVALID, ArchiveRefused

    with pytest.raises(ArchiveRefused) as excinfo:
        _staged(tmp_path, {"theme.json": b"this is not json at all"})

    assert excinfo.value.code == ARCHIVE_INVALID
    assert "not valid JSON" in excinfo.value.detail


def test_a_theme_json_whose_id_is_not_the_folder_is_refused(tmp_path):
    from src.core.skills.validate import ARCHIVE_INVALID, ArchiveRefused
    from tests.helpers.catalog_surface import theme_manifest

    with pytest.raises(ArchiveRefused) as excinfo:
        _staged(tmp_path, {"theme.json": theme_manifest("somebody-else")})

    assert excinfo.value.code == ARCHIVE_INVALID
    assert "installed and never listed" in excinfo.value.detail


def test_a_valid_theme_json_still_stages(tmp_path):
    from tests.helpers.catalog_surface import theme_manifest

    staged = _staged(tmp_path, {"theme.json": theme_manifest(THEME)})

    assert (staged.path / "theme.json").is_file()




def test_an_effects_file_at_0644_still_counts_as_script_bearing(tmp_path):
    import os as _os

    from src.core.skills.manifest_rules import declares_script

    folder = tmp_path / "neon"
    folder.mkdir()
    (folder / "theme.json").write_text('{"id": "neon", "effects": "effects.js"}')
    script = folder / "effects.js"
    script.write_bytes(EFFECTS_V1)
    _os.chmod(script, 0o644)

    assert _os.stat(script).st_mode & 0o111 == 0, "the fixture must be non-executable"
    assert declares_script(kinds.KIND_THEME, folder) is True


def test_a_theme_declaring_no_script_is_not_script_bearing(tmp_path):
    from src.core.skills.manifest_rules import declares_script

    folder = tmp_path / "neon"
    folder.mkdir()
    (folder / "theme.json").write_text('{"id": "neon"}')

    assert declares_script(kinds.KIND_THEME, folder) is False
    assert declares_script(kinds.KIND_SKILL, folder) is False


def test_an_unreadable_manifest_is_treated_as_script_bearing(tmp_path):
    from src.core.skills.manifest_rules import declares_script

    folder = tmp_path / "neon"
    folder.mkdir()
    (folder / "theme.json").write_text("not json")

    assert declares_script(kinds.KIND_THEME, folder) is True


def test_every_kind_has_an_entry_in_every_manifest_rules_table():
    from src.core.skills import manifest_rules

    for kind in kinds.KINDS:
        assert kind in manifest_rules.MANIFEST_SHAPE_FOR, kind
        assert kind in manifest_rules.IDENTITY_KEY_FOR, kind
        assert kind in manifest_rules.SCRIPT_KEY_FOR, kind
        manifest_rules.manifest_shape(kind)
        manifest_rules.identity_key(kind)
        manifest_rules.script_key(kind)


def test_a_plugin_manifest_is_not_held_to_the_themes_identity_rule():
    from src.core.skills import manifest_rules

    assert manifest_rules.identity_key(kinds.KIND_THEME) == "id"
    assert manifest_rules.identity_key(kinds.KIND_PLUGIN) is None


def test_a_real_plugin_folder_passes_the_manifest_gate(tmp_path):
    from src.core.skills.manifest_rules import check_manifest
    from tests.helpers.catalog_surface import plugin_manifest

    folder = tmp_path / "toolbelt"
    (folder / ".claude-plugin").mkdir(parents=True)
    (folder / ".claude-plugin" / "plugin.json").write_bytes(
        plugin_manifest("toolbelt")
    )

    assert check_manifest(kinds.KIND_PLUGIN, folder, expected_id="toolbelt") is None
    (folder / ".claude-plugin" / "plugin.json").write_text("not json")
    assert check_manifest(kinds.KIND_PLUGIN, folder, expected_id="toolbelt") is not None


BUNDLED_THEME_IDS = {
    "acid_trip", "alien", "black_ops", "blade_runner", "carnivore", "carnivore-light",
    "claude", "dracula", "hermes", "lovecraft", "matrix", "metal",
}


def test_bundled_theme_dir_is_exactly_the_twelve_plus_shared() -> None:
    on_disk = {p.name for p in (ROOT / "client" / "css" / "themes").iterdir() if p.is_dir()}
    assert on_disk == BUNDLED_THEME_IDS | {"_shared"}, sorted(on_disk ^ (BUNDLED_THEME_IDS | {"_shared"}))
    for theme_id in BUNDLED_THEME_IDS:
        assert (ROOT / "client" / "css" / "themes" / theme_id / "theme.json").is_file(), theme_id
