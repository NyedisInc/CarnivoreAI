
from __future__ import annotations

import asyncio
import contextlib
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import httpx
import pytest
from fastapi.testclient import TestClient

from src.api import catalog_publish_routes, session_crud_routes
from src.config import settings
from src.core.catalog import archive_client, hosted_api
from src.core.catalog.index_refresher import IndexRefresher
from src.core.catalog.services import build_catalog_services
from src.core.catalog.token_store import CatalogSession, open_token_store
from src.core.composition import build_services
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.live_install_roots import LiveInstallRoots
from src.core.plugin_studio import dev_session
from src.core.ui_preferences_store import UiPreferencesStore
from src.plugins.host import developer_mode, dev_lease, dev_stream, runtime, sidecar_boot, sidecar_registry
from src.plugins.host import state as owner_state
from src.plugins.runtime import sandbox
from tests.helpers.catalog_app import StateOnlySettings
from tests.helpers.catalog_surface import INDEX_PATH, FrozenClock, fixture_trust_root, keypairs
from tests.helpers.static_http import self_signed_cert, serve_directory
from tests.python.api_keys.conftest import bearer, key_store, owner_jwt  # noqa: F401

SUBMISSION_ID = "ab" * 16


def _can_run_darwin_sandbox() -> bool:
    if sys.platform != "darwin" or not os.path.exists("/usr/bin/sandbox-exec"):
        return False
    try:
        sandbox.find_interpreter()
        return True
    except sandbox.SandboxUnavailable:
        return False


DARWIN_SANDBOX = _can_run_darwin_sandbox()


