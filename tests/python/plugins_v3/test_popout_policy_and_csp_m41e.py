
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src import security_headers
from src.api import browser_open_routes
from src.api.auth import require_auth
from src.core.browser_pages import app_open, open_pages
from src.plugins.host import identity, page_owner, routes as host_routes, runtime as host_runtime, sidecar_registry, sidecar_ui, state as owner_state, ui_doc, ui_slots
from src.plugins.host.plugin_manifest import load_sidecar_manifest
from src.plugins.host.sidecar_registry import SidecarDefinition, SidecarRegistry
from src.plugins.sdk.manifest_v2 import ManifestV2Error, parse_manifest_v2
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _base_manifest(**ui_extras) -> dict:
    ui = dict(ui_extras)
    return {
        "schema": 2,
        "id": "linearsync",
        "name": "Linear Sync",
        "description": "Linear sync plugin.",
        "author": "Alice",
        "version": "1.0.0",
        "kind": "plugin",
        "ui": ui,
    }


def test_manifest_v2_parses_popout_across_ui_surfaces():
    raw = _base_manifest(
        popout={"enabled": True, "multi": True},
        widget={
            "id": "issues",
            "title": "Issues",
            "mode": "declarative",
            "sizes": ["medium"],
            "popout": True,
            "ui_file": "ui/widget.json",
        },
        sidebar_tab={
            "id": "linear",
            "title": "Linear",
            "icon": "ticket",
            "mode": "declarative",
            "popout": {"enabled": True, "multi": False},
            "ui_file": "ui/tab.json",
        },
        page={"menu": "nav", "main": "board", "popout": True},
        views=[
            {"name": "nav", "surfaces": ["panel"], "files": ["index.html"], "popout": False},
            {"name": "board", "surfaces": ["panel"], "files": ["index.html"], "popout": True},
        ],
    )
    m = parse_manifest_v2(raw)
    assert m.ui_meta["popout"] == {"enabled": True, "multi": True}
    assert m.ui_meta["widget"]["popout"] is True
    assert m.ui_meta["sidebar_tab"]["popout"] == {"enabled": True, "multi": False}
    assert m.page is not None and m.page["popout"] is True
    views_by_name = {v["name"]: v for v in m.views}
    assert views_by_name["board"]["popout"] is True
    assert views_by_name["nav"]["popout"] is False


@pytest.mark.parametrize(
    "bad_ui",
    [
        {"popout": "yes"},
        {"widget": {"id": "w", "title": "W", "sizes": ["medium"], "popout": 123}},
        {"sidebar_tab": {"title": "Tab", "mode": "badmode"}},
        {"sidebar_tab": {"title": "Tab", "popout": ["bad"]}},
        {"page": {"menu": "a", "main": "b", "popout": "nope"}},
    ],
)
def test_manifest_v2_rejects_invalid_popout_or_sidebar_tab(bad_ui):
    with pytest.raises(ManifestV2Error):
        parse_manifest_v2(_base_manifest(**bad_ui))


def test_row_metadata_and_cplug_row_propagate_popout_and_sidebar_tab(tmp_path: Path):
    code_dir = tmp_path / "code" / "linearsync"
    (code_dir / "ui").mkdir(parents=True)
    (code_dir / "views" / "inspect").mkdir(parents=True)
    (code_dir / "ui" / "widget.json").write_text(json.dumps({"schema": 2, "root": {"type": "text", "value": "Widget"}}))
    (code_dir / "ui" / "tab.json").write_text(json.dumps({"schema": 2, "root": {"type": "text", "value": "Tab"}}))
    (code_dir / "views" / "inspect" / "index.html").write_text("<html><body>ok</body></html>")
    (code_dir / "carnivore.toml").write_text(
        """
schema = 2
id = "linearsync"
name = "Linear Sync"
version = "1.0.0"
kind = "plugin"
description = "Linear sync plugin"
author = "Alice"

[ui.widget]
id = "issues"
title = "Issues"
mode = "declarative"
sizes = ["medium"]
popout = false
ui_file = "ui/widget.json"

[ui.sidebar_tab]
id = "linear_tab"
title = "Linear Tab"
icon = "ticket"
mode = "declarative"
popout = true
ui_file = "ui/tab.json"

[[ui.views]]
name = "inspect"
surfaces = ["panel"]
files = ["index.html"]
popout = true
""",
        encoding="utf-8",
    )

    sm = load_sidecar_manifest(code_dir, "linearsync")
    meta = ui_slots.row_metadata(sm, plugin_id=sm.id)
    assert meta["popout"] is True
    assert meta["sidebar_tab"]["title"] == "Linear Tab"
    assert meta["sidebar_tab"]["popout"] is True

    state = tmp_path / "state"
    state.mkdir()
    d = SidecarDefinition(
        manifest=sm,
        item_id="local/linearsync",
        install_key="k1",
        code_root=code_dir,
        folder=tmp_path / "data" / "linearsync",
    )
    row = host_routes.cplug_row(host_runtime.Host(state), d)
    assert row["popout"] is True
    assert row["sidebar_tab"]["id"] == "linear_tab"
    assert row["declarative_widget"]["popout"] is False
    assert row["views"][0]["popout"] is True


