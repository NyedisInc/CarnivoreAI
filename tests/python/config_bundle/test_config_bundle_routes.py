
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_cfgb_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_cfgb_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import config_bundle_routes
from src.api.auth import require_auth
from src.core.config_migration import CURRENT_CONFIG_VERSION
from src.core.sessions.theme_store import ThemeStore
from src.core.ui_preferences_store import UiPreferencesStore

NAMED = "CANARY-named-secret-7f3a9c1e"
WEBHOOK = "CANARY-webhook-2b8d4e6a"
SHAPED = "sk-" + "ant-api03-" + "Q7xR2mLp9VdT4hWk8ZbN3cYf6JgS1aEu5oXi"
WRAPPER_ENV_CANARY = "canary-env-value-for-the-wrapper"
LOCAL_HOOK = "LOCAL-hook-must-survive-55aa"
ALL_CANARIES = (NAMED, WEBHOOK, SHAPED, WRAPPER_ENV_CANARY)


def _doc(*, uploads_ttl: int, theme: str, hook: str, pin_theme_pref: str) -> dict:
    return {
        "config_version": CURRENT_CONFIG_VERSION,
        "totp_secret": NAMED,
        "jwt_secret": NAMED,
        "refresh_token_ttl_seconds": 604800,
        "uploads": {"enabled": True, "ttl_seconds": uploads_ttl},
        "notifications": {
            "enabled": True,
            "slack_webhook_url": hook,
            "pushover_token": NAMED,
            "pushover_user_key": NAMED,
            "ntfy_topic": NAMED,
            "idle_threshold_seconds": 45,
        },
        "agents": {
            "wrappers": [
                {
                    "id": "claude-main",
                    "family": "claude",
                    "label": "main",
                    "script": 'claude "$@"',
                    "default": True,
                    "env": {"ANTHROPIC_API_KEY": WRAPPER_ENV_CANARY, "EDITOR": "vim"},
                    "note": SHAPED,
                }
            ]
        },
        "ui_preferences": {
            "schema_version": 1,
            "revision": 3,
            "values": {"theme": theme, "sidebar_density": pin_theme_pref},
        },
    }


class _Manager:
    async def broadcast(self, message: str) -> None:
        self.last = json.loads(message)


def _make(tmp_path: Path, monkeypatch, name: str, doc: dict, pins: dict, authed: bool = True):
    home = tmp_path / name
    home.mkdir()
    cfg = home / "config.json"
    cfg.write_text(json.dumps(doc, indent=2))
    themes = ThemeStore(pin_path=lambda: home / "pinned_themes.json")
    themes.pinned_themes.update(pins)
    app = FastAPI()
    app.include_router(config_bundle_routes.router, prefix="/api/v1")
    if authed:
        app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    app.state.services = SimpleNamespace(themes=themes)
    app.state.ui_preferences_store = UiPreferencesStore(lambda: cfg)
    app.state.connection_manager = _Manager()
    monkeypatch.setattr(config_bundle_routes, "_config_path", lambda: cfg)
    return TestClient(app), cfg, themes


@pytest.fixture
def source(tmp_path, monkeypatch):
    doc = _doc(uploads_ttl=111, theme="matrix", hook=WEBHOOK, pin_theme_pref="compact")
    return _make(tmp_path, monkeypatch, "src", doc, {"cloude_alpha": "matrix"})


def _export(client) -> dict:
    res = client.get("/api/v1/config/export")
    assert res.status_code == 200
    return res.json()


def test_export_never_contains_a_credential(source):
    client, _cfg, _themes = source
    res = client.get("/api/v1/config/export")
    assert res.status_code == 200
    text = res.text
    for canary in ALL_CANARIES:
        assert canary not in text
    body = res.json()
    assert "totp_secret" not in body["config"] and "jwt_secret" not in body["config"]
    assert "attachment" in res.headers["content-disposition"]
    redacted = set(body["redacted"])
    assert "config.notifications.slack_webhook_url" in redacted
    assert "config.agents.wrappers[0].env.ANTHROPIC_API_KEY" in redacted
    assert "config.agents.wrappers[0].note" in redacted
    assert body["config"]["uploads"]["ttl_seconds"] == 111
    assert body["config"]["refresh_token_ttl_seconds"] == 604800
    assert body["config"]["agents"]["wrappers"][0]["env"] == {"EDITOR": "vim"}
    assert body["ui_preferences"]["theme"] == "matrix"
    assert body["pinned_themes"] == {"cloude_alpha": "matrix"}
    assert body["kind"] == "carnivore-config-bundle" and body["config_version"] == CURRENT_CONFIG_VERSION


