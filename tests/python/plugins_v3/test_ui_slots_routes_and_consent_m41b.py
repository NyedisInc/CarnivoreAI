
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.core.resource_push import topics
from src.plugins.host import (
    activity_log,
    inspector_telemetry,
    owner_switch,
    routes as host_routes,
    runtime as host_runtime,
    sidecar_registry,
    state as owner_state,
    ui_doc,
    ui_slots,
)
from src.plugins.host.plugin_manifest import load_sidecar_manifest
from src.plugins.host.sidecar_registry import SidecarDefinition
from src.plugins.sdk.definition import CplugDefinition
from src.plugins.sdk.manifest import Manifest, Surfaces
from tests.python.api_keys.conftest import bearer, key_store, owner_jwt  # noqa: F401
from tests.python.plugins_v3.test_github_install_17a import OWNER_REPO, _init_bare_repo, _wire_bare_github, gh_world  # noqa: F401


def _write_slot_plugin(
    code_dir: Path,
    plugin_id: str,
    *,
    tier: str = "catalog",
    slots: List[str] | None = None,
    contribute: Dict[str, Any] | None = None,
    routes: List[str] | None = None,
    permission_reasons: Dict[str, str] | None = None,
    include_channel: bool = False,
) -> None:
    code_dir.mkdir(parents=True, exist_ok=True)
    perms: Dict[str, Any] = {
        "app": ["notify"],
        "reasons": {
            "notify": "show status",
            "events:session.started": "Listen to session events",
            f"events:{plugin_id}:ready": "Emit ready event",
            **(permission_reasons or {}),
        },
    }
    if include_channel:
        perms["network"] = [{"host": "example.com", "methods": ["POST"], "paths": ["/hook"], "reason": "Send webhook"}]
    raw: Dict[str, Any] = {
        "schema": 2,
        "id": plugin_id,
        "name": f"Plugin {plugin_id}",
        "version": "1.0.0",
        "kind": "plugin",
        "description": "Slot test plugin",
        "author": "Tester",
        "run": {"cmd": ["python3", "main.py"], "mode": "rpc"},
        "permissions": perms,
        "ui": {
            "routes": routes or ["ping"],
            "commands": [{"id": "open_panel", "title": "Open Panel", "shortcut": "Cmd+Shift+P"}],
            "session_badge": {"id": "sess_badge", "label": "PR"},
        },
        "services": {"provides": [{"name": f"{plugin_id}.api", "methods": ["ping"]}], "consumes": []},
        "events": {"on": ["session.started"], "emit": [f"{plugin_id}:ready"]},
        "harnesses": ["rules.toml"],
    }
    if include_channel:
        raw["channels"] = {"ops": {"url": "https://example.com/hook", "label": "Ops Hook"}}
    if slots:
        raw["ui"]["slots"] = slots
    if contribute:
        raw["ui"]["contribute"] = contribute
    (code_dir / "carnivore.json").write_text(json.dumps(raw), encoding="utf-8")
    (code_dir / "main.py").write_text("# stub\n", encoding="utf-8")
    (code_dir / "rules.toml").write_text(
        'id = "customagent"\nnames = ["customagent"]\n',
        encoding="utf-8",
    )


def _sidecar_def(code_dir: Path, state_dir: Path, plugin_id: str, *, item_id: str | None = None) -> SidecarDefinition:
    manifest = load_sidecar_manifest(code_dir, plugin_id)
    install_key = f"inst-{plugin_id}"
    data_dir = state_dir / "cplugs" / install_key
    (data_dir / "files").mkdir(parents=True, exist_ok=True)
    return SidecarDefinition(
        manifest=manifest,
        item_id=item_id or f"acme/{plugin_id}",
        install_key=install_key,
        code_root=code_dir,
        folder=data_dir,
    )