def test_tier0_static_document_resolves_sidebar_tab_surface(tmp_path: Path):
    ui_dir = tmp_path / "ui"
    ui_dir.mkdir()
    (ui_dir / "widget.json").write_text(json.dumps({"kind": "text", "text": "Widget Body"}))
    (ui_dir / "tab.json").write_text(json.dumps({"kind": "text", "text": "Tab Body"}))

    manifest = parse_manifest_v2(
        _base_manifest(
            widget={"id": "w", "title": "W", "mode": "declarative", "sizes": ["medium"], "ui_file": "ui/widget.json"},
            sidebar_tab={"id": "t", "title": "T", "mode": "declarative", "popout": True, "ui_file": "ui/tab.json"},
        )
    )
    entry = SimpleNamespace(id="linearsync", code_root=tmp_path, manifest=manifest)
    tab_doc = sidecar_ui._tier0_static_document(entry, surface="tab")
    widget_doc = sidecar_ui._tier0_static_document(entry, surface="widget")
    assert tab_doc == {"kind": "text", "text": "Tab Body"}
    assert widget_doc == {"kind": "text", "text": "Widget Body"}


def test_page_owner_recognizes_enabled_popout_sidecar_tabs(monkeypatch):
    def fake_listed():
        return [
            SimpleNamespace(
                id="linearsync",
                enabled=True,
                state="active",
                manifest=SimpleNamespace(
                    ui_meta={
                        "popout": False,
                        "sidebar_tab": {"id": "linear", "title": "Linear", "popout": True},
                    }
                ),
            ),
            SimpleNamespace(
                id="nopopout",
                enabled=True,
                state="active",
                manifest=SimpleNamespace(
                    ui_meta={"sidebar_tab": {"title": "NoPopout", "popout": False}}
                ),
            ),
        ]

    monkeypatch.setattr("src.plugins.host.page_owner.listed", fake_listed)
    assert page_owner.owner_of("app:/static/popout.html?tab=cplug-linearsync-linear").id == "linearsync"
    assert page_owner.owner_of("app:/static/popout.html?tab=cplug-nopopout") is None


def test_security_headers_and_view_csp_invariants_preserved():
    assert ("/api/v1/cplugs/devwidgetlab/draft-harness/", "devwidgetlab") in security_headers.dev_frameable_entries()
    assert "/api/v1/cplugs/devwidgetlab/draft-harness/" in security_headers.dev_frameable_prefixes()
    assert not hasattr(security_headers, "DRAFT_PLUGIN_ID")
    assert not hasattr(security_headers, "DRAFT_HARNESS_PREFIX")
    assert "/static/popout.html" in security_headers.SELF_FRAMEABLE_PATHS
    directives = dict(security_headers.CSP_DIRECTIVES)
    assert directives["default-src"] == "'self'"
    assert directives["script-src"] == "'self'"
    assert directives["frame-ancestors"] == "'none'"
    view_csp = security_headers.build_view_csp("https://example.invalid")
    assert "default-src 'none'" in view_csp
    assert "script-src https://example.invalid" in view_csp
    assert "connect-src 'none'" in view_csp
    assert "frame-ancestors 'self'" in view_csp
    assert "sandbox allow-scripts" in view_csp


def test_ui_doc_validate_slot_entry_widget_grammar():
    for valid_widget in (
        "linear-sync.issues:panel-lin12345",
        "huddle.chat:agent:7",
        "my-plug.panel:panel-12345678",
        "core.tasks",
    ):
        res = ui_doc.validate_slot_entry(
            {"id": "w1", "label": "Open Widget", "widget": valid_widget},
            routes=(),
            tools=(),
        )
        assert res["widget"] == valid_widget

    for bad_widget in (
        "javascript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "http://evil.example/x",
        "https://evil.example/x",
        "my-plug.panel",
        "my-plug.panel:../escape",
        "my-plug.panel:bad space",
        "core.notes:t",
        "MyPlug.panel:panel-1",
        "",
    ):
        with pytest.raises(ui_doc.UiDocError):
            ui_doc.validate_slot_entry(
                {"id": "w1", "label": "Bad Widget", "widget": bad_widget},
                routes=(),
                tools=(),
            )