@pytest.fixture
def studio_world(tmp_path: Path, owner_jwt, key_store, monkeypatch: pytest.MonkeyPatch):  # noqa: F811
    from src.main import app

    @contextlib.asynccontextmanager
    async def _noop_lifespan(_app: Any):
        yield

    monkeypatch.setattr(app.router, "lifespan_context", _noop_lifespan)
    state = tmp_path / "state"
    state.mkdir(parents=True, exist_ok=True)
    ensure_db_migrated(state, 4, "0.8.2")

    published_topics: List[str] = []
    launched_sessions: List[Dict[str, Any]] = []
    dev_mode_flag = {"on": True}
    launch_profiles: List[Dict[str, Any]] = []

    config_path = tmp_path / "config.json"
    config_path.write_text("{}\n", encoding="utf-8")
    prefs = UiPreferencesStore(lambda: config_path)

    sent_hosted: List[httpx.Request] = []

    def _hosted_handler(request: httpx.Request) -> httpx.Response:
        sent_hosted.append(request)
        path = request.url.path
        if request.method == "GET" and path.endswith("/me"):
            return httpx.Response(
                200,
                json={"provider": "github", "login": "alice", "handle": "alice", "handle_status": "approved", "registered": True},
            )
        if request.method == "POST" and path.endswith("/submissions"):
            return httpx.Response(
                201,
                json={"submission_id": SUBMISSION_ID, "status": "pending", "item_id": "alice/studiotest", "version": "0.1.0"},
            )
        return httpx.Response(404, json={"detail": f"unhandled {request.method} {path}"})

    fake_hosted = httpx.AsyncClient(transport=httpx.MockTransport(_hosted_handler), follow_redirects=False)

    async def _shared_hosted_client() -> httpx.AsyncClient:
        return fake_hosted

    prev_hosted_client = hosted_api.shared_client
    hosted_api.shared_client = _shared_hosted_client  # type: ignore[assignment]

    served = tmp_path / "served"
    served.mkdir(parents=True, exist_ok=True)
    tls_dir = tmp_path / "tls"
    tls_dir.mkdir(parents=True, exist_ok=True)
    cert = self_signed_cert(tls_dir)
    assert cert is not None
    index_kp, publisher_kp, _stranger = keypairs(tmp_path / "keys")
    trust = fixture_trust_root(index_kp, publisher_kp)
    clock = FrozenClock()

    async def _fake_create_session(_request: Any, body: Any, **_kw: Any) -> Dict[str, Any]:
        sid = f"ses_stub{len(launched_sessions) + 1}"
        rec = {
            "id": sid,
            "tmux_session": None,
            "agent_type": body.agent_type,
            "working_dir": body.working_dir,
            "opening_prompt": body.opening_prompt,
            "status": "active",
        }
        launched_sessions.append(rec)
        return rec

    monkeypatch.setattr(session_crud_routes, "create_session_with_extra", _fake_create_session)
    monkeypatch.setattr(developer_mode, "is_on", lambda: dev_mode_flag["on"])
    monkeypatch.setattr(type(settings), "get_state_dir", lambda _self: state)
    monkeypatch.setattr(type(settings), "get_launch_profiles", lambda _self: list(launch_profiles))

    prev_codeload = archive_client.CODELOAD_BASE_URL
    with serve_directory(served, tls_cert=cert) as static_srv:
        archive_client.CODELOAD_BASE_URL = static_srv.base_url
        index_url = f"{static_srv.base_url}/{INDEX_PATH}"
        catalog = build_catalog_services(
            index_url=lambda: index_url,
            api_base_url=lambda: "https://catalog.test.invalid/api/v1",
            clock=clock,
            open_db=lambda: connect(db_path_for(state)),
            trust_root=trust,
        )
        roots = LiveInstallRoots(settings_reader=StateOnlySettings(state))
        services = build_services(
            clock=clock,
            install_roots=roots,
            catalog=catalog,
            settings_reader=StateOnlySettings(state),
            ui_preferences=prefs,
        )
        with open_token_store(state) as tok_store:
            tok_store.save(
                CatalogSession(
                    login="alice",
                    access_token="HELD-ACCESS-SECRET",
                    access_expires_at=4_000_000_000,
                    refresh_token="HELD-REFRESH-SECRET",
                    refresh_expires_at=4_100_000_000,
                )
            )
        cplugs_host = runtime.Host(state, app)
        loop = asyncio.new_event_loop()
        rt = sidecar_boot.SidecarRuntime(cplugs_host, app, loop, env_safe=lambda: False, app_version="9.9.9")
        app.state.sidecar_runtime = rt
        app.state.cplugs_host = cplugs_host
        app.state.services = services
        app.state.ui_preferences_store = prefs
        app.state.catalog_index_refresher = IndexRefresher(catalog.index_cache)
        app.state.session_manager = SimpleNamespace(sessions={})
        dev_lease.store_for(state).clear_all()
        _row, api_secret = key_store.create("script")
        catalog_publish_routes.clear_handle_cache(id(app))

        with TestClient(app) as tc:
            try:
                yield SimpleNamespace(
                    client=tc,
                    state=state,
                    owner=bearer(owner_jwt),
                    api_key=bearer(api_secret),
                    rt=rt,
                    app=app,
                    dev_mode_flag=dev_mode_flag,
                    launch_profiles=launch_profiles,
                    launched_sessions=launched_sessions,
                    published_topics=published_topics,
                    sent_hosted=sent_hosted,
                )
            finally:
                if tc.portal is not None:
                    tc.portal.call(dev_session.manager_for(app).shutdown)
                    tc.portal.call(rt.supervisor.shutdown)
                for attr in (
                    "sidecar_runtime",
                    "cplugs_host",
                    "services",
                    "ui_preferences_store",
                    "catalog_index_refresher",
                    "session_manager",
                    "plugin_studio_dev",
                ):
                    if hasattr(app.state, attr):
                        delattr(app.state, attr)
                sidecar_registry.install(None)
                dev_lease.store_for(state).clear_all()
                hosted_api.shared_client = prev_hosted_client  # type: ignore[assignment]
                archive_client.CODELOAD_BASE_URL = prev_codeload
                loop.close()


