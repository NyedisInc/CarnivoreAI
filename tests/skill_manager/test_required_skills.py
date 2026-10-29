
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import catalog_installed_routes, catalog_required_routes
from src.api.auth import require_auth
from src.api.catalog_required_routes import run_required_pass
from src.core.catalog.services import build_catalog_services
from src.core.composition import build_services
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.skills import bundled_install
from src.core.skills.bundled_install import BUNDLED_ROOT as REAL_BUNDLED_ROOT
from src.core.skills.required import REQUIRED_SKILLS, STATE_AVAILABLE, STATE_BLOCKED, STATE_DECLINED, STATE_INSTALLED
from src.core.ui_preferences_store import UiPreferencesStore
from tests.helpers.catalog_app import StateOnlySettings, ledger_rows
from tests.helpers.catalog_surface import FrozenClock
from tests.test_skill_installer import FakeInstallRoots

ITEM_ID = "carnivore/huddle"
V1 = "---\nname: huddle\ndescription: first\n---\n\n# huddle v1\n"
WB_ID = "carnivore/widget-builder"
WB = "---\nname: widget-builder\ndescription: build a widget\n---\n\n# widget-builder\n"
V2 = "---\nname: huddle\ndescription: second\n---\n\n# huddle v2\n"


class Env:

    def __init__(self, client, services, roots, bundled: Path) -> None:
        self.client, self.services, self.roots, self.bundled = client, services, roots, bundled

    def write_bundled(self, text: str) -> None:
        (self.bundled / "huddle" / "SKILL.md").write_text(text, encoding="utf-8")

    def run_pass(self) -> None:
        self.client.portal.call(run_required_pass, self.client.app)

    def state(self) -> dict:
        response = self.client.get("/catalog/required-skills")
        assert response.status_code == 200, response.text
        items = response.json()["items"]
        assert [i["item_id"] for i in items] == [s.item_id for s in REQUIRED_SKILLS]
        return items[0]

    def entry(self, item_id: str) -> dict:
        items = self.client.get("/catalog/required-skills").json()["items"]
        return next(i for i in items if i["item_id"] == item_id)

    def rows(self) -> list:
        return list(self._rows())

    def _rows(self):
        with self.services.catalog.ledger() as ledger:
            return ledger.list()

    def claude(self) -> Path:
        return self.roots.claude_skills() / "huddle"

    def codex(self) -> Path:
        return self.roots.codex_skills() / "huddle"


@pytest.fixture
def env(tmp_path, monkeypatch):
    bundled = tmp_path / "bundled"
    (bundled / "huddle").mkdir(parents=True)
    (bundled / "huddle" / "SKILL.md").write_text(V1, encoding="utf-8")
    (bundled / "widget-builder").mkdir()
    (bundled / "widget-builder" / "SKILL.md").write_text(WB, encoding="utf-8")
    monkeypatch.setattr(bundled_install, "BUNDLED_ROOT", bundled)
    state = tmp_path / "state"
    state.mkdir()
    ensure_db_migrated(state, 4, "0.8.2")
    roots = FakeInstallRoots(tmp_path / "roots")
    roots.make_roots()
    clock = FrozenClock()
    config = tmp_path / "config.json"
    config.write_text("{}\n", encoding="utf-8")
    prefs = UiPreferencesStore(lambda: config)
    catalog = build_catalog_services(index_url=lambda: "https://catalog.invalid/index.json",
                                     api_base_url=lambda: "https://catalog.invalid/api/v1", clock=clock,
                                     open_db=lambda: connect(db_path_for(state)))
    services = build_services(clock=clock, install_roots=roots, catalog=catalog,
                              settings_reader=StateOnlySettings(state), ui_preferences=prefs)
    app = FastAPI()
    app.include_router(catalog_required_routes.router)
    app.include_router(catalog_installed_routes.router)
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    app.state.services = services
    app.state.ui_preferences_store = prefs
    with TestClient(app) as client:
        yield Env(client, services, roots, bundled)


