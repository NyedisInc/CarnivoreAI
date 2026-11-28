
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.api import catalog_install_routes
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.skills.kinds import KIND_PLUGIN
from src.core.skills.ledger import InstallLedger
from src.core.skills.ledger_types import GLOBAL_PROJECT_PATH, SCOPE_GLOBAL, InstalledItem
from src.plugins.host import dev_stream, inspector_telemetry, owner_switch, routes as host_routes, runtime as host_runtime, state as owner_state
from src.plugins.host.plugin_manifest import load_sidecar_manifest
from src.plugins.host.sidecar_registry import SidecarDefinition
from tests.helpers.catalog_app import catalog_app
from tests.helpers.minisign_keys import SKIP_REASON, minisign_binary
from tests.python.cplugs.test_cplug_install_glue import GLOBAL, attach_runtime, cplug_files, live_roots, publish


def test_agent_plugin_rows_include_install_id_and_publisher(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    ensure_db_migrated(state, 4, "0.8.2")
    conn = connect(db_path_for(state), create=False)
    try:
        InstallLedger(conn).insert(
            InstalledItem(
                install_id="inst-ap-123",
                item_id="github/gh-agent-mod",
                kind=KIND_PLUGIN,
                publisher="github",
                name="gh-agent-mod",
                version="1.0.0",
                digest="sha256:abc",
                scope=SCOPE_GLOBAL,
                project_path=GLOBAL_PROJECT_PATH,
                auto_update=False,
                source_index_url="https://github.com/acme/gh-agent-mod.git",
                consented_digest="sha256:abc",
                consented_body_sha="body-sha",
                publisher_key_id="",
                revision=1,
                installed_at="2026-11-24T00:00:00Z",
                updated_at="2026-11-24T00:00:00Z",
                consent_via="sheet",
            )
        )
    finally:
        conn.close()

    host = host_runtime.Host(state)
    rows = host_routes._agent_plugin_rows(host)
    assert len(rows) == 1
    assert rows[0]["id"] == "gh-agent-mod"
    assert rows[0]["install_id"] == "inst-ap-123"
    assert rows[0]["publisher"] == "github"
    assert rows[0]["kind"] == "agent-plugin"


def test_cplug_row_serializes_declarative_widget_and_none_when_absent(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    code_decl = tmp_path / "code" / "declw"
    code_decl.mkdir(parents=True)
    (code_decl / "carnivore.toml").write_text(
        """
schema = 2
id = "declw"
name = "Declarative Widget"
version = "1.0.0"
kind = "widget"
description = "Tier 0 widget"
author = "Tester"

[ui.widget]
id = "clock"
title = "Clock"
sizes = ["medium", "large"]
document = { schema = 1, root = { type = "text", value = "12:00" } }
""",
        encoding="utf-8",
    )
    sm_decl = load_sidecar_manifest(code_decl, "declw")
    d_decl = SidecarDefinition(manifest=sm_decl, item_id="local/declw", install_key="inst-declw", code_root=code_decl, folder=tmp_path / "data" / "declw")
    owner_state.update(state, sm_decl, None, lambda st: replace(st, enabled=True, digest=sm_decl.code_digest))

    code_plain = tmp_path / "code" / "plainp"
    code_plain.mkdir(parents=True)
    (code_plain / "main.py").write_text("print('ok')\n", encoding="utf-8")
    (code_plain / "carnivore.toml").write_text(
        """
schema = 2
id = "plainp"
name = "Plain Plugin"
version = "1.0.0"
kind = "plugin"
description = "No widget"
author = "Tester"

[run]
cmd = ["python3", "main.py"]
mode = "rpc"
""",
        encoding="utf-8",
    )
    sm_plain = load_sidecar_manifest(code_plain, "plainp")
    d_plain = SidecarDefinition(manifest=sm_plain, item_id="local/plainp", install_key="inst-plainp", code_root=code_plain, folder=tmp_path / "data" / "plainp")
    owner_state.update(state, sm_plain, None, lambda st: replace(st, enabled=False, digest=sm_plain.code_digest))

    host = host_runtime.Host(state)
    row_decl = host_routes.cplug_row(host, d_decl)
    assert row_decl["declarative_widget"] == {
        "id": "clock",
        "title": "Clock",
        "sizes": ["medium", "large"],
        "document": {"schema": 1, "root": {"type": "text", "value": "12:00"}},
    }
    row_plain = host_routes.cplug_row(host, d_plain)
    assert row_plain["declarative_widget"] is None


def test_watchdog_row_summary_includes_last_call_and_last_event(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    sup = SimpleNamespace(
        process=lambda _pid: None,
        restart_count=lambda _pid: 0,
        state=lambda _pid: "running",
        _strikes={},
    )

    empty_summary = inspector_telemetry.watchdog_row_summary(state, sup, "emptyplug")
    assert empty_summary["last_call"] is None
    assert empty_summary["last_event"] is None

    tel = inspector_telemetry.telemetry_for(state)
    tel.record_rpc("obsplug", source="rpc", method="http.fetch", target="https://api.example.com/data", ok=True)
    tel.record_capability("obsplug", permission="network_hosts:api.example.com", allowed=True, reason="granted")
    cap_summary = inspector_telemetry.watchdog_row_summary(state, sup, "obsplug")
    assert cap_summary["last_call"] == "http.fetch https://api.example.com/data"
    assert cap_summary["last_event"] == "network_hosts:api.example.com (allowed)"

    dev_stream.stream_for(state).publish("obsplug", "reloaded", {"ms": 12})
    stream_summary = inspector_telemetry.watchdog_row_summary(state, sup, "obsplug")
    assert stream_summary["last_event"] == "reloaded"


def test_cplug_row_serializes_runtime_active_from_owner_switch_and_safe_mode(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    code_plain = tmp_path / "code" / "plainp"
    code_plain.mkdir(parents=True)
    (code_plain / "main.py").write_text("print('ok')\n", encoding="utf-8")
    (code_plain / "carnivore.toml").write_text(
        """
schema = 2
id = "plainp"
name = "Plain Plugin"
version = "1.0.0"
kind = "plugin"
description = "Runtime active check"
author = "Tester"

[run]
cmd = ["python3", "main.py"]
mode = "rpc"
""",
        encoding="utf-8",
    )
    sm = load_sidecar_manifest(code_plain, "plainp")
    defn = SidecarDefinition(
        manifest=sm,
        item_id="local/plainp",
        install_key="inst-plainp",
        code_root=code_plain,
        folder=tmp_path / "data" / "plainp",
    )
    owner_state.update(state, sm, None, lambda st: replace(st, enabled=False, digest=sm.code_digest))

    host = host_runtime.Host(state)
    assert host_routes.cplug_row(host, defn)["runtime_active"] is False

    assert owner_switch.write(state, True) is True
    assert host_routes.cplug_row(host, defn)["runtime_active"] is True

    app_safe = SimpleNamespace(
        state=SimpleNamespace(
            sidecar_runtime=SimpleNamespace(
                supervisor=SimpleNamespace(
                    state=lambda _pid: "disabled (safe mode)",
                    is_paused=lambda _pid: False,
                    process=lambda _pid: None,
                    restart_count=lambda _pid: 0,
                    _strikes={},
                ),
                safe_mode=lambda: {"env": False, "owner": True, "off": False},
            )
        )
    )
    host_safe = host_runtime.Host(state, app=app_safe)
    assert host_routes.cplug_row(host_safe, defn)["runtime_active"] is False


@pytest.mark.skipif(minisign_binary() is None, reason=SKIP_REASON)
def test_catalog_preview_for_cplug_serializes_real_runtime_active(tmp_path: Path) -> None:
    trust, _package = publish(tmp_path, cplug_files())
    state = tmp_path / "state"
    (tmp_path / "served").mkdir(exist_ok=True)
    with catalog_app(tmp_path, tmp_path / "served", trust_root=trust, roots_factory=live_roots) as app:
        app.client.app.include_router(catalog_install_routes.router, prefix="/api/v1")
        rt = attach_runtime(app.client.app, state)

        assert owner_switch.read(state) is False
        off_res = app.client.post("/api/v1/catalog/install/preview", json=GLOBAL)
        assert off_res.status_code == 200, off_res.text
        assert off_res.json()["runtime_active"] is False

        assert owner_switch.write(state, True) is True
        on_res = app.client.post("/api/v1/catalog/install/preview", json=GLOBAL)
        assert on_res.status_code == 200, on_res.text
        assert on_res.json()["runtime_active"] is True

        rt.route_safe = True
        safe_res = app.client.post("/api/v1/catalog/install/preview", json=GLOBAL)
        assert safe_res.status_code == 200, safe_res.text
        assert safe_res.json()["runtime_active"] is False
