
from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
import time
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_pk_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_pk_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.api import catalog_publish_routes
from src.core.catalog.token_store import CatalogSession, open_token_store
from tests.helpers.hosted_routes_app import hosted_proxy_app, route_responder

THEME_JSON = json.dumps({"id": "night-ops", "name": "night ops", "cssVars": {"--color-bg": "#0a0f0c"},
                         "background": {"image": "background.webp"}})
PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 64
SUBMITTED = {"submission_id": "abc", "status": "pending", "item_id": "bob/night-ops", "version": "1.0.0"}


def loc(kind: str, folder: Path) -> dict:
    return {"location_id": f"{kind}:{folder.name}", "kind": kind, "name": folder.name, "harness": "",
            "scope": "personal", "path": str(folder), "description": "", "description_tokens_est": 0,
            "is_symlink": False, "read_only": False, "plugin": None, "managed": None}


def make_theme(tmp_path: Path) -> Path:
    folder = tmp_path / "themes" / "night-ops"
    folder.mkdir(parents=True)
    (folder / "theme.json").write_text(THEME_JSON)
    (folder / "background.webp").write_bytes(PNG)
    return folder


def make_plugin(tmp_path: Path, hooks: bool) -> Path:
    folder = tmp_path / "plugins" / "helper"
    (folder / ".claude-plugin").mkdir(parents=True)
    (folder / ".claude-plugin" / "plugin.json").write_text('{"name": "helper", "version": "1.0.0"}')
    (folder / "commands").mkdir()
    (folder / "commands" / "go.md").write_text("# go\n\ndo it plainly.\n")
    if hooks:
        (folder / "hooks").mkdir()
        (folder / "hooks" / "hooks.json").write_text("{}")
    return folder


def sign_in(state: Path) -> None:
    now = int(time.time())
    with open_token_store(state) as store:
        store.save(CatalogSession(login="bob", access_token="HELD-ACCESS", access_expires_at=now + 3600,
                                  refresh_token="HELD-REFRESH", refresh_expires_at=now + 86400))


@pytest.fixture
def scan(monkeypatch):
    box: dict = {"locs": []}

    async def own(_request):
        return list(box["locs"])

    monkeypatch.setattr(catalog_publish_routes, "_own_locations", own)
    return box


def send(app, location: dict):
    body = {"location": location["location_id"], "version": "1.0.0"}
    shown = app.client.post("/catalog/publish/preview", json=body)
    digest = shown.json().get("digest", "0" * 64)
    return shown, app.client.post("/catalog/submissions", json={**body, "digest": digest})


def test_a_theme_is_relayed_with_its_kind_and_its_files(tmp_path, scan):
    folder = make_theme(tmp_path)
    scan["locs"] = [loc("theme", folder)]
    with hosted_proxy_app(tmp_path, responder=route_responder({"/submissions": (201, SUBMITTED)}),
                          include_aggregator=True) as app:
        sign_in(app.state)
        shown, sent = send(app, scan["locs"][0])
        assert shown.json()["kind"] == "theme" and shown.json()["can_send"] is True, shown.text
        assert sent.status_code == 200, sent.text
        body = json.loads(app.sent[-1].content)
        assert body["kind"] == "theme"
        files = {f["path"]: base64.b64decode(f["content_base64"]) for f in body["files"]}
        assert files == {"theme.json": THEME_JSON.encode(), "background.webp": PNG}


def test_a_plugin_with_hooks_is_refused_locally_before_any_outbound_request(tmp_path, scan):
    folder = make_plugin(tmp_path, hooks=True)
    scan["locs"] = [loc("plugin", folder)]
    with hosted_proxy_app(tmp_path, responder=route_responder({"/submissions": (201, SUBMITTED)}),
                          include_aggregator=True) as app:
        sign_in(app.state)
        shown, sent = send(app, scan["locs"][0])
        refusal = shown.json()["refusals"]
        assert shown.json()["can_send"] is False
        assert any(r["code"] == "plugin_not_safe" and r["path"] == "hooks/hooks.json" for r in refusal), refusal
        assert sent.status_code == 409 and sent.json()["detail"]["code"] == "folder_refused"
        assert app.sent == [], "nothing may leave the Mac for an unsafe plugin"


def test_a_clean_plugin_relays_and_a_theme_with_effects_is_refused_locally(tmp_path, scan):
    plugin = make_plugin(tmp_path, hooks=False)
    scan["locs"] = [loc("plugin", plugin)]
    with hosted_proxy_app(tmp_path, responder=route_responder({"/submissions": (201, SUBMITTED)}),
                          include_aggregator=True) as app:
        sign_in(app.state)
        _, sent = send(app, scan["locs"][0])
        assert sent.status_code == 200 and json.loads(app.sent[-1].content)["kind"] == "plugin"
    theme = make_theme(tmp_path)
    (theme / "effects.js").write_text("alert(1)")
    scan["locs"] = [loc("theme", theme)]
    with hosted_proxy_app(tmp_path, responder=route_responder({}), include_aggregator=True) as app:
        sign_in(app.state)
        shown, _ = send(app, scan["locs"][0])
        assert any(r["code"] == "scripts_not_supported" and r["path"] == "effects.js"
                   for r in shown.json()["refusals"])
        assert app.sent == []


def test_a_hosted_409_passes_through_with_its_paths(tmp_path, scan):
    folder = make_theme(tmp_path)
    scan["locs"] = [loc("theme", folder)]
    hosted = {"code": "plugin_not_safe", "detail": "a plugin may not carry: hooks/hooks.json (path not allowed)"}
    with hosted_proxy_app(tmp_path, responder=route_responder({"/submissions": (409, hosted)}),
                          include_aggregator=True) as app:
        sign_in(app.state)
        _, sent = send(app, scan["locs"][0])
        assert sent.status_code == 409
        assert sent.json()["detail"] == hosted


@pytest.mark.parametrize("extra", [".env", "lib/run.py", "data/blob.bin"])
def test_an_unlisted_plugin_path_is_refused_locally_before_any_outbound_request(tmp_path, scan, extra):
    folder = make_plugin(tmp_path, hooks=False)
    target = folder / extra
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("X=1\n")
    scan["locs"] = [loc("plugin", folder)]
    with hosted_proxy_app(tmp_path, responder=route_responder({"/submissions": (201, SUBMITTED)}),
                          include_aggregator=True) as app:
        sign_in(app.state)
        shown, sent = send(app, scan["locs"][0])
        assert shown.json()["can_send"] is False
        assert any(r["code"] == "plugin_not_safe" and r["path"] == extra for r in shown.json()["refusals"]), shown.text
        assert sent.status_code == 409 and sent.json()["detail"]["code"] == "folder_refused"
        assert app.sent == []