def test_studio_routes_auth_and_api_key_fence(studio_world: SimpleNamespace) -> None:
    r_unauth = studio_world.client.get("/api/v1/cplug-owner/studio/workspaces")
    assert r_unauth.status_code == 401

    r_key = studio_world.client.get("/api/v1/cplug-owner/studio/workspaces", headers=studio_world.api_key)
    assert r_key.status_code == 403
    assert r_key.json()["detail"]["reason"] == "api_key_forbidden"

    r_post_key = studio_world.client.post(
        "/api/v1/cplug-owner/studio/workspaces",
        json={"prompt": "Build plugin", "template": "no-code"},
        headers=studio_world.api_key,
    )
    assert r_post_key.status_code == 403


def test_studio_agy_profile_resolution_and_agent_switch(studio_world: SimpleNamespace) -> None:
    r_missing = studio_world.client.post(
        "/api/v1/cplug-owner/studio/workspaces",
        json={"prompt": "Build with agy", "template": "no-code", "name": "agyplug", "agent_kind": "agy"},
        headers=studio_world.owner,
    )
    assert r_missing.status_code == 409
    assert r_missing.json()["detail"]["code"] == "agy_profile_not_configured"
    assert studio_world.client.get("/api/v1/cplug-owner/studio/workspaces", headers=studio_world.owner).json()["workspaces"] == []

    r_ws = studio_world.client.post(
        "/api/v1/cplug-owner/studio/workspaces",
        json={"prompt": "Build a status greeting plugin", "template": "no-code", "name": "agyplug", "agent_kind": "claude"},
        headers=studio_world.owner,
    )
    assert r_ws.status_code == 201, r_ws.text
    studio_id = r_ws.json()["workspace"]["studio_id"]
    assert r_ws.json()["session"]["agent_type"] == "claude"

    studio_world.launch_profiles.append({"id": "agy-main", "default": True, "agent": {"process": "agy", "rules": "agy"}})
    r_agy = studio_world.client.post(
        f"/api/v1/cplug-owner/studio/workspaces/{studio_id}/agent",
        json={"agent_kind": "agy", "prompt": "Add a second macro"},
        headers=studio_world.owner,
    )
    assert r_agy.status_code == 200, r_agy.text
    assert r_agy.json()["agent_type"] == "agy-main"