def test_page_owner_handles_page_plus_idless_and_empty_sidebar_tab(monkeypatch):
    def _make_combo(sidebar_tab_decl: dict):
        return parse_manifest_v2(
            {
                "schema": 2,
                "id": "comboplug",
                "name": "Combo",
                "description": "D",
                "author": "A",
                "version": "1.0.0",
                "kind": "plugin",
                "ui": {
                    "views": [
                        {"name": "menu", "surfaces": ["panel"], "files": ["index.html"]},
                        {"name": "main", "surfaces": ["panel"], "files": ["index.html"]},
                    ],
                    "page": {"menu": "menu", "main": "main", "popout": True},
                    "sidebar_tab": sidebar_tab_decl,
                },
            }
        )

    m_none = _make_combo({"title": "Extra", "popout": True, "mode": "declarative"})
    monkeypatch.setattr(
        "src.plugins.host.page_owner.listed",
        lambda: [SimpleNamespace(id="comboplug", manifest=m_none)],
    )
    assert page_owner.owner_of("app:/static/popout.html?tab=cplug-comboplug-tab").id == "comboplug"
    assert page_owner.owner_of("app:/static/popout.html?tab=cplug-comboplug").id == "comboplug"

    m_empty = SimpleNamespace(
        ui_meta={"sidebar_tab": {"id": "", "title": "Extra", "popout": True}},
        page={"menu": "menu", "main": "main", "popout": True},
    )
    monkeypatch.setattr(
        "src.plugins.host.page_owner.listed",
        lambda: [SimpleNamespace(id="comboplug", manifest=m_empty)],
    )
    assert page_owner.owner_of("app:/static/popout.html?tab=cplug-comboplug-tab").id == "comboplug"


def test_browsers_pages_integration_with_sidecar_registry_and_idless_sidebar_tab(tmp_path: Path):
    state_dir = tmp_path / "state"
    code_dir = state_dir / "plugins" / "comboplug"
    (code_dir / "views" / "menu").mkdir(parents=True)
    (code_dir / "views" / "main").mkdir(parents=True)
    (code_dir / "views" / "menu" / "index.html").write_text("<html><body>menu</body></html>", encoding="utf-8")
    (code_dir / "views" / "main" / "index.html").write_text("<html><body>main</body></html>", encoding="utf-8")
    (code_dir / "carnivore.toml").write_text(
        """
schema = 2
id = "comboplug"
name = "Combo Plug"
version = "1.0.0"
kind = "plugin"
description = "Combo plugin"
author = "Alice"

[[ui.views]]
name = "menu"
surfaces = ["panel"]
files = ["index.html"]

[[ui.views]]
name = "main"
surfaces = ["panel"]
files = ["index.html"]

[ui.page]
menu = "menu"
main = "main"
popout = true

[ui.sidebar_tab]
title = "Extra Tab"
popout = true
mode = "declarative"
""",
        encoding="utf-8",
    )
    identity.register_install(state_dir, "comboplug", "acme/comboplug", frozenset(), publisher_key_id="pubk1")
    ledger_rows = [SimpleNamespace(item_id="acme/comboplug", kind="cplug", source_index_url="https://warez.invalid/index.json", publisher_key_id="pubk1")]
    reg = SidecarRegistry(state_dir, lambda: ledger_rows)
    assert reg.reload() == 1

    prev_reg = sidecar_registry.current()
    open_pages.reset_for_test()
    try:
        sidecar_registry.install(reg)
        host = host_runtime.Host(state_dir)
        app = FastAPI()
        app.state.cplugs_host = host
        app.include_router(browser_open_routes.router, prefix="/api/v1")
        app.dependency_overrides[require_auth] = lambda: True
        client = TestClient(app)

        app_open.open_app_page("/static/popout.html?tab=cplug-comboplug-tab", "Combo Tab")
        assert client.get("/api/v1/browsers/pages").json()["pages"] == []

        d = sidecar_registry.find("comboplug")
        assert d is not None
        owner_state.update(state_dir, d.manifest, None, lambda st: type(st)(**{**st.__dict__, "enabled": True}))
        pages = client.get("/api/v1/browsers/pages").json()["pages"]
        assert len(pages) == 1
        assert pages[0]["title"] == "Combo Tab"
        assert pages[0]["section"] is None
    finally:
        sidecar_registry.install(prev_reg)
        open_pages.reset_for_test()