def test_the_real_bundled_skill_is_in_the_app():
    text = (REAL_BUNDLED_ROOT / "huddle" / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\nname: huddle\n")
    assert [s.folder for s in REQUIRED_SKILLS] == ["huddle", "widget-builder"]
    assert bundled_install.bundled_digest("huddle")
    builder = (REAL_BUNDLED_ROOT / "widget-builder" / "SKILL.md").read_text(encoding="utf-8")
    assert builder.startswith("---\nname: widget-builder\n")
    assert bundled_install.bundled_digest("widget-builder")


def test_a_missing_skill_is_installed_from_the_bundled_copy_for_every_present_agent(env):
    assert env.state()["state"] == STATE_AVAILABLE
    env.run_pass()
    rows = env.rows()
    assert [(r.item_id, r.scope, r.auto_update, r.source_index_url, r.consent_via) for r in rows if r.item_id == ITEM_ID] == [
        (ITEM_ID, "global", False, "bundled", "one_click")]
    assert (env.claude() / "SKILL.md").read_text(encoding="utf-8") == V1
    assert (env.codex() / "SKILL.md").read_text(encoding="utf-8") == V1
    state = env.state()
    assert (state["state"], state["local_edits"]) == (STATE_INSTALLED, False)


def test_a_second_pass_changes_nothing(env):
    env.run_pass()
    before = (env.claude() / "SKILL.md").stat().st_mtime_ns
    env.run_pass()
    assert len(env.rows()) == 1
    assert (env.claude() / "SKILL.md").stat().st_mtime_ns == before


def test_a_pristine_copy_is_updated_when_the_bundled_text_changes(env):
    env.run_pass()
    old = env.rows()[0]
    env.write_bundled(V2)
    env.run_pass()
    row = env.rows()[0]
    assert (env.claude() / "SKILL.md").read_text(encoding="utf-8") == V2
    assert (env.codex() / "SKILL.md").read_text(encoding="utf-8") == V2
    assert row.digest == bundled_install.bundled_digest("huddle") != old.digest
    assert row.install_id == old.install_id and row.revision == old.revision + 1
    trash = list((env.roots.home / ".claude" / ".carnivore-trash").glob("huddle-*"))
    assert len(trash) == 1 and (trash[0] / "SKILL.md").read_text(encoding="utf-8") == V1
    assert env.state()["local_edits"] is False


def test_a_locally_edited_copy_is_never_overwritten_and_says_so(env):
    env.run_pass()
    (env.claude() / "SKILL.md").write_text(V1 + "my own rule\n", encoding="utf-8")
    env.write_bundled(V2)
    env.run_pass()
    assert (env.claude() / "SKILL.md").read_text(encoding="utf-8") == V1 + "my own rule\n"
    assert (env.codex() / "SKILL.md").read_text(encoding="utf-8") == V1
    state = env.state()
    assert (state["state"], state["local_edits"]) == (STATE_INSTALLED, True)
    assert env.rows()[0].digest != bundled_install.bundled_digest("huddle")


def test_a_removed_skill_is_not_reinstalled_and_the_offer_brings_it_back(env):
    env.run_pass()
    install_id = env.rows()[0].install_id
    assert env.client.delete(f"/catalog/installed/{install_id}").status_code == 200
    assert not env.claude().exists()
    env.run_pass()
    assert env.rows() == [] and not env.claude().exists()
    assert env.state()["state"] == STATE_DECLINED
    offer = env.client.post(f"/catalog/required-skills/{ITEM_ID}/install")
    assert offer.status_code == 200, offer.text
    assert (env.claude() / "SKILL.md").read_text(encoding="utf-8") == V1
    assert env.state()["state"] == STATE_INSTALLED
    env.run_pass()
    assert len(env.rows()) == 1


def test_a_folder_the_person_owns_is_left_alone_and_reported_blocked(env):
    mine = env.claude()
    mine.mkdir()
    (mine / "SKILL.md").write_text("my huddle skill\n", encoding="utf-8")
    env.run_pass()
    assert (mine / "SKILL.md").read_text(encoding="utf-8") == "my huddle skill\n"
    rows = env.rows()
    assert [r.item_id for r in rows] == [ITEM_ID]
    with env.services.catalog.ledger() as ledger:
        assert [t.harness for t in ledger.targets(rows[0].install_id)] == ["codex"]


def test_an_only_blocked_install_writes_nothing(env):
    for folder in (env.claude(), env.codex()):
        folder.mkdir()
        (folder / "SKILL.md").write_text("mine\n", encoding="utf-8")
    assert env.state()["state"] == STATE_BLOCKED
    env.run_pass()
    assert env.rows() == []
    assert (env.codex() / "SKILL.md").read_text(encoding="utf-8") == "mine\n"


def test_a_byte_identical_folder_is_adopted_not_rewritten(env):
    for folder in (env.claude(), env.codex()):
        folder.mkdir()
        (folder / "SKILL.md").write_text(V1, encoding="utf-8")
    env.run_pass()
    rows = env.rows()
    assert len(rows) == 1 and rows[0].digest == bundled_install.bundled_digest("huddle")
    assert (env.claude() / "SKILL.md").read_text(encoding="utf-8") == V1
    assert env.state()["local_edits"] is False
    assert not (env.roots.home / ".claude" / ".carnivore-trash").exists()


def test_no_agent_present_installs_nothing(env, tmp_path):
    for home in (env.roots.home / ".claude", env.roots.home / ".codex"):
        import shutil
        shutil.rmtree(home)
    env.run_pass()
    assert env.rows() == []
    assert env.state()["state"] == STATE_BLOCKED


def test_widget_builder_is_bundled_and_offered_not_installed_by_the_boot_pass(env):
    assert next(s for s in REQUIRED_SKILLS if s.item_id == WB_ID).required is False
    assert env.entry(WB_ID) == {"item_id": WB_ID, "required": False, "state": STATE_AVAILABLE,
                                "install_id": None, "local_edits": None}
    env.run_pass()
    assert [r.item_id for r in env.rows()] == [ITEM_ID]
    assert not (env.roots.claude_skills() / "widget-builder").exists()
    assert env.entry(WB_ID)["state"] == STATE_AVAILABLE


def test_widget_builder_offer_installs_it_and_a_removal_is_never_reinstalled(env):
    wb_claude = env.roots.claude_skills() / "widget-builder"
    offer = env.client.post(f"/catalog/required-skills/{WB_ID}/install")
    assert offer.status_code == 200, offer.text
    assert (wb_claude / "SKILL.md").read_text(encoding="utf-8") == WB
    assert (env.roots.codex_skills() / "widget-builder" / "SKILL.md").read_text(encoding="utf-8") == WB
    assert env.entry(WB_ID)["state"] == STATE_INSTALLED
    install_id = env.entry(WB_ID)["install_id"]
    assert env.client.delete(f"/catalog/installed/{install_id}").status_code == 200
    assert not wb_claude.exists()
    env.run_pass()
    assert not wb_claude.exists()
    assert env.entry(WB_ID)["state"] == STATE_DECLINED
    assert env.client.post(f"/catalog/required-skills/{WB_ID}/install").status_code == 200
    assert (wb_claude / "SKILL.md").exists()


def test_an_installed_widget_builder_is_refreshed_while_pristine(env):
    assert env.client.post(f"/catalog/required-skills/{WB_ID}/install").status_code == 200
    newer = WB + "one more rule\n"
    (env.bundled / "widget-builder" / "SKILL.md").write_text(newer, encoding="utf-8")
    env.run_pass()
    assert (env.roots.claude_skills() / "widget-builder" / "SKILL.md").read_text(encoding="utf-8") == newer
