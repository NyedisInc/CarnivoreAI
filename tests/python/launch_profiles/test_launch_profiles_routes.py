
from __future__ import annotations

import os
import stat
import sys
import tempfile
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Tuple

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_lp_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_lp_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import ai_routes, launch_profiles_routes
from src.api.auth import require_auth
from src.core import blueprints_store, config_writer, session_change_notice
from src.core.byoai import gateway as gateway_module
from src.core.byoai.calllog import CallLog
from src.core.byoai.gateway import Gateway
from src.core.byoai.keys import KeyStore
from src.core.byoai.store import ByoaiStore
from src.core.config_migration import CURRENT_CONFIG_VERSION
from src.core.config_bundle import service as bundle_service
from src.core.config_bundle.bundle import ConfigBundle, build_export
from src.core.config_bundle.importer import ImportRefused
from src.core.db import connect
from src.core.launch_profiles import check as check_module
from src.models.blueprints import BlueprintSpec
from tests.layouts_helpers import migrated
from tests.lifecycle_helpers import add_row


def profile(pid: str, harness: str = "claude", **extra: Any) -> Dict[str, Any]:
    return {"id": pid, "harness": harness, "label": pid, **extra}


class GuardedKeychain:

    def __init__(self) -> None:
        self.items: Dict[Tuple[str, str], str] = {}
        self.armed = False

    def _guard(self) -> None:
        if self.armed:
            raise AssertionError("the Keychain was touched")

    def state(self, service: str, account: str) -> str:
        self._guard()
        return "ok" if (service, account) in self.items else "absent"

    def read(self, service: str, account: str) -> Any:
        self._guard()
        return self.items.get((service, account))

    def write(self, service: str, account: str, secret: str) -> None:
        self._guard()
        self.items[(service, account)] = secret

    def delete(self, service: str, account: str) -> bool:
        self._guard()
        return self.items.pop((service, account), None) is not None


@pytest.fixture
def env(tmp_path, monkeypatch):
    from src.config import settings

    state = tmp_path / "state"
    db = migrated(state)
    config = tmp_path / "config.json"
    config.write_text("{}")
    config_writer.commit(config, lambda d: {**d, "config_version": CURRENT_CONFIG_VERSION, "launch_profiles": {"revision": 1, "profiles": [
        profile("claude-main", default=True), profile("claude-gone"), profile("claude-spare"),
        profile("codex-yolo", "codex", default=True, permissions="skip_all"),
    ]}})
    keychain = GuardedKeychain()
    keys = KeyStore(backend=keychain)
    gateway_module.set_gateway(Gateway(ByoaiStore(config, keys=keys), CallLog(tmp_path), keys))
    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: state, raising=True)
    monkeypatch.setattr(settings, "auth_config_file", str(config))
    monkeypatch.setattr(type(settings), "load_auth_config",
                        lambda self: SimpleNamespace(byoai=gateway_module.get_gateway().store.read()), raising=True)
    monkeypatch.setattr(session_change_notice, "publish", lambda *_a: 0)
    app = FastAPI()
    app.dependency_overrides[require_auth] = lambda: True
    app.include_router(launch_profiles_routes.router, prefix="/api/v1")
    app.include_router(ai_routes.router, prefix="/api/v1")
    yield SimpleNamespace(client=TestClient(app), db=db, state=state, config=config, tmp=tmp_path, keychain=keychain)
    gateway_module.set_gateway(None)


def reference(env: SimpleNamespace, kind: str, pid: str) -> None:
    with closing(connect(env.db, create=False)) as conn:
        if kind == "sessions":
            row = add_row(conn, uuid="u-asleep", name="cloude_asleep", epoch=1, lifecycle="stopped")
            conn.execute("UPDATE sessions SET agent_type = ?, agent_family = 'claude' WHERE id = ?", (pid, row))
        elif kind == "project_defaults":
            conn.execute("INSERT INTO projects (root, raw_path, display_name, default_agent_type, source, created_at, updated_at) "
                         "VALUES ('/p', '/p', 'p', ?, 'test', 't', 't')", (pid,))
        else:
            spec = BlueprintSpec.model_validate({"name": "team", "sessions": [
                {"label": "a", "family": pid, "folder": {"mode": "existing", "path": str(env.tmp)}}]})
            blueprints_store.create_blueprint(conn, spec)
        conn.commit()


