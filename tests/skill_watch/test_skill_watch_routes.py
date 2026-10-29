
from __future__ import annotations

import pytest

from src.api import skill_watch_routes
from src.core.skill_watch import sentinel
from tests.helpers.catalog_app import catalog_app, ledger_rows
from tests.helpers.minisign_keys import SKIP_REASON, minisign_binary
from tests.test_catalog_installed_routes import (  # noqa: F401
    ITEM_ID, NAME, install, keys, publish_first, refusal, served,
)

pytestmark = pytest.mark.skipif(minisign_binary() is None, reason=SKIP_REASON)


def _isolate_state(monkeypatch, tmp_path) -> None:
    from src.config import settings

    monkeypatch.setenv("CLOUDE_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr(settings, "state_dir_override", str(tmp_path / "state"))


def _listed(app) -> dict:
    response = app.client.get("/catalog/installed")
    assert response.status_code == 200, response.text
    return response.json()["items"][0]


def test_drift_fork_restore_and_autopsy_over_a_real_install(tmp_path, served, keys, monkeypatch) -> None:
    _isolate_state(monkeypatch, tmp_path)
    monkeypatch.setattr(sentinel, "TTL_SECONDS", 0.0)
    trust = publish_first(tmp_path, served, keys)
    with catalog_app(tmp_path, served, trust_root=trust) as app:
        app.client.app.include_router(skill_watch_routes.router)
        row = install(app)
        assert _listed(app)["drift"]["state"] == "clean" and _listed(app)["forked"] is False

        skill_md = app.roots.claude_skills() / NAME / "SKILL.md"
        skill_md.write_text(skill_md.read_text() + "an edit\n")
        drift = _listed(app)["drift"]
        assert (drift["state"], drift["changed_files"]) == ("drifted", ["SKILL.md"])

        marked = app.client.put(f"/catalog/installed/{row['install_id']}/fork", json={"forked": True})
        assert marked.status_code == 200 and marked.json()["forked"] is True

        restored = app.client.post(f"/catalog/installed/{row['install_id']}/restore",
                                   json={"expected_revision": row["revision"]})
        assert restored.status_code == 200, restored.text
        assert restored.json()["drift"]["state"] == "clean" and restored.json()["forked"] is False
        assert "an edit" not in skill_md.read_text()
        assert ledger_rows(app)[0].version == row["version"]

        stale = app.client.post(f"/catalog/installed/{row['install_id']}/restore",
                                json={"expected_revision": 99})
        assert stale.status_code == 409
        assert app.client.get(f"/skills/{NAME}/autopsy?days=30").json()["state"] == "not_measured"


def _stray(app) -> list:
    root = app.roots.claude_skills()
    incoming = [p.name for p in root.iterdir() if "-carnivore-incoming-" in p.name]
    pending = app.roots.pending_dir()
    journals = sorted(p.name for p in pending.iterdir()) if pending.is_dir() else []
    return incoming + journals


def test_restore_refuses_a_revoked_recorded_version_and_writes_nothing(tmp_path, served, keys, monkeypatch) -> None:
    from src.core.catalog.index_state import RevocationStore
    from src.core.catalog.revocation import KIND_VERSION, RevocationRef, version_subject
    _isolate_state(monkeypatch, tmp_path)
    monkeypatch.setattr(sentinel, "TTL_SECONDS", 0.0)
    trust = publish_first(tmp_path, served, keys)
    with catalog_app(tmp_path, served, trust_root=trust) as app:
        app.client.app.include_router(skill_watch_routes.router)
        row = install(app)
        skill_md = app.roots.claude_skills() / NAME / "SKILL.md"
        skill_md.write_text(skill_md.read_text() + "an edit\n")
        cache = app.services.catalog.index_cache
        from contextlib import closing
        with closing(cache._open_db()) as conn:
            RevocationStore(conn).remember(cache.index_key_id, [
                RevocationRef(KIND_VERSION, version_subject(ITEM_ID, row["version"]), "2026-09-28T00:00:00Z")])
        before = skill_md.read_text()
        refused = app.client.post(f"/catalog/installed/{row['install_id']}/restore",
                                  json={"expected_revision": row["revision"]})
        assert refused.status_code == 409 and refusal(refused)["code"] == "version_revoked", refused.text
        assert skill_md.read_text() == before and _stray(app) == []


def test_restore_over_a_missing_folder_is_a_named_409_with_nothing_left_behind(tmp_path, served, keys, monkeypatch) -> None:
    import shutil
    _isolate_state(monkeypatch, tmp_path)
    monkeypatch.setattr(sentinel, "TTL_SECONDS", 0.0)
    trust = publish_first(tmp_path, served, keys)
    with catalog_app(tmp_path, served, trust_root=trust) as app:
        app.client.app.include_router(skill_watch_routes.router)
        row = install(app)
        shutil.rmtree(app.roots.claude_skills() / NAME)
        assert _listed(app)["drift"]["state"] == "missing"
        response = app.client.post(f"/catalog/installed/{row['install_id']}/restore",
                                   json={"expected_revision": row["revision"]})
        assert response.status_code == 409 and refusal(response)["code"] == "restore_missing", response.text
        assert not (app.roots.claude_skills() / NAME).exists() and _stray(app) == []
