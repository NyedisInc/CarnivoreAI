
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_tm_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_tm_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.core.catalog import theme_migration
from src.models.catalog import CatalogItem
from tests.helpers.catalog_app import catalog_app, ledger_rows
from tests.helpers.catalog_surface import (
    ARCHIVE_FOLDER_THEME,
    build_skill,
    fixture_trust_root,
    keypairs,
    publish_index,
    serve_archive,
    theme_item_for,
    theme_manifest,
)
from tests.helpers.minisign_keys import SKIP_REASON, minisign_binary

pytestmark = pytest.mark.skipif(minisign_binary() is None, reason=SKIP_REASON)

COMMIT = "c" * 40


def _publish(tmp_path, publisher="nyedis", name="snes"):
    served = tmp_path / "served"
    served.mkdir(exist_ok=True)
    index_kp, publisher_kp, _ = keypairs(tmp_path / "keys")
    package = build_skill(
        tmp_path, publisher=publisher, name=name,
        files={"theme.json": theme_manifest(name, effects="effects.js"), "effects.js": b"export default function e() {}\n"},
        folder=ARCHIVE_FOLDER_THEME, commit=COMMIT, label="t",
    )
    serve_archive(served, package.tar_bytes, commit=COMMIT)
    publish_index(
        tmp_path, served, index_keypair=index_kp, publisher_keypair=publisher_kp,
        items=[theme_item_for(package, publisher=publisher, name=name, commit=COMMIT, version="1.0.0")], serial=1,
    )
    return served, fixture_trust_root(index_kp, publisher_kp)


def _run(app):
    app.clock.advance(301)
    assert app.client.post("/catalog/index/refresh").status_code == 200
    snapshot = app.services.catalog.index_cache.snapshot()
    return app.client.portal.call(theme_migration.run, snapshot, app.services)


@pytest.fixture
def notified(monkeypatch):
    from src.core import resource_push

    topics = []
    monkeypatch.setattr(resource_push, "notify", topics.append)
    return topics


@pytest.fixture
def env(tmp_path, monkeypatch):
    bundled = tmp_path / "bundled"
    bundled.mkdir()
    monkeypatch.setattr(theme_migration, "BUNDLED_THEMES_ROOT", bundled)
    return bundled


def test_in_use_moved_theme_installs_through_the_gate_and_notifies(tmp_path, env, notified, monkeypatch):
    served, trust = _publish(tmp_path)
    with catalog_app(tmp_path, served, trust_root=trust) as app:
        monkeypatch.setenv("CARNIVORE_USER_THEMES_DIR", str(app.roots.themes_dir()))
        app.services.themes.pinned_themes.clear()
        app.services.themes.pinned_themes["cloude_a"] = "snes"
        assert _run(app) == ["snes"]
        row = ledger_rows(app)[0]
        assert (row.item_id, row.consent_via, row.auto_update) == ("nyedis/snes", "one_click", True)
        assert (app.roots.themes_dir() / "snes" / "effects.js").is_file()
        assert "themes" in notified
        assert _run(app) == []
        assert len(ledger_rows(app)) == 1


def test_still_bundled_or_unused_theme_is_not_installed(tmp_path, env, monkeypatch):
    served, trust = _publish(tmp_path)
    with catalog_app(tmp_path, served, trust_root=trust) as app:
        monkeypatch.setenv("CARNIVORE_USER_THEMES_DIR", str(app.roots.themes_dir()))
        app.services.themes.pinned_themes.clear()
        assert _run(app) == []
        app.services.themes.pinned_themes["cloude_a"] = "snes"
        (env / "snes").mkdir()
        assert _run(app) == []
        assert ledger_rows(app) == []


def test_non_nyedis_item_is_refused_before_any_fetch(tmp_path, env, monkeypatch):
    item = CatalogItem.model_construct(id="nyedis/snes", kind="theme", publisher="someone", name="snes", versions=[])
    snapshot = SimpleNamespace(
        verified=SimpleNamespace(items=[item], untrusted_items=[]), refusal=None,
    )
    import src.api.catalog_install_support as support
    import src.api.catalog_views as views

    monkeypatch.setattr(views, "latest_version", lambda _i: SimpleNamespace(v="1.0.0", digest="x"))

    async def boom(*_a, **_k):
        raise AssertionError("fetched a non-first-party item")

    monkeypatch.setattr(support, "fetch_and_stage_with", boom)
    assert asyncio.run(theme_migration.install_one(SimpleNamespace(), snapshot, "snes")) is False