def test_studio_dev_mode_hot_reload_preview_and_delete(studio_world: SimpleNamespace) -> None:
    studio_world.dev_mode_flag["on"] = False
    r_ws = studio_world.client.post(
        "/api/v1/cplug-owner/studio/workspaces",
        json={"prompt": "Widget preview test", "template": "no-code", "name": "prevplug", "start_agent": False},
        headers=studio_world.owner,
    )
    assert r_ws.status_code == 201
    studio_id = r_ws.json()["workspace"]["studio_id"]
    folder = Path(r_ws.json()["workspace"]["folder"])

    (folder / "carnivore.toml").write_text(
        (folder / "carnivore.toml").read_text(encoding="utf-8")
        + '\n[ui.widget]\ntitle = "Prev"\ndocument = { schema = 1, root = { type = "section", title = "Beat 1", children = [{ type = "text", value = "Hello" }] } }\n',
        encoding="utf-8",
    )

    r_dev_off = studio_world.client.post(
        f"/api/v1/cplug-owner/studio/workspaces/{studio_id}/dev/start",
        headers=studio_world.owner,
    )
    assert r_dev_off.status_code == 409
    assert r_dev_off.json()["detail"]["code"] == "developer_mode_off"

    studio_world.dev_mode_flag["on"] = True
    r_dev_on = studio_world.client.post(
        f"/api/v1/cplug-owner/studio/workspaces/{studio_id}/dev/start",
        headers=studio_world.owner,
    )
    assert r_dev_on.status_code == 200, r_dev_on.text
    assert r_dev_on.json()["active"] is True

    r_prev = studio_world.client.post(
        f"/api/v1/cplug-owner/studio/workspaces/{studio_id}/preview-render",
        json={"theme_id": "matrix", "width": 640, "height": 420},
        headers=studio_world.owner,
    )
    assert r_prev.status_code == 200, r_prev.text
    prev_body = r_prev.json()
    assert prev_body["kind"] == "declarative"
    assert prev_body["doc"]["root"]["title"] == "Beat 1"
    assert prev_body["theme_id"] == "matrix"

    toml_text = (folder / "carnivore.toml").read_text(encoding="utf-8").replace("Beat 1", "Beat 2")
    (folder / "carnivore.toml").write_text(toml_text, encoding="utf-8")
    deadline = time.monotonic() + 2.0
    reloaded = False
    while time.monotonic() < deadline:
        evs = dev_stream.stream_for(studio_world.state).recent("prevplug")
        if any(e.get("type") == "reloaded" for e in evs):
            reloaded = True
            break
        time.sleep(0.03)
    assert reloaded is True

    r_prev2 = studio_world.client.post(
        f"/api/v1/cplug-owner/studio/workspaces/{studio_id}/preview-render",
        json={},
        headers=studio_world.owner,
    )
    assert r_prev2.status_code == 200
    assert r_prev2.json()["doc"]["root"]["title"] == "Beat 2"

    r_get = studio_world.client.get(f"/api/v1/cplug-owner/studio/workspaces/{studio_id}", headers=studio_world.owner)
    assert r_get.status_code == 200
    assert r_get.json()["inspector"]["capabilities"]["permissions"] == ["notify"]

    r_stop = studio_world.client.post(f"/api/v1/cplug-owner/studio/workspaces/{studio_id}/dev/stop", headers=studio_world.owner)
    assert r_stop.status_code == 200
    assert r_stop.json()["active"] is False

    r_del = studio_world.client.delete(f"/api/v1/cplug-owner/studio/workspaces/{studio_id}", headers=studio_world.owner)
    assert r_del.status_code == 200
    assert not folder.exists()


def test_studio_readiness_sandbox_install_and_publish(studio_world: SimpleNamespace) -> None:
    if not DARWIN_SANDBOX:
        pytest.skip("sandbox smoke probe requires macOS sandbox-exec")

    r_ws = studio_world.client.post(
        "/api/v1/cplug-owner/studio/workspaces",
        json={"prompt": "Build a python plugin", "template": "python", "name": "studiotest", "start_agent": False},
        headers=studio_world.owner,
    )
    assert r_ws.status_code == 201, r_ws.text
    studio_id = r_ws.json()["workspace"]["studio_id"]

    r_rdy = studio_world.client.get(f"/api/v1/cplug-owner/studio/workspaces/{studio_id}/readiness", headers=studio_world.owner)
    assert r_rdy.status_code == 200, r_rdy.text
    assert r_rdy.json()["ready"] is True

    r_rdy_post = studio_world.client.post(
        f"/api/v1/cplug-owner/studio/workspaces/{studio_id}/readiness",
        json={"run_tests": True},
        headers=studio_world.owner,
    )
    assert r_rdy_post.status_code == 200
    assert r_rdy_post.json()["ready"] is True

    r_sbx = studio_world.client.post(
        f"/api/v1/cplug-owner/studio/workspaces/{studio_id}/test-sandbox",
        json={},
        headers=studio_world.owner,
    )
    assert r_sbx.status_code == 200, r_sbx.text
    assert r_sbx.json()["ok"] is True
    assert r_sbx.json()["smoke"]["tool_checked"] == "studiotest_hello"

    r_inst = studio_world.client.post(
        f"/api/v1/cplug-owner/studio/workspaces/{studio_id}/install",
        json={"activate_runtime": True, "auto_approve": True},
        headers=studio_world.owner,
    )
    assert r_inst.status_code == 200, r_inst.text
    assert r_inst.json()["ok"] is True
    assert r_inst.json()["enabled"] is True

    r_pub_dry = studio_world.client.post(
        f"/api/v1/cplug-owner/studio/workspaces/{studio_id}/publish",
        json={"mode": "local", "dry_run": True},
        headers=studio_world.owner,
    )
    assert r_pub_dry.status_code == 200, r_pub_dry.text
    preview = r_pub_dry.json()["preview"]
    assert preview["can_send"] is True

    r_pub_send = studio_world.client.post(
        f"/api/v1/cplug-owner/studio/workspaces/{studio_id}/publish",
        json={"mode": "local", "digest": preview["digest"], "dry_run": False},
        headers=studio_world.owner,
    )
    assert r_pub_send.status_code == 200, r_pub_send.text
    assert r_pub_send.json()["submission"]["submission_id"] == SUBMISSION_ID

    r_gh_send = studio_world.client.post(
        f"/api/v1/cplug-owner/studio/workspaces/{studio_id}/publish",
        json={"mode": "github", "pointer": "alice/studiotest@v0.1.0", "dry_run": False},
        headers=studio_world.owner,
    )
    assert r_gh_send.status_code == 200, r_gh_send.text
    assert r_gh_send.json()["submission"]["submission_id"] == SUBMISSION_ID