def _build_test_app(state_dir: Path, defs: List[SidecarDefinition], monkeypatch: pytest.MonkeyPatch) -> tuple[FastAPI, List[str]]:
    published: List[str] = []
    app = FastAPI()
    app.dependency_overrides[require_auth] = lambda: {"sub": "owner"}
    app.include_router(host_routes.router, prefix="/api/v1")
    host = host_runtime.Host(state_dir, app=app, publish=published.append)
    app.state.cplugs_host = host
    owner_switch.write(state_dir, True)
    by_id = {d.id: d for d in defs}
    fake_reg = SimpleNamespace(listed=lambda: list(defs), find=lambda pid: by_id.get(pid))
    monkeypatch.setattr(sidecar_registry, "current", lambda: fake_reg)
    monkeypatch.setattr(sidecar_registry, "find", lambda pid: by_id.get(pid))
    monkeypatch.setattr(host_runtime, "listed", lambda: tuple(defs))
    monkeypatch.setattr(host_runtime, "find", lambda pid: by_id.get(pid))
    return app, published


def test_ui_doc_validate_slot_entry_valid_and_refusals() -> None:
    valid_action = ui_doc.validate_slot_entry(
        {"id": "run", "label": "Run Ping", "route": "ping", "icon": "play", "href": "https://docs.example.com/run"},
        routes=("ping",),
        tools=("echo",),
    )
    assert valid_action["route"] == "ping"
    assert valid_action["href"] == "https://docs.example.com/run"

    valid_doc = ui_doc.validate_slot_entry(
        {
            "id": "panel",
            "label": "Health",
            "document": {"schema": 2, "root": {"type": "text", "value": "OK"}},
        },
        routes=("ping",),
        tools=(),
    )
    assert valid_doc["document"]["root"]["value"] == "OK"

    with pytest.raises(ui_doc.UiDocError) as e_js:
        ui_doc.validate_slot_entry({"id": "x", "href": "javascript:alert(1)"}, routes=(), tools=())
    assert e_js.value.code == "link_not_allowed"

    with pytest.raises(ui_doc.UiDocError) as e_rt:
        ui_doc.validate_slot_entry({"id": "x", "route": "undeclared"}, routes=("ping",), tools=())
    assert e_rt.value.code == "action_not_declared"

    with pytest.raises(ui_doc.UiDocError) as e_macro_empty:
        ui_doc.validate_slot_entry({"id": "x", "macro": "undeclared_macro"}, routes=(), tools=(), macros=())
    assert e_macro_empty.value.code == "action_not_declared"
    assert e_macro_empty.value.path == "/slot/macro"

    valid_macro = ui_doc.validate_slot_entry({"id": "x", "macro": "run_check"}, routes=(), tools=(), macros=("run_check",))
    assert valid_macro["macro"] == "run_check"

    with pytest.raises(ui_doc.UiDocError) as e_inv:
        ui_doc.validate_slot_entry({"id": "x", "label": "bad\u202etext"}, routes=(), tools=())
    assert e_inv.value.code == "invisible_character"

    with pytest.raises(ui_doc.UiDocError) as e_doc:
        ui_doc.validate_slot_entry(
            {"id": "p", "document": {"schema": 2, "root": {"type": "script", "value": "x"}}},
            routes=(),
            tools=(),
        )
    assert e_doc.value.code == "unknown_node"

    with pytest.raises(ui_doc.UiDocError) as e_unk:
        ui_doc.validate_slot_entry({"id": "x", "evil_html": "<b>no</b>"}, routes=(), tools=())
    assert e_unk.value.code == "unknown_field"


