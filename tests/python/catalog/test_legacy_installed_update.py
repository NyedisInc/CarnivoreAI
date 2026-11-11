
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_lg_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_lg_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

# ruff: noqa: E402
from src.api.catalog_views import badge_for
from src.core.catalog import publisher_rename
from src.core.catalog.publisher_rename import find_installed_item
from src.core.skills.auto_update import NOT_IN_INDEX
from src.core.skills.records import read_sidecar
from tests.helpers.catalog_app import catalog_app, ledger_rows
from tests.helpers.catalog_surface import (
    build_skill, fixture_trust_root, item_for, keypairs, publish_index, serve_archive,
)
from tests.helpers.minisign_keys import SKIP_REASON, minisign_binary
from tests.test_auto_update_pass import arm, reasons, refresh, run_pass
from tests.test_catalog_installed_routes import BODY_V1, SECOND_COMMIT

pytestmark = pytest.mark.skipif(minisign_binary() is None, reason=SKIP_REASON)

NAME = "sme"


@pytest.fixture
def served(tmp_path) -> Path:
    root = tmp_path / "served"
    root.mkdir()
    return root


@pytest.fixture
def keys(tmp_path):
    return keypairs(tmp_path / "keys")


def _publish(tmp_path, served, keys, *, publisher, version, serial, second=False):
    index_kp, publisher_kp, _ = keys
    files = {"SKILL.md": BODY_V1, **({"reference.md": b"# more\n"} if second else {})}
    kwargs = {"commit": SECOND_COMMIT, "label": "v2"} if second else {}
    package = build_skill(tmp_path, publisher=publisher, name=NAME, files=files, **kwargs)
    serve_archive(served, package.tar_bytes, **({"commit": SECOND_COMMIT} if second else {}))
    item = item_for(package, publisher=publisher, name=NAME, version=version,
                    **({"commit": SECOND_COMMIT} if second else {}))
    publish_index(tmp_path, served, index_keypair=index_kp, publisher_keypair=publisher_kp, items=[item],
                  serial=serial, publisher_handle=publisher)
    return fixture_trust_root(index_kp, publisher_kp)


def _world(tmp_path, served, keys, monkeypatch):
    trust = _publish(tmp_path, served, keys, publisher="nyedis", version="1.0.0", serial=1)
    monkeypatch.setattr(publisher_rename, "production_trust_root", lambda: trust)
    monkeypatch.setattr(publisher_rename, "pinned_key_id", lambda: trust.publisher_key.key_id.strip().upper())
    return trust


def _install_legacy(app):
    response = app.client.post("/catalog/install", json={"item_id": f"nyedis/{NAME}", "scope": "global"})
    assert response.status_code == 200, response.text
    return response.json()


def test_legacy_row_badges_updates_and_relabels_to_the_successor(tmp_path, served, keys, monkeypatch):
    trust = _world(tmp_path, served, keys, monkeypatch)
    with catalog_app(tmp_path, served, trust_root=trust) as app:
        row = _install_legacy(app)
        assert row["item_id"] == "nyedis/sme" and row["version"] == "1.0.0"
        _publish(tmp_path, served, keys, publisher="carnivore", version="1.0.1", serial=2, second=True)
        refresh(app)
        stored = ledger_rows(app)[0]
        snapshot = app.services.catalog.index_cache.snapshot()
        assert badge_for(stored, snapshot) is True
        response = app.client.post(f"/catalog/installed/{row['install_id']}/update", json={"expected_revision": stored.revision})
        assert response.status_code == 200, response.text
        after = ledger_rows(app)[0]
        sidecar = read_sidecar(app.roots.claude_skills() / NAME)
    assert response.json()["item_id"] == "carnivore/sme"
    assert (after.item_id, after.publisher, after.version, after.install_id) == ("carnivore/sme", "carnivore", "1.0.1", row["install_id"])
    assert sidecar.publisher == "carnivore" and sidecar.version == "1.0.1"


def test_auto_update_follows_the_rename_and_relabels(tmp_path, served, keys, monkeypatch):
    trust = _world(tmp_path, served, keys, monkeypatch)
    with catalog_app(tmp_path, served, trust_root=trust) as app:
        arm(app, _install_legacy(app))
        _publish(tmp_path, served, keys, publisher="carnivore", version="1.0.1", serial=2, second=True)
        refresh(app)
        report = run_pass(app)
        after = ledger_rows(app)[0]
    assert NOT_IN_INDEX not in reasons(report)
    assert (after.item_id, after.version) == ("carnivore/sme", "1.0.1")


def _snap(*, trusted=(), untrusted=()):
    return SimpleNamespace(verified=SimpleNamespace(items=list(trusted), untrusted_items=list(untrusted)), refusal=None)


def _it(item_id, kind="skill"):
    return SimpleNamespace(id=item_id, kind=kind)


def test_resolver_negatives_and_precedence():
    twin = _it("carnivore/sme")
    assert find_installed_item(_snap(trusted=[twin]), "nyedis/sme", "skill") == (twin, False)
    assert find_installed_item(_snap(untrusted=[twin]), "nyedis/sme", "skill") == (None, False)
    assert find_installed_item(_snap(trusted=[twin]), "nyedis/sme", "theme") == (None, False)
    assert find_installed_item(_snap(trusted=[twin]), "someone/sme", "skill") == (None, False)
    assert find_installed_item(_snap(trusted=[twin]), "nyedisx/sme", "skill") == (None, False)
    exact = _it("nyedis/sme")
    assert find_installed_item(_snap(trusted=[twin, exact]), "nyedis/sme", "skill") == (exact, False)
    assert find_installed_item(_snap(trusted=[twin], untrusted=[exact]), "nyedis/sme", "skill") == (exact, True)
    assert find_installed_item(SimpleNamespace(verified=None), "nyedis/sme", "skill") == (None, False)
