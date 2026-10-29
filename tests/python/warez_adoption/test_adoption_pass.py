
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Dict

import pytest
import structlog
from fastapi import FastAPI
from fastapi.testclient import TestClient

from scripts.warez import unadopt
from src.api import catalog_install_routes
from src.api.auth import require_auth
from src.core.catalog.services import build_catalog_services
from src.core.composition import build_services
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.ui_preferences_store import UiPreferencesStore
from src.cplugs.host import adoption, state as cplug_state
from src.cplugs.registry import PLUGINS_ROOT, plugin_folders
from tests.helpers.catalog_app import StateOnlySettings
from tests.helpers.catalog_surface import FrozenClock
from tests.test_skill_installer import FakeInstallRoots

SHIPPED = plugin_folders(PLUGINS_ROOT)


class Env:

    def __init__(self, tmp_path: Path) -> None:
        self.state = tmp_path / "state"
        self.state.mkdir()
        ensure_db_migrated(self.state, 4, "0.8.2")
        cplugs = self.state / "cplugs"
        (cplugs / "huddle").mkdir(parents=True)
        (cplugs / "huddle" / "items.db").write_bytes(b"owner data")
        (cplugs / "save" / "vault").mkdir(parents=True)
        (cplugs / "save" / "vault" / "point").write_bytes(b"the only copy")
        (cplugs / cplug_state.STATE_FILE).write_text(json.dumps({"cplugs": {"huddle": {"enabled": True}, "flow": {"enabled": False}}}))
        roots = FakeInstallRoots(tmp_path / "roots")
        roots.make_roots()
        clock = FrozenClock()
        config = tmp_path / "config.json"
        config.write_text("{}\n", encoding="utf-8")
        prefs = UiPreferencesStore(lambda: config)
        catalog = build_catalog_services(index_url=lambda: "https://catalog.invalid/index.json",
                                         api_base_url=lambda: "https://catalog.invalid/api/v1", clock=clock,
                                         open_db=lambda: connect(db_path_for(self.state)))
        self.services = build_services(clock=clock, install_roots=roots, catalog=catalog,
                                       settings_reader=StateOnlySettings(self.state), ui_preferences=prefs)
        self.prefs = prefs

    def tree_hash(self) -> Dict[str, str]:
        out = {}
        for path in sorted((self.state / "cplugs").rglob("*")):
            if path.is_file():
                out[str(path.relative_to(self.state))] = hashlib.sha256(path.read_bytes()).hexdigest() + f"@{path.stat().st_mtime_ns}"
        return out

    def rows(self) -> list:
        with self.services.catalog.ledger() as ledger:
            return ledger.list()


@pytest.fixture
def env(tmp_path) -> Env:
    return Env(tmp_path)


def test_every_compiled_in_plugin_gets_one_builtin_row_and_nothing_else_is_written(env: Env) -> None:
    before = env.tree_hash()
    assert before, "the fixture state tree must not be empty, or the unchanged-hash claim proves nothing"
    result = adoption.adopt_builtin_plugins(env.services)
    rows = [r for r in env.rows() if r.kind == "cplug"]
    assert sorted(r.item_id for r in rows) == sorted(f"nyedis/{i}" for i in SHIPPED) and len(SHIPPED) == 10
    assert result.adopted == 10 and result.failed == 0
    for row in rows:
        assert (row.source_index_url, row.publisher_key_id, row.auto_update, row.consent_via, row.scope) == ("builtin", "builtin", False, "one_click", "global")
        assert row.digest.startswith("builtin:")
    assert env.tree_hash() == before
    assert cplug_state.state_path(env.state).read_text() == json.dumps({"cplugs": {"huddle": {"enabled": True}, "flow": {"enabled": False}}})


def test_a_second_pass_writes_nothing(env: Env) -> None:
    adoption.adopt_builtin_plugins(env.services)
    first = env.rows()
    again = adoption.adopt_builtin_plugins(env.services)
    assert (again.adopted, again.updated, again.failed) == (0, 0, 0)
    assert env.rows() == first, "revisions, timestamps and ids must be unchanged"


def test_a_stale_version_on_a_builtin_row_follows_the_manifest(env: Env, monkeypatch) -> None:
    adoption.adopt_builtin_plugins(env.services)
    with env.services.catalog.ledger() as ledger:
        row = ledger.find("nyedis/flow", "global", "")
        ledger.update(row.install_id, expected_revision=row.revision, now=row.updated_at, version="0.0.1")
    result = adoption.adopt_builtin_plugins(env.services)
    assert result.updated == 1
    with env.services.catalog.ledger() as ledger:
        assert ledger.find("nyedis/flow", "global", "").version != "0.0.1"


def test_a_failing_ledger_is_inert_it_warns_and_does_not_raise(env: Env) -> None:
    class Boom:
        def ledger(self):
            raise sqlite3.OperationalError("database is locked")

    broken = type("S", (), {"catalog": Boom(), "clock": env.services.clock})()
    before = env.tree_hash()
    with structlog.testing.capture_logs() as logs:
        result = adoption.adopt_builtin_plugins(broken)
    assert result.adopted == 0 and result.failed >= 1
    assert any(e["event"] == "cplug_adoption_failed" and e["log_level"] == "warning" for e in logs)
    assert env.tree_hash() == before


def test_the_installed_list_still_answers_with_the_rows_present(env: Env) -> None:
    adoption.adopt_builtin_plugins(env.services)
    app = FastAPI()
    app.include_router(catalog_install_routes.router)
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    app.state.services = env.services
    app.state.ui_preferences_store = env.prefs
    with TestClient(app) as client:
        response = client.get("/catalog/installed")
    assert response.status_code == 200, response.text
    assert {i["item_id"] for i in response.json()["items"] if i["kind"] == "cplug"} == {f"nyedis/{i}" for i in SHIPPED}


def test_the_rollback_script_deletes_builtin_rows_only(env: Env) -> None:
    adoption.adopt_builtin_plugins(env.services)
    with env.services.catalog.ledger() as ledger:
        keep = ledger.insert(_skill_row())
    assert unadopt.remove_builtin_rows(db_path_for(env.state), dry_run=True) == 10
    assert len([r for r in env.rows() if r.kind == "cplug"]) == 10
    assert unadopt.remove_builtin_rows(db_path_for(env.state)) == 10
    assert [r.item_id for r in env.rows()] == [keep.item_id]
    assert unadopt.remove_builtin_rows(db_path_for(env.state)) == 0


def _skill_row():
    from src.core.skills.ledger_types import InstalledItem

    return InstalledItem(install_id="s1", item_id="carnivore/huddle", kind="skill", publisher="carnivore", name="huddle", version="bundled-1",
                         digest="d", scope="global", project_path="", auto_update=False, source_index_url="bundled", consented_digest="d",
                         consented_body_sha="b", publisher_key_id="bundled", revision=1, installed_at="t", updated_at="t", consent_via="one_click")