def test_retired_pins_are_pruned_but_a_community_name_in_use_is_kept(tmp_path, monkeypatch):
    from src.core.sessions.theme_store import ThemeStore

    user_dir = tmp_path / "themes"
    user_dir.mkdir()
    monkeypatch.setenv("CARNIVORE_USER_THEMES_DIR", str(user_dir))
    pins = tmp_path / "pins.json"
    store = ThemeStore(pin_path=lambda: pins)
    store.pinned_themes.update({"a": "ascii-raven", "b": "cannabis", "c": "snes", "d": "black_market"})
    services = SimpleNamespace(themes=store)
    (user_dir / "black_market").mkdir()
    dropped = theme_migration.prune_retired_pins(services)
    assert sorted(dropped) == ["a", "b"]
    assert store.pinned_themes == {"c": "snes", "d": "black_market"}
    assert json.loads(pins.read_text()) == store.pinned_themes
    assert theme_migration.prune_retired_pins(services) == []


def test_boot_journal_recovery_announces_themes_and_dir_is_ensured():
    source = (ROOT / "src" / "api" / "shell" / "static.py").read_text(encoding="utf-8")
    boot = (ROOT / "src" / "core" / "boot" / "background.py").read_text(encoding="utf-8")
    block = boot.split("async def _recover_skill_updates", 1)[1].split("task = asyncio.create_task(_recover_skill_updates())", 1)[0]
    assert "resource_push.notify(resource_topics.THEMES)" in block
    assert "theme_migration.ensure_user_themes_dir()" in source
    assert "theme_migration.prune_retired_pins(services)" in boot


def test_deprecated_item_and_degraded_index_are_not_installed_unattended(monkeypatch):
    import src.api.catalog_install_support as support
    import src.api.catalog_views as views

    item = SimpleNamespace(id="nyedis/snes", deprecated=SimpleNamespace(superseded_by=None))
    snapshot = SimpleNamespace(verified=SimpleNamespace(), refusal=None, degraded=False)
    monkeypatch.setattr(views, "find_item", lambda _s, _i: (item, False))
    monkeypatch.setattr(views, "latest_version", lambda _i: SimpleNamespace(v="1.0.0", digest="x"))
    monkeypatch.setattr(theme_migration, "is_first_party_item", lambda _i: True)

    async def boom(*_a, **_k):
        raise AssertionError("fetched a deprecated item")

    monkeypatch.setattr(support, "fetch_and_stage_with", boom)
    assert asyncio.run(theme_migration.install_one(SimpleNamespace(), snapshot, "snes")) is False

    def no_work(*_a, **_k):
        raise AssertionError("a degraded index reached the migration")

    monkeypatch.setattr(theme_migration, "wanted_ids", no_work)
    frozen = SimpleNamespace(verified=SimpleNamespace(), refusal=None, degraded=True)
    assert asyncio.run(theme_migration.run(frozen, SimpleNamespace())) == []


def test_retired_ascii_pin_is_kept_when_the_user_has_that_folder(tmp_path, monkeypatch):
    from src.core.sessions.theme_store import ThemeStore

    user_dir = tmp_path / "themes"
    (user_dir / "ascii-raven").mkdir(parents=True)
    monkeypatch.setenv("CARNIVORE_USER_THEMES_DIR", str(user_dir))
    store = ThemeStore(pin_path=lambda: tmp_path / "pins.json")
    store.pinned_themes.update({"a": "ascii-raven", "b": "ascii-relic"})
    dropped = theme_migration.prune_retired_pins(SimpleNamespace(themes=store))
    assert dropped == ["b"] and store.pinned_themes == {"a": "ascii-raven"}


def test_project_dotfile_read_is_bounded(tmp_path):
    from src.core.sessions.theme_dotfile import DOTFILE_MAX_BYTES, read_project_theme

    ok = tmp_path / "ok"
    ok.mkdir()
    (ok / ".cc.theme").write_text("snes\n")
    assert read_project_theme(ok) == "snes"
    dev = tmp_path / "dev"
    dev.mkdir()
    (dev / ".cc.theme").symlink_to("/dev/zero")
    assert read_project_theme(dev) is None
    big = tmp_path / "big"
    big.mkdir()
    (big / ".cc.theme").write_text("x" * (DOTFILE_MAX_BYTES + 1))
    assert read_project_theme(big) is None