def test_export_requires_auth(tmp_path, monkeypatch):
    doc = _doc(uploads_ttl=1, theme="matrix", hook=WEBHOOK, pin_theme_pref="compact")
    client, _c, _t = _make(tmp_path, monkeypatch, "noauth", doc, {}, authed=False)
    assert client.get("/api/v1/config/export").status_code in (401, 403)
    assert client.post("/api/v1/config/import", json={"bundle": {}}).status_code in (401, 403)


def test_round_trip_into_a_fresh_install_keeps_its_own_credentials(source, tmp_path, monkeypatch):
    client, _cfg, _themes = source
    bundle = _export(client)

    other = _doc(uploads_ttl=5, theme="default", hook=LOCAL_HOOK, pin_theme_pref="cozy")
    c2, cfg2, themes2 = _make(tmp_path, monkeypatch, "dst", other, {"cloude_zed": "default"})
    res = c2.post("/api/v1/config/import", json={"bundle": bundle, "mode": "merge", "dry_run": False})
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "applied"

    doc = json.loads(cfg2.read_text())
    assert doc["uploads"]["ttl_seconds"] == 111
    assert doc["ui_preferences"]["values"]["theme"] == "matrix"
    assert doc["ui_preferences"]["values"]["sidebar_density"] == "compact"
    assert themes2.pinned_themes == {"cloude_alpha": "matrix", "cloude_zed": "default"}
    assert doc["notifications"]["slack_webhook_url"] == LOCAL_HOOK
    assert doc["totp_secret"] == NAMED
    assert doc["agents"]["wrappers"][0]["env"]["ANTHROPIC_API_KEY"] == WRAPPER_ENV_CANARY
    assert (cfg2.parent / "config.json.bak").exists()
    again = c2.post("/api/v1/config/import", json={"bundle": bundle, "dry_run": False})
    assert again.json()["status"] == "unchanged"

    rep = c2.post("/api/v1/config/import", json={"bundle": bundle, "mode": "replace", "dry_run": False})
    assert rep.status_code == 200
    assert themes2.pinned_themes == {"cloude_alpha": "matrix"}
    assert json.loads(cfg2.read_text())["notifications"]["slack_webhook_url"] == LOCAL_HOOK


def test_dry_run_previews_and_writes_nothing(source, tmp_path, monkeypatch):
    client, _cfg, _themes = source
    bundle = _export(client)
    other = _doc(uploads_ttl=5, theme="default", hook=LOCAL_HOOK, pin_theme_pref="cozy")
    c2, cfg2, themes2 = _make(tmp_path, monkeypatch, "dst", other, {"cloude_zed": "default"})
    before = cfg2.read_bytes()

    res = c2.post("/api/v1/config/import", json={"bundle": bundle})
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "preview" and body["dry_run"] is True
    paths = {c["path"]: c for c in body["changes"]}
    assert paths["config.uploads.ttl_seconds"]["kind"] == "changed"
    assert paths["config.uploads.ttl_seconds"]["before"] == "5"
    assert paths["config.uploads.ttl_seconds"]["after"] == "111"
    assert paths["pinned_themes.cloude_alpha"]["kind"] == "added"
    assert cfg2.read_bytes() == before
    assert not (cfg2.parent / "config.json.bak").exists()
    assert themes2.pinned_themes == {"cloude_zed": "default"}
    assert not (cfg2.parent / "pinned_themes.json").exists()
    real = c2.post("/api/v1/config/import", json={"bundle": bundle, "dry_run": False})
    assert real.status_code == 200 and cfg2.read_bytes() != before
    for canary in ALL_CANARIES:
        assert canary not in res.text and canary not in real.text


