
from __future__ import annotations

import asyncio
import contextlib
import os
import stat
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
from src.core.plugin_studio import dev_session, store as studio_store
from src.core.ui_preferences_store import UiPreferencesStore
from src.plugins.host import developer_mode, dev_lease, dev_stream, runtime, sidecar_boot, sidecar_registry
from src.plugins.runtime import sandbox
from tests.helpers.catalog_app import StateOnlySettings
from tests.helpers.catalog_surface import INDEX_PATH, FrozenClock, fixture_trust_root, keypairs
from tests.helpers.static_http import self_signed_cert, serve_directory
from tests.python.api_keys.conftest import bearer, key_store, owner_jwt  # noqa: F401

SUBMISSION_ID = "cd" * 16


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
def studio_e2e_world(tmp_path: Path, owner_jwt, key_store, monkeypatch: pytest.MonkeyPatch):  # noqa: F811
    from src.main import app

    @contextlib.asynccontextmanager
    async def _noop_lifespan(_app: Any):
        yield

    monkeypatch.setattr(app.router, "lifespan_context", _noop_lifespan)
    state = tmp_path / "state"
    state.mkdir(parents=True, exist_ok=True)
    ensure_db_migrated(state, 4, "0.8.2")

    launched_sessions: List[Dict[str, Any]] = []
    sent_hosted: List[Dict[str, Any]] = []
    config_path = tmp_path / "config.json"
    config_path.write_text("{}\n", encoding="utf-8")
    prefs = UiPreferencesStore(lambda: config_path)

    def _hosted_handler(request: httpx.Request) -> httpx.Response:
        body_text = ""
        try:
            body_text = request.content.decode("utf-8", errors="replace")
        except Exception:
            body_text = ""
        sent_hosted.append({"method": request.method, "path": request.url.path, "body": body_text})
        path = request.url.path
        if request.method == "GET" and path.endswith("/me"):
            return httpx.Response(
                200,
                json={"provider": "github", "login": "alice", "handle": "alice", "handle_status": "approved", "registered": True},
            )
        if request.method == "POST" and path.endswith("/submissions"):
            return httpx.Response(
                201,
                json={"submission_id": SUBMISSION_ID, "status": "pending", "item_id": "alice/m63studio", "version": "0.1.0"},
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
        sid = f"ses_m63_{len(launched_sessions) + 1}"
        rec = {
            "id": sid,
            "tmux_session": f"cl_{sid}",
            "agent_type": body.agent_type,
            "working_dir": body.working_dir,
            "opening_prompt": body.opening_prompt,
            "status": "active",
        }
        launched_sessions.append(rec)
        return rec

    monkeypatch.setattr(session_crud_routes, "create_session_with_extra", _fake_create_session)
    monkeypatch.setattr(developer_mode, "is_on", lambda: True)
    monkeypatch.setattr(type(settings), "get_state_dir", lambda _self: state)

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
        _row, _api_secret = key_store.create("script")
        catalog_publish_routes.clear_handle_cache(id(app))

        with TestClient(app) as tc:
            try:
                yield SimpleNamespace(
                    client=tc,
                    state=state,
                    owner=bearer(owner_jwt),
                    rt=rt,
                    app=app,
                    launched_sessions=launched_sessions,
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


def test_m63_e2e_scaffold_hot_reload_multitheme_inspector_readiness_sandbox_install_publish(
    studio_e2e_world: SimpleNamespace,
) -> None:
    if not DARWIN_SANDBOX:
        pytest.skip("full Python sidecar sandbox E2E requires macOS sandbox-exec")

    client = studio_e2e_world.client
    headers = studio_e2e_world.owner

    prompt = "Build a multi-theme status greeting plugin for sessions"
    r_create = client.post(
        "/api/v1/cplug-owner/studio/workspaces",
        json={"prompt": prompt, "template": "python", "name": "m63studio", "agent_kind": "claude"},
        headers=headers,
    )
    assert r_create.status_code == 201, r_create.text
    created = r_create.json()
    ws = created["workspace"]
    studio_id = ws["studio_id"]
    folder = Path(ws["folder"])

    assert (folder / "carnivore.toml").is_file()
    assert (folder / "main.py").is_file()
    assert (folder / "README.md").is_file()
    assert (folder / "tests" / "test_m63studio.py").is_file()
    assert (folder / "LICENSE.md").is_file()
    assert "MIT License" in (folder / "LICENSE.md").read_text(encoding="utf-8")
    brief_text = (folder / "STUDIO_BRIEF.md").read_text(encoding="utf-8")
    assert studio_id in brief_text
    assert "m63studio" in brief_text
    assert "python" in brief_text
    assert prompt in brief_text

    idx_path = studio_store.index_path(studio_e2e_world.state)
    assert idx_path.is_file()
    assert stat.S_IMODE(idx_path.stat().st_mode) == 0o600

    assert len(studio_e2e_world.launched_sessions) == 1
    launched = studio_e2e_world.launched_sessions[0]
    assert launched["agent_type"] == "claude"
    assert "STUDIO_BRIEF.md" in launched["opening_prompt"]

    toml_path = folder / "carnivore.toml"
    toml_text = toml_path.read_text(encoding="utf-8").replace(
        '[permissions.reasons]\n"sessions.read" = "Read active sessions for plugin context."',
        '[permissions.reasons]\n"sessions.read" = "Read active sessions for plugin context."\n"ui.slot:session.row_actions" = "Add M63 action to session row menu."',
    )
    toml_text += (
        '\n[[ui.contribute."session.row_actions"]]\n'
        'id = "m63_ping"\n'
        'label = "M63 Ping"\n'
        'route = "status"\n'
    )
    toml_path.write_text(toml_text, encoding="utf-8")

    r_start = client.post(f"/api/v1/cplug-owner/studio/workspaces/{studio_id}/dev/start", headers=headers)
    assert r_start.status_code == 200, r_start.text
    start_body = r_start.json()
    assert start_body["active"] is True
    baseline_sha = start_body["lease"]["baseline_sha"]
    assert baseline_sha

    main_path = folder / "main.py"
    original_main = main_path.read_text(encoding="utf-8")
    assert '"Ready"' in original_main
    updated_main = original_main.replace('"Ready"', '"Hot Reloaded M63"')
    main_path.write_text(updated_main, encoding="utf-8")

    deadline = time.monotonic() + 3.0
    reloaded_ev: Dict[str, Any] | None = None
    while time.monotonic() < deadline:
        evs = dev_stream.stream_for(studio_e2e_world.state).recent("m63studio")
        for ev in reversed(evs):
            if ev.get("type") == "reloaded":
                reloaded_ev = ev
                break
        if reloaded_ev is not None:
            break
        time.sleep(0.03)
    assert reloaded_ev is not None, dev_stream.stream_for(studio_e2e_world.state).recent("m63studio")
    assert reloaded_ev["data"]["status"] == "reloaded"
    assert reloaded_ev["data"]["digest"] != baseline_sha
    assert reloaded_ev["data"]["timings"]["total_ms"] > 0

    for theme_id, width, height in (("carnivore", 480, 320), ("matrix", 720, 420)):
        r_prev = client.post(
            f"/api/v1/cplug-owner/studio/workspaces/{studio_id}/preview-render",
            json={"theme_id": theme_id, "width": width, "height": height},
            headers=headers,
        )
        assert r_prev.status_code == 200, r_prev.text
        prev = r_prev.json()
        assert prev["kind"] == "declarative"
        assert prev["errors"] == []
        assert prev["theme_id"] == theme_id
        assert prev["width"] == width
        assert prev["height"] == height
        assert prev["doc"]["root"]["children"][0]["value"] == "Hot Reloaded M63"

    r_detail = client.get(f"/api/v1/cplug-owner/studio/workspaces/{studio_id}", headers=headers)
    assert r_detail.status_code == 200, r_detail.text
    detail = r_detail.json()
    inspector = detail["inspector"]
    assert inspector["capabilities"]["permissions"] == ["sessions.read"]
    assert "m63studio_hello" in inspector["capabilities"]["tools"]
    assert "status" in inspector["capabilities"]["routes"]
    assert "session.row_actions" in inspector["slot_renders"]
    assert inspector["slot_renders"]["session.row_actions"][0]["plugin_id"] == "m63studio"
    event_types = {ev["type"] for ev in inspector["events"]}
    assert {"lease_acquired", "reloaded"}.issubset(event_types)
    assert inspector["ui_errors"] == []
    assert inspector["dev"]["reload_count"] >= 1

    r_green = client.post(
        f"/api/v1/cplug-owner/studio/workspaces/{studio_id}/readiness",
        json={"run_tests": True},
        headers=headers,
    )
    assert r_green.status_code == 200, r_green.text
    green = r_green.json()
    assert green["ready"] is True
    assert green["ok"] is True
    assert green["summary"]["fail"] == 0
    green_by_id = {item["id"]: item["status"] for item in green["items"]}
    assert green_by_id["check_manifest"] == "pass"
    assert green_by_id["prepare_kind"] == "pass"
    assert green_by_id["sandbox_test"] == "pass"
    assert green_by_id["gate_01_structure"] == "pass"
    assert green_by_id["gate_02_schema"] == "pass"
    assert green_by_id["gate_06_static_scans"] in ("pass", "advisory")
    assert green_by_id["gate_07_secrets"] == "pass"
    assert green_by_id["gate_08_license"] == "pass"

    saved_license = (folder / "LICENSE.md").read_text(encoding="utf-8")
    try:
        fake_jwt = ".".join([
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
            "eyJzdWIiOiIxMjM0NTY3ODkwIn0",
            "dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",
        ])
        main_path.write_text(
            "import subprocess\n"
            f"JWT = '{fake_jwt}'\n"
            "subprocess.run('id', shell=True)\n",
            encoding="utf-8",
        )
        (folder / "LICENSE.md").unlink()
        r_red = client.get(f"/api/v1/cplug-owner/studio/workspaces/{studio_id}/readiness?run_tests=false", headers=headers)
        assert r_red.status_code == 200, r_red.text
        red = r_red.json()
        assert red["ready"] is False
        assert red["summary"]["fail"] >= 3
        red_by_id = {item["id"]: item["status"] for item in red["items"]}
        assert red_by_id["gate_06_static_scans"] == "fail"
        assert red_by_id["gate_07_secrets"] == "fail"
        assert red_by_id["gate_08_license"] == "fail"
    finally:
        main_path.write_text(updated_main, encoding="utf-8")
        (folder / "LICENSE.md").write_text(saved_license, encoding="utf-8")

    r_recovered = client.get(f"/api/v1/cplug-owner/studio/workspaces/{studio_id}/readiness?run_tests=false", headers=headers)
    assert r_recovered.status_code == 200
    assert r_recovered.json()["ready"] is True

    r_sbx = client.post(
        f"/api/v1/cplug-owner/studio/workspaces/{studio_id}/test-sandbox",
        json={},
        headers=headers,
    )
    assert r_sbx.status_code == 200, r_sbx.text
    sbx = r_sbx.json()
    assert sbx["ok"] is True
    assert sbx["check"]["ok"] is True
    assert sbx["smoke"]["tool_checked"] == "m63studio_hello"
    assert sbx["smoke"]["ui_checked"] is True
    assert sbx["errors"] == []

    r_stop = client.post(f"/api/v1/cplug-owner/studio/workspaces/{studio_id}/dev/stop", headers=headers)
    assert r_stop.status_code == 200
    assert r_stop.json()["active"] is False

    r_install = client.post(
        f"/api/v1/cplug-owner/studio/workspaces/{studio_id}/install",
        json={"activate_runtime": True, "auto_approve": True},
        headers=headers,
    )
    assert r_install.status_code == 200, r_install.text
    inst = r_install.json()
    assert inst["ok"] is True
    assert inst["enabled"] is True
    assert inst["runtime_active"] is True
    assert inst["item_id"] == "local/m63studio"

    r_plug = client.get("/api/v1/cplugs/m63studio", headers=headers)
    assert r_plug.status_code == 200, r_plug.text
    assert r_plug.json()["enabled"] is True

    r_pub_dry = client.post(
        f"/api/v1/cplug-owner/studio/workspaces/{studio_id}/publish",
        json={"mode": "local", "dry_run": True},
        headers=headers,
    )
    assert r_pub_dry.status_code == 200, r_pub_dry.text
    preview = r_pub_dry.json()["preview"]
    assert preview["can_send"] is True
    assert preview["digest"]

    r_pub_local = client.post(
        f"/api/v1/cplug-owner/studio/workspaces/{studio_id}/publish",
        json={"mode": "local", "digest": preview["digest"], "dry_run": False},
        headers=headers,
    )
    assert r_pub_local.status_code == 200, r_pub_local.text
    assert r_pub_local.json()["submission"]["submission_id"] == SUBMISSION_ID

    r_pub_gh = client.post(
        f"/api/v1/cplug-owner/studio/workspaces/{studio_id}/publish",
        json={"mode": "github", "pointer": "alice/m63studio@v0.1.0", "dry_run": False},
        headers=headers,
    )
    assert r_pub_gh.status_code == 200, r_pub_gh.text
    assert r_pub_gh.json()["submission"]["submission_id"] == SUBMISSION_ID
    submits = [req for req in studio_e2e_world.sent_hosted if req["method"] == "POST" and req["path"].endswith("/submissions")]
    assert len(submits) == 2


def test_m63_e2e_view_iframe_csp_and_bash_widget_scaffold(studio_e2e_world: SimpleNamespace) -> None:
    client = studio_e2e_world.client
    headers = studio_e2e_world.owner

    for tpl, pname in (("bash", "m63bash"), ("widget", "m63widget")):
        r_ws = client.post(
            "/api/v1/cplug-owner/studio/workspaces",
            json={"prompt": f"Scaffold clean {tpl} plugin", "template": tpl, "name": pname, "start_agent": False},
            headers=headers,
        )
        assert r_ws.status_code == 201, r_ws.text
        ws = r_ws.json()["workspace"]
        folder = Path(ws["folder"])
        assert (folder / "STUDIO_BRIEF.md").is_file()
        assert (folder / "LICENSE.md").is_file()
        r_rdy = client.get(f"/api/v1/cplug-owner/studio/workspaces/{ws['studio_id']}/readiness?run_tests=false", headers=headers)
        assert r_rdy.status_code == 200, r_rdy.text
        assert r_rdy.json()["ready"] is True, r_rdy.json()

    r_view_ws = client.post(
        "/api/v1/cplug-owner/studio/workspaces",
        json={"prompt": "Build a multi-theme view plugin", "template": "no-code", "name": "m63view", "start_agent": False},
        headers=headers,
    )
    assert r_view_ws.status_code == 201, r_view_ws.text
    studio_id = r_view_ws.json()["workspace"]["studio_id"]
    folder = Path(r_view_ws.json()["workspace"]["folder"])
    views_dir = folder / "views" / "main"
    views_dir.mkdir(parents=True, exist_ok=True)
    (views_dir / "index.html").write_text("<html><head></head><body><h1>M63 View</h1></body></html>\n", encoding="utf-8")
    (folder / "carnivore.toml").write_text(
        (folder / "carnivore.toml").read_text(encoding="utf-8")
        + '\n[[ui.views]]\nname = "main"\nsurfaces = ["panel"]\nfiles = ["index.html"]\n',
        encoding="utf-8",
    )

    r_start = client.post(f"/api/v1/cplug-owner/studio/workspaces/{studio_id}/dev/start", headers=headers)
    assert r_start.status_code == 200, r_start.text

    for theme_id in ("carnivore", "matrix"):
        r_prev = client.post(
            f"/api/v1/cplug-owner/studio/workspaces/{studio_id}/preview-render",
            json={"surface_id": "main", "theme_id": theme_id, "width": 520, "height": 340},
            headers=headers,
        )
        assert r_prev.status_code == 200, r_prev.text
        prev = r_prev.json()
        assert prev["kind"] == "view"
        assert prev["theme_id"] == theme_id
        assert prev["view_url"].startswith("/api/v1/cplugs/m63view/view/main/")

        r_iframe = client.get(prev["view_url"])
        assert r_iframe.status_code == 200, r_iframe.text
        csp = r_iframe.headers.get("content-security-policy", "")
        assert "default-src 'none'" in csp
        assert "script-src http://testserver/api/v1/cplugs/m63view/view/main/" in csp
        assert "connect-src 'none'" in csp
        assert "frame-ancestors 'self'" in csp
        assert "sandbox allow-scripts" in csp
        assert r_iframe.headers.get("x-content-type-options") == "nosniff"
        assert "carnivore-frame.css" in r_iframe.text