def test_studio_view_preview_codex_and_permission_widening(studio_world: SimpleNamespace) -> None:
    r_ws = studio_world.client.post(
        "/api/v1/cplug-owner/studio/workspaces",
        json={"prompt": "Build an iframe view plugin", "template": "no-code", "name": "viewplug", "agent_kind": "codex"},
        headers=studio_world.owner,
    )
    assert r_ws.status_code == 201, r_ws.text
    assert r_ws.json()["session"]["agent_type"] == "codex"
    studio_id = r_ws.json()["workspace"]["studio_id"]
    folder = Path(r_ws.json()["workspace"]["folder"])

    views_dir = folder / "views" / "main"
    views_dir.mkdir(parents=True, exist_ok=True)
    (views_dir / "index.html").write_text("<html><body><h1>Studio View</h1></body></html>\n", encoding="utf-8")
    (folder / "carnivore.toml").write_text(
        (folder / "carnivore.toml").read_text(encoding="utf-8")
        + '\n[[ui.views]]\nname = "main"\nsurfaces = ["panel"]\nfiles = ["index.html"]\n',
        encoding="utf-8",
    )

    r_start = studio_world.client.post(
        f"/api/v1/cplug-owner/studio/workspaces/{studio_id}/dev/start",
        headers=studio_world.owner,
    )
    assert r_start.status_code == 200, r_start.text

    r_view = studio_world.client.post(
        f"/api/v1/cplug-owner/studio/workspaces/{studio_id}/preview-render",
        json={"surface_id": "main", "theme_id": "carnivore"},
        headers=studio_world.owner,
    )
    assert r_view.status_code == 200, r_view.text
    assert r_view.json()["kind"] == "view"
    assert r_view.json()["view_url"].startswith("/api/v1/cplugs/viewplug/view/main/")

    toml_widened = (folder / "carnivore.toml").read_text(encoding="utf-8").replace(
        'write = ["notify"]',
        'read = ["sessions"]\nwrite = ["notify"]',
    ).replace(
        '[permissions.reasons]',
        '[permissions.reasons]\n"sessions.read" = "Read sessions"',
    )
    (folder / "carnivore.toml").write_text(toml_widened, encoding="utf-8")
    deadline = time.monotonic() + 2.0
    widened = False
    while time.monotonic() < deadline:
        evs = dev_stream.stream_for(studio_world.state).recent("viewplug")
        if any(e.get("type") == "permission_widened" for e in evs):
            widened = True
            break
        time.sleep(0.03)
    assert widened is True

    deadline_store = time.monotonic() + 2.0
    cleared = False
    while time.monotonic() < deadline_store:
        r_ws_after = studio_world.client.get(f"/api/v1/cplug-owner/studio/workspaces/{studio_id}", headers=studio_world.owner)
        assert r_ws_after.status_code == 200
        body_after = r_ws_after.json()
        if body_after["workspace"].get("dev_active") is False and body_after["dev_status"]["active"] is False:
            cleared = True
            break
        time.sleep(0.03)
    assert cleared is True