def test_cplug_row_exposes_universal_metadata_for_builtin_and_sidecar(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    code_dir = tmp_path / "code" / "slotplug"
    _write_slot_plugin(
        code_dir,
        "slotplug",
        slots=["slotplug.detail"],
        contribute={
            "terminal.toolbar": [{"id": "tb", "label": "TB", "route": "ping"}],
            "session.row_actions": [{"id": "ra", "label": "Row Act", "route": "ping"}],
            "session.badges": [{"id": "sb", "label": "Badge"}],
            "project.panels": [{"id": "pp", "label": "Proj Panel"}],
        },
        permission_reasons={"ui.slot:terminal.toolbar": "tb", "ui.slot:session.row_actions": "ra"},
        include_channel=True,
    )
    sd = _sidecar_def(code_dir, state_dir, "slotplug")
    owner_state.update(
        state_dir,
        sd.manifest,
        None,
        lambda st: replace(
            st,
            enabled=True,
            grants=("notify",),
            ui_slot_grants=("terminal.toolbar",),
            digest=sd.manifest.code_digest,
        ),
    )

    host = host_runtime.Host(state_dir, publish=lambda _t: None)
    row = host_routes.cplug_row(host, sd)
    assert row["grants"] == {"app": ["notify"], "ui_slots": ["terminal.toolbar"]}
    assert row["granted_ui_slots"] == ["terminal.toolbar"]
    assert row["services"] == {"provides": [{"name": "slotplug.api", "methods": ["ping"]}], "consumes": []}
    assert row["events"]["on"] == ["session.started"]
    assert row["events"]["emit"] == ["slotplug:ready"]
    assert set(row["events"]["allowed"]) == {"session.started", "slotplug:ready"}
    assert row["ui_slots"] == ["slotplug.detail"]
    assert "terminal.toolbar" in row["ui_contribute"]
    assert row["commands"][0]["id"] == "open_panel"
    assert row["chords"] == [{"command": "open_panel", "shortcut": "Cmd+Shift+P"}]
    assert row["session_row_actions"][0]["id"] == "ra"
    assert len(row["session_badges"]) == 2
    assert row["terminal_toolbar"][0]["id"] == "tb"
    assert row["project_panels"][0]["id"] == "pp"
    assert row["channels"][0]["kind_id"] == "plugin:slotplug:ops"
    assert row["harnesses"] == ["rules.toml"]

    builtin_m = Manifest(
        id="builtinmod",
        name_key="cplug.builtinmod.name",
        description_key="cplug.builtinmod.description",
        version="1.0.0",
        icon="box",
        author="Core",
        min_app_version="1.0.0",
        tier="builtin",
        default_enabled=True,
        permissions=(),
        surfaces=Surfaces(),
        ui_slots=("builtinmod.zone",),
        ui_contribute={"terminal.toolbar": [{"id": "core_tb", "label": "Core TB"}]},
        ui_meta={"commands": [{"id": "core_cmd", "title": "Core", "shortcut": "Cmd+K"}], "popout": True},
        channels={"alerts": {"label": "Core Alerts"}},
        harnesses=("agent.toml",),
    )
    builtin_d = CplugDefinition(manifest=builtin_m)
    b_row = host_routes.cplug_row(host, builtin_d)
    assert b_row["commands"][0]["id"] == "core_cmd"
    assert b_row["chords"] == [{"command": "core_cmd", "shortcut": "Cmd+K"}]
    assert b_row["terminal_toolbar"][0]["id"] == "core_tb"
    assert b_row["popout"] is True
    assert b_row["channels"][0]["kind_id"] == "plugin:builtinmod:alerts"
    assert b_row["harnesses"] == ["agent.toml"]


def test_ui_slots_consent_routes_gating_and_slots_endpoint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    code_a = tmp_path / "code" / "slota"
    code_b = tmp_path / "code" / "slotb"

    _write_slot_plugin(
        code_a,
        "slota",
        slots=["slota.hostslot"],
        contribute={"terminal.toolbar": [{"id": "tbtn", "label": "A Btn", "route": "ping"}]},
        permission_reasons={"ui.slot:terminal.toolbar": "Add button to terminal toolbar"},
    )
    _write_slot_plugin(
        code_b,
        "slotb",
        contribute={"slota.hostslot": [{"id": "bitem", "label": "B Item", "route": "ping"}]},
        permission_reasons={"ui.slot:slota.hostslot": "Render in slota host slot"},
    )
    def_a = _sidecar_def(code_a, state_dir, "slota")
    def_b = _sidecar_def(code_b, state_dir, "slotb")
    app, published = _build_test_app(state_dir, [def_a, def_b], monkeypatch)

    client = TestClient(app)

    sheet_res = client.get("/api/v1/cplugs/slota/sheet")
    assert sheet_res.status_code == 200
    sheet = sheet_res.json()
    assert sheet["ui_slots"][0]["slot"] == "terminal.toolbar"
    assert sheet["ui_slots"][0]["needs_tick"] is True
    assert sheet["ui_slots"][0]["granted"] is False
    assert isinstance(sheet["ui_slots_sha"], str) and len(sheet["ui_slots_sha"]) == 64

    row_a = client.get("/api/v1/cplugs/slota").json()
    rev = row_a["revision"]
    perms_a = [p["name"] for p in sheet["permissions"]]
    ticks_a = [p["name"] for p in sheet["permissions"] if p["needs_tick"]]
    bad_mismatch = client.put(
        "/api/v1/cplugs/slota",
        json={
            "revision": rev,
            "enabled": True,
            "grants": {"app": perms_a, "ui_slots": ["terminal.toolbar"]},
            "consent": {
                "digest": sheet["digest"],
                "body_sha": sheet["body_sha"],
                "grants_sha": sheet["grants_sha"],
                "ticks": ticks_a,
            },
        },
    )
    assert bad_mismatch.status_code == 422
    assert bad_mismatch.json()["detail"]["code"] == "consent_mismatch"

    bad_tick = client.put(
        "/api/v1/cplugs/slota",
        json={
            "revision": rev,
            "enabled": True,
            "grants": {"app": perms_a, "ui_slots": ["terminal.toolbar"]},
            "consent": {
                "digest": sheet["digest"],
                "body_sha": sheet["body_sha"],
                "grants_sha": sheet["grants_sha"],
                "ticks": ticks_a,
                "ui_slots_sha": sheet["ui_slots_sha"],
                "slot_ticks": [],
            },
        },
    )
    assert bad_tick.status_code == 422
    assert bad_tick.json()["detail"]["code"] == "tick_missing"

    bad_unknown = client.put(
        "/api/v1/cplugs/slota",
        json={"revision": rev, "grants": {"app": perms_a, "ui_slots": ["unknown.slot"]}},
    )
    assert bad_unknown.status_code == 422
    assert bad_unknown.json()["detail"]["code"] == "grant_not_asked"

    ok_res = client.put(
        "/api/v1/cplugs/slota",
        json={
            "revision": rev,
            "enabled": True,
            "grants": {"app": perms_a, "ui_slots": ["terminal.toolbar"]},
            "consent": {
                "digest": sheet["digest"],
                "body_sha": sheet["body_sha"],
                "grants_sha": sheet["grants_sha"],
                "ticks": ticks_a,
                "ui_slots_sha": sheet["ui_slots_sha"],
                "slot_ticks": ["terminal.toolbar"],
            },
        },
    )
    assert ok_res.status_code == 200
    assert ok_res.json()["grants"]["ui_slots"] == ["terminal.toolbar"]
    assert topics.CPLUG_SLOTS in published

    sheet_b = client.get("/api/v1/cplugs/slotb/sheet").json()
    perms_b = [p["name"] for p in sheet_b["permissions"]]
    ticks_b = [p["name"] for p in sheet_b["permissions"] if p["needs_tick"]]
    rev_b = client.get("/api/v1/cplugs/slotb").json()["revision"]
    ok_b = client.put(
        "/api/v1/cplugs/slotb",
        json={
            "revision": rev_b,
            "enabled": True,
            "grants": {"app": perms_b, "ui_slots": ["slota.hostslot"]},
            "consent": {
                "digest": sheet_b["digest"],
                "body_sha": sheet_b["body_sha"],
                "grants_sha": sheet_b["grants_sha"],
                "ticks": ticks_b,
                "ui_slots_sha": sheet_b["ui_slots_sha"],
                "slot_ticks": ["slota.hostslot"],
            },
        },
    )
    assert ok_b.status_code == 200

    slots_res = client.get("/api/v1/cplugs/slots")
    assert slots_res.status_code == 200
    body = slots_res.json()
    assert body["owners"] == {"slota.hostslot": "slota"}
    assert body["slots"]["terminal.toolbar"][0]["plugin_id"] == "slota"
    assert body["slots"]["slota.hostslot"][0]["plugin_id"] == "slotb"

    rev_a2 = client.get("/api/v1/cplugs/slota").json()["revision"]
    off_res = client.put("/api/v1/cplugs/slota", json={"revision": rev_a2, "enabled": False})
    assert off_res.status_code == 200
    slots_after = client.get("/api/v1/cplugs/slots").json()
    assert slots_after["slots"] == {}
    assert slots_after["owners"] == {}


def test_ui_slot_dynamic_publish_rate_limit_audit_and_push(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    code_dir = tmp_path / "code" / "dynplug"
    _write_slot_plugin(
        code_dir,
        "dynplug",
        contribute={"terminal.toolbar": [{"id": "init", "label": "Init"}]},
        permission_reasons={"ui.slot:terminal.toolbar": "Toolbar"},
    )
    sd = _sidecar_def(code_dir, state_dir, "dynplug")
    owner_state.update(
        state_dir,
        sd.manifest,
        None,
        lambda st: replace(
            st,
            enabled=True,
            grants=("notify",),
            ui_slot_grants=("terminal.toolbar",),
            digest=sd.manifest.code_digest,
        ),
    )
    published: List[str] = []
    host = host_runtime.Host(state_dir, publish=published.append)
    now = [100.0]
    reg = ui_slots.UiSlotRegistry(state_dir, clock=lambda: now[0])

    updated = reg.publish(
        "dynplug",
        "terminal.toolbar",
        [{"id": "dyn1", "label": "Dynamic 1", "route": "ping"}],
        host=host,
        definitions=[sd],
    )
    assert updated[0]["id"] == "dyn1"
    assert topics.CPLUG_SLOTS in published
    resolved = reg.resolve(host=host, definitions=[sd])
    assert resolved["slots"]["terminal.toolbar"][0]["item"]["id"] == "dyn1"

    act = activity_log.ActivityLog(state_dir).recent(host.install_key("dynplug"), 10)
    assert any(r["method"] == "ui.slot.publish" and r["permission"] == "ui.slot:terminal.toolbar" and r["status"] == "ok" for r in act)
    telem_caps = inspector_telemetry.telemetry_for(state_dir).capability_checks("dynplug", 10)
    assert any(c["permission"] == "ui.slot:terminal.toolbar" and c["allowed"] is True for c in telem_caps)

    for _ in range(ui_slots.UI_SLOT_RATE_LIMIT - 1):
        reg.publish("dynplug", "terminal.toolbar", [{"id": "dyn", "label": "OK"}], host=host, definitions=[sd])
    with pytest.raises(ui_slots.UiSlotError) as exc_rate:
        reg.publish("dynplug", "terminal.toolbar", [{"id": "dyn", "label": "TooFast"}], host=host, definitions=[sd])
    assert exc_rate.value.code == "rate_limited"
    assert exc_rate.value.status == 429


def test_github_install_enforces_ui_slot_consent_and_persists_grants(
    tmp_path: Path, gh_world, monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    bare = _init_bare_repo(
        tmp_path,
        {
            "carnivore.json": json.dumps(
                {
                    "schema": 2,
                    "id": "ghslot",
                    "name": "GH Slot",
                    "version": "1.0.0",
                    "kind": "plugin",
                    "description": "GH slot consent test",
                    "author": "Tester",
                    "permissions": {
                        "app": ["notify"],
                        "reasons": {
                            "notify": "Notify user",
                            "ui.slot:terminal.toolbar": "Add button",
                        },
                    },
                    "ui": {
                        "contribute": {"terminal.toolbar": [{"id": "ghbtn", "label": "GH"}]},
                    },
                }
            )
        },
    )
    _wire_bare_github(monkeypatch, bare)
    published: List[str] = []
    monkeypatch.setattr(gh_world.app.state.cplugs_host, "publish", published.append)
    headers = gh_world.owner

    prev = gh_world.client.post("/api/v1/cplug-owner/github/preview", json={"source": OWNER_REPO}, headers=headers)
    assert prev.status_code == 200, prev.text
    pj = prev.json()
    sheet = pj["consent_sheet"]
    assert sheet["ui_slots"][0]["slot"] == "terminal.toolbar"

    missing_tick = gh_world.client.post(
        "/api/v1/cplug-owner/github/install",
        json={
            "source": OWNER_REPO,
            "enable": True,
            "consent": {
                "digest": sheet["digest"],
                "body_sha": sheet["body_sha"],
                "grants_sha": sheet["grants_sha"],
                "ticks": ["notify"],
                "ui_slots_sha": sheet["ui_slots_sha"],
                "slot_ticks": [],
            },
        },
        headers=headers,
    )
    assert missing_tick.status_code == 422
    assert missing_tick.json()["detail"]["code"] == "tick_missing"

    ok = gh_world.client.post(
        "/api/v1/cplug-owner/github/install",
        json={
            "source": OWNER_REPO,
            "enable": True,
            "consent": {
                "digest": sheet["digest"],
                "body_sha": sheet["body_sha"],
                "grants_sha": sheet["grants_sha"],
                "ticks": ["notify"],
                "ui_slots_sha": sheet["ui_slots_sha"],
                "slot_ticks": ["terminal.toolbar"],
            },
        },
        headers=headers,
    )
    assert ok.status_code == 200, ok.text
    assert topics.CPLUG_SLOTS in published
    defn = sidecar_registry.find("ghslot")
    assert defn is not None
    assert owner_state.granted_ui_slots(gh_world.state, defn.manifest) == ("terminal.toolbar",)


def test_ui_slot_registry_rejects_undeclared_macro_when_zero_macros_declared(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    code_dir = tmp_path / "code" / "macroplug"
    _write_slot_plugin(
        code_dir,
        "macroplug",
        contribute={"terminal.toolbar": [{"id": "evil", "label": "Evil", "macro": "undeclared_secret_macro"}]},
        permission_reasons={"ui.slot:terminal.toolbar": "Toolbar"},
    )
    sd = _sidecar_def(code_dir, state_dir, "macroplug")
    owner_state.update(
        state_dir,
        sd.manifest,
        None,
        lambda st: replace(
            st,
            enabled=True,
            grants=("notify",),
            ui_slot_grants=("terminal.toolbar",),
            digest=sd.manifest.code_digest,
        ),
    )
    host = host_runtime.Host(state_dir, publish=lambda _t: None)
    reg = ui_slots.UiSlotRegistry(state_dir)
    resolved = reg.resolve(host=host, definitions=[sd])
    assert resolved["slots"] == {}

    act = activity_log.ActivityLog(state_dir).recent(host.install_key("macroplug"), 10)
    assert any(r["method"] == "ui.slot.sync" and r["status"] == "invalid:action_not_declared" for r in act)

    sd_with_macro = replace(
        sd,
        manifest=replace(sd.manifest, macros={"declared_macro": {"steps": []}}),
    )
    (code_dir / "carnivore.json").write_text(
        json.dumps(
            {
                **json.loads((code_dir / "carnivore.json").read_text(encoding="utf-8")),
                "ui": {
                    "routes": ["ping"],
                    "contribute": {"terminal.toolbar": [{"id": "good", "label": "Good", "macro": "declared_macro"}]},
                },
            }
        ),
        encoding="utf-8",
    )
    sd_ok = replace(sd_with_macro, manifest=replace(load_sidecar_manifest(code_dir, "macroplug"), macros={"declared_macro": {"steps": []}}))
    owner_state.update(
        state_dir,
        sd_ok.manifest,
        None,
        lambda st: replace(
            st,
            enabled=True,
            grants=("notify",),
            ui_slot_grants=("terminal.toolbar",),
            digest=sd_ok.manifest.code_digest,
        ),
    )
    resolved_ok = reg.resolve(host=host, definitions=[sd_ok])
    assert resolved_ok["slots"]["terminal.toolbar"][0]["item"]["macro"] == "declared_macro"