@pytest.mark.parametrize(
    "mutate",
    [
        lambda b: b.update(kind="something-else"),
        lambda b: b.update(surprise=1),
        lambda b: b.update(schema_version=99),
        lambda b: b.update(config_version=CURRENT_CONFIG_VERSION + 1),
        lambda b: b["config"]["uploads"].update(ttl_seconds="not a number"),
        lambda b: b["ui_preferences"].update(sidebar_density="enormous"),
    ],
)
def test_invalid_file_is_rejected_and_nothing_is_written(source, tmp_path, monkeypatch, mutate):
    client, _cfg, _themes = source
    bundle = _export(client)
    mutate(bundle)
    other = _doc(uploads_ttl=5, theme="default", hook=LOCAL_HOOK, pin_theme_pref="cozy")
    c2, cfg2, themes2 = _make(tmp_path, monkeypatch, "dst", other, {})
    before = cfg2.read_bytes()
    res = c2.post("/api/v1/config/import", json={"bundle": bundle, "dry_run": False})
    assert res.status_code == 422
    assert cfg2.read_bytes() == before
    assert not (cfg2.parent / "config.json.bak").exists()
    assert themes2.pinned_themes == {}


def test_a_hand_edited_bundle_cannot_write_a_credential(source, tmp_path, monkeypatch):
    client, _cfg, _themes = source
    bundle = _export(client)
    bundle["config"]["notifications"]["pushover_token"] = NAMED
    bundle["config"]["notifications"]["idle_threshold_seconds"] = 77
    bundle["config"]["totp_secret"] = NAMED
    bundle["config"]["agents"]["wrappers"][0]["note"] = SHAPED
    bundle["ui_preferences"]["claude_refresh_token"] = NAMED
    bundle["ui_preferences"]["theme_script_consent"] = {"matrix": True}
    other = _doc(uploads_ttl=5, theme="default", hook=LOCAL_HOOK, pin_theme_pref="cozy")
    other["notifications"]["pushover_token"] = "LOCAL-pushover"
    c2, cfg2, _t = _make(tmp_path, monkeypatch, "dst", other, {})
    res = c2.post("/api/v1/config/import", json={"bundle": bundle, "dry_run": False})
    assert res.status_code == 200, res.text
    body = res.json()
    assert "config.notifications.pushover_token" in body["stripped"]
    assert "config.totp_secret" not in body["stripped"] and "totp_secret" in body["ignored"]
    written = cfg2.read_text()
    assert SHAPED not in written and "claude_refresh_token" not in written
    assert "theme_script_consent" not in written
    doc = json.loads(written)
    assert doc["notifications"]["pushover_token"] == "LOCAL-pushover"
    assert doc["notifications"]["idle_threshold_seconds"] == 77
    assert doc["totp_secret"] == NAMED
    assert NAMED not in res.text and SHAPED not in res.text


def test_an_older_config_version_is_migrated_on_import(source, tmp_path, monkeypatch):
    client, _cfg, _themes = source
    bundle = _export(client)
    bundle["config_version"] = 5
    bundle["config"]["agents"] = {"wrappers": [], "codex_command": "codex --yolo-import-canary"}
    other = _doc(uploads_ttl=5, theme="default", hook=LOCAL_HOOK, pin_theme_pref="cozy")
    other["agents"] = {"wrappers": []}
    c2, cfg2, _t = _make(tmp_path, monkeypatch, "dst", other, {})
    preview = c2.post("/api/v1/config/import", json={"bundle": bundle, "mode": "replace"}).json()
    assert c2.post("/api/v1/config/import", json={"bundle": bundle, "mode": "replace", "dry_run": False}).status_code == 409
    res = c2.post("/api/v1/config/import", json={"bundle": bundle, "mode": "replace", "dry_run": False,
                                                 "confirm_launch_profiles_sha256": preview["launch_profiles"]["sha256"]})
    assert res.status_code == 200, res.text
    scripts = [w.get("script", "") for w in json.loads(cfg2.read_text())["agents"]["wrappers"]]
    assert any("yolo-import-canary" in s for s in scripts)