@pytest.mark.parametrize("kind", ["sessions", "blueprint_members", "project_defaults"])
def test_delete_is_refused_while_referenced_then_allowed_after_a_move(env, kind):
    c = env.client
    assert c.delete("/api/v1/launch-profiles/claude-spare").status_code == 200
    reference(env, kind, "claude-gone")
    refused = c.delete("/api/v1/launch-profiles/claude-gone")
    assert refused.status_code == 409
    detail = refused.json()["detail"]
    assert detail["code"] == "in_use" and detail["counts"][kind] == 1 and sum(detail["counts"].values()) == 1
    assert c.get("/api/v1/launch-profiles/claude-gone/usage").json()["total"] == 1
    assert c.post("/api/v1/launch-profiles/claude-gone/move-references", json={"to": "codex-yolo"}).status_code == 409
    moved = c.post("/api/v1/launch-profiles/claude-gone/move-references", json={"to": "claude-main"})
    assert moved.status_code == 200 and moved.json()["moved"][kind] == 1
    assert c.get("/api/v1/launch-profiles/claude-main/usage").json()["counts"][kind] == 1
    assert c.delete("/api/v1/launch-profiles/claude-gone").status_code == 200


def test_a_default_cannot_be_deleted(env):
    refused = env.client.delete("/api/v1/launch-profiles/codex-yolo")
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "is_default"


def test_check_never_runs_before_launch_and_scrubs_the_environment(env, monkeypatch):
    marker = env.tmp / "before-launch-ran"
    fake = env.tmp / "fake-claude"
    fake.write_text("#!/bin/sh\necho \"version 9 key=${ANTHROPIC_API_KEY:-none} tok=${MY_SECRET_TOKEN:-none}\"\n")
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setattr(check_module, "harness_binary", lambda harness: str(fake))
    monkeypatch.setenv("MY_SECRET_TOKEN", "must-not-reach-the-child")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-reach-the-child")
    body = profile("claude-hook", before_launch=f"touch {marker}")
    assert env.client.post("/api/v1/launch-profiles", json={"profile": body}).status_code == 201
    result = env.client.post("/api/v1/launch-profiles/claude-hook/check").json()
    assert result["binary"]["status"] == "ok" and "version 9" in result["binary"]["output"]
    assert "key=none tok=none" in result["binary"]["output"]
    assert not marker.exists()
    preview = env.client.get("/api/v1/launch-profiles/claude-hook/preview").json()
    assert f"touch {marker}" in preview["command"]


def test_preview_never_touches_the_keychain(env):
    c = env.client
    made = c.post("/api/v1/ai/connections", json={"preset": "custom", "base_url": "https://anth.test", "key": "q" * 20 + "WXYZ",
                                                  "options": {"protocol": "anthropic_messages", "auth": "bearer", "capabilities": ["chat"]}})
    assert made.status_code == 201, made.text
    cid = made.json()["connection"]["id"]
    env.keychain.armed = True
    body = profile("claude-routed", endpoint={"mode": "connection", "connection_id": cid},
                   model={"mode": "fixed", "value": "m-1"}, secrets=[{"name": "EXTRA_API_KEY", "keychain_ref": "item-1"}])
    assert c.post("/api/v1/launch-profiles", json={"profile": body}).status_code == 201
    out = c.get("/api/v1/launch-profiles/claude-routed/preview")
    assert out.status_code == 200, out.text
    data = out.json()
    names = {s["name"]: s for s in data["secrets"]}
    assert names["EXTRA_API_KEY"]["keychain_ref"] == "item-1" and names["ANTHROPIC_AUTH_TOKEN"]["key_hint"] == "WXYZ"
    assert "q" * 20 not in out.text
    codex = c.get("/api/v1/launch-profiles/codex-yolo/preview")
    assert codex.status_code == 200 and "--yolo" in codex.json()["command"]


