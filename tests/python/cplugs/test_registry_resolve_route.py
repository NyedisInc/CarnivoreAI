
from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.plugins.host import registry_boot, registry_files, registry_routes, runtime
from src.plugins.host.peer_refusal import refuse_peer_token_writes
from tests.python.cplugs import registry_world as W
from tests.python.cplugs.test_registry_boot_tiebreaks import migrated, set_marker
from tests.python.cplugs.test_registry_migration_full_tuple import Alerts, boot


def client(state, monkeypatch) -> TestClient:
    app = FastAPI()
    app.include_router(registry_routes.router)
    app.dependency_overrides[require_auth] = lambda: None
    app.dependency_overrides[refuse_peer_token_writes] = lambda: None
    monkeypatch.setattr(runtime, "host_for", lambda _app: SimpleNamespace(state_dir=state))
    return TestClient(app)


def test_keep_lifts_read_only_and_the_registry_is_writable_again(tmp_path, monkeypatch):
    w = migrated(tmp_path)
    set_marker(w.state, registry_files.read_generation(w.state) + 4)
    boot(w.state, Alerts())
    assert registry_files.read_only_reason(w.state) == "older_copy"
    reply = client(w.state, monkeypatch).put("/cplug-owner/registry/resolve", json={"choice": "keep"})
    assert reply.status_code == 200 and reply.json() == {"ok": True}
    assert registry_files.read_only_reason(w.state) is None


def test_backup_with_no_readable_copy_answers_409_and_stays_read_only(tmp_path, monkeypatch):
    w = migrated(tmp_path)
    set_marker(w.state, registry_files.read_generation(w.state) + 4)
    boot(w.state, Alerts())
    for folder in registry_files.cplugs_dir(w.state).glob("migration-backup-*"):
        (folder / "state.json").write_text("{ torn")
    registry_files.registry_path(w.state).with_suffix(".json.bak").unlink(missing_ok=True)
    reply = client(w.state, monkeypatch).put("/cplug-owner/registry/resolve", json={"choice": "backup"})
    assert reply.status_code == 409 and reply.json()["detail"]["code"] == "no_readable_copy"
    assert registry_files.read_only_reason(w.state) == "older_copy"
    registry_files.clear_read_only(w.state)


def test_an_unknown_choice_is_refused(tmp_path, monkeypatch):
    w = W.support(tmp_path, "empty")
    assert client(w.state, monkeypatch).put("/cplug-owner/registry/resolve", json={"choice": "wipe"}).status_code == 422
    assert registry_boot.CHOICE_KEEP == "keep"