def test_studio_routes_malformed_readiness_github_files_publish_and_malformed_tier0_ui(studio_world: SimpleNamespace) -> None:
    r_ws = studio_world.client.post(
        "/api/v1/cplug-owner/studio/workspaces",
        json={"prompt": "GitHub workspace files publish", "template": "no-code", "name": "ghfiles", "start_agent": False},
        headers=studio_world.owner,
    )
    assert r_ws.status_code == 201, r_ws.text
    studio_id = r_ws.json()["workspace"]["studio_id"]
    folder = Path(r_ws.json()["workspace"]["folder"])

    r_pub = studio_world.client.post(
        f"/api/v1/cplug-owner/studio/workspaces/{studio_id}/publish",
        json={
            "mode": "github",
            "pointer": "alice/ghupload@v0.1.0",
            "include_workspace_files": True,
            "dry_run": False,
        },
        headers=studio_world.owner,
    )
    assert r_pub.status_code == 200, r_pub.text
    assert r_pub.json()["submission"]["submission_id"] == SUBMISSION_ID

    (folder / "ui").mkdir(parents=True, exist_ok=True)
    (folder / "ui" / "widget.json").write_text("{broken tier0 ui json\n", encoding="utf-8")
    (folder / "carnivore.toml").write_text(
        (folder / "carnivore.toml").read_text(encoding="utf-8")
        + '\n[ui.widget]\ntitle = "BrokenUI"\nui_file = "ui/widget.json"\n',
        encoding="utf-8",
    )
    r_prev = studio_world.client.post(
        f"/api/v1/cplug-owner/studio/workspaces/{studio_id}/preview-render",
        json={"theme_id": "carnivore"},
        headers=studio_world.owner,
    )
    assert r_prev.status_code == 200, r_prev.text
    prev_body = r_prev.json()
    assert prev_body["errors"], prev_body
    assert prev_body["errors"][0]["code"] == "manifest_invalid"

    (folder / "ui" / "widget.json").write_text(
        '{"schema": 1, "root": {"type": "section", "title": "OK", "children": []}}\n',
        encoding="utf-8",
    )
    r_dev = studio_world.client.post(
        f"/api/v1/cplug-owner/studio/workspaces/{studio_id}/dev/start",
        headers=studio_world.owner,
    )
    assert r_dev.status_code == 200, r_dev.text
    defn = runtime.find("ghfiles")
    assert defn is not None
    (defn.code_root / "ui" / "widget.json").write_text("{broken tier0 ui json\n", encoding="utf-8")
    r_prev_live = studio_world.client.post(
        f"/api/v1/cplug-owner/studio/workspaces/{studio_id}/preview-render",
        json={"theme_id": "carnivore"},
        headers=studio_world.owner,
    )
    assert r_prev_live.status_code == 200, r_prev_live.text
    prev_live_body = r_prev_live.json()
    assert prev_live_body["errors"], prev_live_body
    assert prev_live_body["errors"][0]["code"] == "tier0_ui_invalid"
    studio_world.client.post(
        f"/api/v1/cplug-owner/studio/workspaces/{studio_id}/dev/stop",
        headers=studio_world.owner,
    )

    (folder / "carnivore.toml").write_text("schema = 2\nid = [unclosed\n", encoding="utf-8")
    r_rdy = studio_world.client.get(
        f"/api/v1/cplug-owner/studio/workspaces/{studio_id}/readiness",
        headers=studio_world.owner,
    )
    assert r_rdy.status_code == 200, r_rdy.text
    rdy_body = r_rdy.json()
    assert rdy_body["ready"] is False
    by_id = {item["id"]: item for item in rdy_body["items"]}
    assert by_id["check_manifest"]["status"] == "fail"
    assert by_id["gate_02_schema"]["status"] == "fail"