def test_draft_preview_renders_an_unsaved_profile_and_writes_nothing(env):
    c = env.client
    before = c.get("/api/v1/launch-profiles").json()
    draft = profile("claude-draft", permissions="skip_all")
    out = c.post("/api/v1/launch-profiles/preview", json={"profile": draft})
    assert out.status_code == 200, out.text
    assert "--dangerously-skip-permissions" in out.json()["command"]
    assert c.get("/api/v1/launch-profiles/claude-draft/preview").status_code == 404
    assert c.get("/api/v1/launch-profiles").json() == before
    refused = c.post("/api/v1/launch-profiles/preview", json={"profile": profile("shell-draft", harness="shell", permissions="skip_all")})
    assert refused.status_code == 422, refused.text


def test_import_refuses_a_bad_digest_and_never_makes_a_default(env):
    c = env.client
    doc = c.get("/api/v1/launch-profiles/claude-main/export").json()
    assert doc["format"] == "carnivore.launch_profile/1"
    doc["profile"]["id"] = "claude-shared"
    doc["profile"]["before_launch"] = "echo hi"
    tampered = c.post("/api/v1/launch-profiles/import/preview", json={"document": doc})
    assert tampered.status_code == 422
    del doc["sha256"]
    preview = c.post("/api/v1/launch-profiles/import/preview", json={"document": doc}).json()
    assert preview["exists"] is False and {"kind": "before_launch", "text": "echo hi"} in preview["parts"]
    wrong = c.post("/api/v1/launch-profiles/import", json={"document": doc, "confirm_sha256": "0" * 64})
    assert wrong.status_code == 409 and wrong.json()["detail"]["code"] == "digest_mismatch"
    assert c.get("/api/v1/launch-profiles/claude-shared").status_code == 404
    written = c.post("/api/v1/launch-profiles/import", json={"document": doc, "confirm_sha256": preview["sha256"]})
    assert written.status_code == 200 and written.json()["profile"]["default"] is False
    again = c.post("/api/v1/launch-profiles/import", json={"document": doc, "confirm_sha256": preview["sha256"]})
    assert again.status_code == 409 and again.json()["detail"]["code"] == "exists"


def test_settings_bundle_import_needs_the_launch_profiles_digest(env):
    exported = build_export(config_writer.read_config(env.config), {}, app_version="1", host="a")
    exported["config"]["launch_profiles"]["profiles"].append(profile("claude-bundled", before_launch="echo hi"))
    bundle = ConfigBundle.model_validate(exported)
    args: Dict[str, Any] = dict(mode="merge", pins={}, themes=None, host="b")
    body, _ = bundle_service.run_import(env.config, bundle, dry_run=True, **args)
    digest = body["launch_profiles"]["sha256"]
    assert any(p["id"] == "claude-bundled" for p in body["launch_profiles"]["profiles"])
    with pytest.raises(ImportRefused) as refused:
        bundle_service.run_import(env.config, bundle, dry_run=False, **args)
    assert refused.value.status_code == 409
    assert "claude-bundled" not in config_writer.read_config(env.config)["launch_profiles"]["profiles"].__repr__()
    applied, _ = bundle_service.run_import(env.config, bundle, dry_run=False, confirm_launch_profiles_sha256=digest, **args)
    assert applied["status"] == "applied"
    ids = [p["id"] for p in config_writer.read_config(env.config)["launch_profiles"]["profiles"]]
    assert "claude-bundled" in ids and "claude-gone" in ids


def test_byoai_connection_delete_is_refused_while_a_profile_uses_it(env):
    c = env.client
    made = c.post("/api/v1/ai/connections", json={"preset": "custom", "base_url": "https://anth.test", "key": "q" * 20 + "WXYZ",
                                                  "options": {"protocol": "anthropic_messages", "auth": "bearer", "capabilities": ["chat"]}})
    cid = made.json()["connection"]["id"]
    body = profile("claude-routed", endpoint={"mode": "connection", "connection_id": cid}, model={"mode": "fixed", "value": "m-1"})
    assert c.post("/api/v1/launch-profiles", json={"profile": body}).status_code == 201
    refused = c.delete(f"/api/v1/ai/connections/{cid}")
    assert refused.status_code == 409
    assert refused.json()["detail"]["profiles"] == [{"id": "claude-routed", "label": "claude-routed"}]
    assert c.delete("/api/v1/launch-profiles/claude-routed").status_code == 200
    assert c.delete(f"/api/v1/ai/connections/{cid}").status_code == 200