def test_studio_preview_render_catches_supervisor_ensure_sandbox_unavailable(
    studio_world: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    r_ws = studio_world.client.post(
        "/api/v1/cplug-owner/studio/workspaces",
        json={"prompt": "Python ensure error test", "template": "python", "name": "ensurerr", "start_agent": False},
        headers=studio_world.owner,
    )
    assert r_ws.status_code == 201, r_ws.text
    studio_id = r_ws.json()["workspace"]["studio_id"]
    folder = Path(r_ws.json()["workspace"]["folder"])

    from src.plugins.host import sideload, sideload_routes

    sideload.set_switch(studio_world.state, True)
    studio_world.client.portal.call(sideload_routes.sync_folder, studio_world.rt, folder, None)

    async def _fail_ensure(_plugin_id: str):
        raise sandbox.SandboxUnavailable("sandbox unavailable in test")

    monkeypatch.setattr(studio_world.rt.supervisor, "ensure", _fail_ensure)
    r_prev = studio_world.client.post(
        f"/api/v1/cplug-owner/studio/workspaces/{studio_id}/preview-render",
        json={"theme_id": "carnivore"},
        headers=studio_world.owner,
    )
    assert r_prev.status_code == 200, r_prev.text
    body = r_prev.json()
    assert body["errors"]
    assert body["errors"][0]["code"] == "SandboxUnavailable"


def test_studio_dev_revert_after_error_and_missing_folder_cleanup(studio_world: SimpleNamespace) -> None:
    import shutil

    r_ws = studio_world.client.post(
        "/api/v1/cplug-owner/studio/workspaces",
        json={"prompt": "Dev revert and missing folder test", "template": "no-code", "name": "revplug", "start_agent": False},
        headers=studio_world.owner,
    )
    assert r_ws.status_code == 201, r_ws.text
    studio_id = r_ws.json()["workspace"]["studio_id"]
    folder = Path(r_ws.json()["workspace"]["folder"])
    toml_path = folder / "carnivore.toml"
    valid_toml = toml_path.read_text(encoding="utf-8")

    r_start = studio_world.client.post(
        f"/api/v1/cplug-owner/studio/workspaces/{studio_id}/dev/start",
        headers=studio_world.owner,
    )
    assert r_start.status_code == 200, r_start.text

    toml_path.write_text("schema = 2\nid = [unclosed\n", encoding="utf-8")
    deadline = time.monotonic() + 2.5
    saw_error = False
    while time.monotonic() < deadline:
        r_det = studio_world.client.get(f"/api/v1/cplug-owner/studio/workspaces/{studio_id}", headers=studio_world.owner)
        assert r_det.status_code == 200
        dev_st = r_det.json()["dev_status"]
        if dev_st["status"] == "error" and dev_st["last_error"] is not None:
            saw_error = True
            break
        time.sleep(0.03)
    assert saw_error is True

    toml_path.write_text(valid_toml, encoding="utf-8")
    deadline = time.monotonic() + 2.5
    recovered = False
    while time.monotonic() < deadline:
        r_det = studio_world.client.get(f"/api/v1/cplug-owner/studio/workspaces/{studio_id}", headers=studio_world.owner)
        assert r_det.status_code == 200
        dev_st = r_det.json()["dev_status"]
        if dev_st["status"] in ("active", "reloaded") and dev_st["last_error"] is None and dev_st["active"] is True:
            recovered = True
            break
        time.sleep(0.03)
    assert recovered is True

    shutil.rmtree(folder)
    from src.core.plugin_studio import store as studio_store

    deadline = time.monotonic() + 2.5
    cleaned = False
    while time.monotonic() < deadline:
        ws_row = studio_store.get_workspace(studio_world.state, studio_id)
        dev_st = dev_session.manager_for(studio_world.app).status_for(studio_id, studio_world.state, "revplug")
        if ws_row.get("dev_active") is False and dev_st["active"] is False and dev_st["status"] == "stopped":
            cleaned = True
            break
        time.sleep(0.03)
    assert cleaned is True
