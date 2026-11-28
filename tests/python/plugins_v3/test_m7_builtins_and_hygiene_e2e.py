
from __future__ import annotations

import ast
import functools
import json
import re
import sqlite3
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List

import pytest

from src import security_headers
from src.core.catalog import client as catalog_client
from src.core.db_migration import ensure_db_migrated
from src.core.skills import kinds
from src.plugins import registry
from src.plugins.host import (
    owner_switch,
    registry_boot,
    registry_store,
    runtime as host_runtime,
    state as owner_state,
)
from src.plugins.host.mcp_health_port import HostMcpHealth
from src.plugins.sdk import mcp_health as mcp_health_sdk, ports
from src.plugins.sdk.manifest_v2 import load_manifest_v2
from tests.helpers.catalog_surface import (
    FIXTURE_COMMIT,
    FIXTURE_REPO,
    build_skill,
    publish_index,
    serve_archive,
    skill_item,
)
from tests.helpers.minisign_keys import Keypair, minisign_binary
from tests.helpers.plugins_v3_e2e_world import DARWIN_SANDBOX, build_plugins_v3_world
from tests.python.api_keys.conftest import key_store, owner_jwt  # noqa: F401

REPO_ROOT = Path(__file__).resolve().parents[3]
MCPHEALTH_PKG = REPO_ROOT / "packages" / "cplugs" / "mcphealth"

EXPECTED_12_BUILTINS = (
    "argent",
    "crate",
    "devwidgetlab",
    "flow",
    "reviewboard",
    "save",
    "sessionchat",
    "share",
    "taskmanager",
    "timemachine",
    "tmdevtools",
    "unread",
)

DELETED_LEGACY_PATHS = (
    "src/cplugs",
    "src/plugins/sdk/sidecar.py",
    "src/plugins/host/sidecar_manifest.py",
    "src/core/catalog/plugin_pack.py",
    "src/plugins/host/registry_files.py",
    "src/plugins/host/registry_projection.py",
    "src/plugins/host/registry_migration.py",
    "hosted/catalog/api/validate_cplug.py",
    "web/src/plugins/save/SessionTab.svelte",
)


def _create_sqlite_sentinel(path: Path, table: str, row_id: str) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(f"CREATE TABLE IF NOT EXISTS {table} (id TEXT PRIMARY KEY, note TEXT)")
        conn.execute(f"INSERT OR REPLACE INTO {table} (id, note) VALUES (?, ?)", (row_id, "preserve-sentinel"))
        conn.commit()
    finally:
        conn.close()
    return path.read_bytes()


def _read_sqlite_note(path: Path, table: str, row_id: str) -> str:
    conn = sqlite3.connect(str(path))
    try:
        row = conn.execute(f"SELECT note FROM {table} WHERE id = ?", (row_id,)).fetchone()
        return str(row[0]) if row else ""
    finally:
        conn.close()


def _load_keypair(directory: Path) -> Keypair:
    pub = directory / "catalog.pub"
    sec = directory / "catalog.key"
    return Keypair(pub_path=pub, sec_path=sec, public_key_text=pub.read_text(encoding="utf-8"))


def _string_literals_in_code(py_path: Path) -> List[str]:
    tree = ast.parse(py_path.read_text(encoding="utf-8"))
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                docstrings.add(id(first.value))
    out: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            out.append(node.value)
    return out


def test_12_shipped_builtins_boot_rename_3260_timeline_2951_blocked_by_and_popout_csp(
    tmp_path: Path,
    owner_jwt: str,  # noqa: F811
    key_store: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    discovered_folders = tuple(sorted(registry.plugin_folders()))
    assert discovered_folders == EXPECTED_12_BUILTINS

    loaded_ids = tuple(sorted(d.id for d in registry.CPLUGS))
    assert loaded_ids == EXPECTED_12_BUILTINS
    host_runtime.check_definitions(registry.CPLUGS)

    for pid in EXPECTED_12_BUILTINS:
        folder = registry.PLUGINS_ROOT / pid
        assert (folder / "carnivore.toml").is_file()
        assert not (folder / "cplug.json").exists()
        assert not (folder / "carnivore.json").exists()
        expected_tier = "dev" if pid in ("devwidgetlab", "tmdevtools") else "builtin"
        v2 = load_manifest_v2(folder, expected_id=pid, tier=expected_tier, expected_tier=expected_tier)
        assert v2.id == pid

    reg_literals = _string_literals_in_code(REPO_ROOT / "src" / "plugins" / "registry.py")
    boot_literals = _string_literals_in_code(REPO_ROOT / "src" / "plugins" / "host" / "sidecar_boot.py")
    for forbidden in (*EXPECTED_12_BUILTINS, "mcphealth", "huddle", "MCP_HEALTH_ID", "DRAFT_PLUGIN_ID"):
        assert forbidden not in reg_literals, f"hardcoded plugin id {forbidden!r} found in registry.py"
        assert forbidden not in boot_literals, f"hardcoded plugin id {forbidden!r} found in sidecar_boot.py"

    state = tmp_path / "state"
    huddle_db = state / "cplugs" / "huddle" / "huddle.db"
    huddle_bytes = _create_sqlite_sentinel(huddle_db, "legacy_items", "row1")
    timeline_db = state / "pipeline-plugins" / "timeline.db"
    timeline_bytes = _create_sqlite_sentinel(timeline_db, "timeline_events", "ev1")
    sc_timeline_db = state / "cplugs" / "sessionchat" / "timeline.db"
    sc_timeline_bytes = _create_sqlite_sentinel(sc_timeline_db, "sc_events", "ev2")

    with build_plugins_v3_world(tmp_path, owner_jwt, key_store, monkeypatch) as world:
        r_list = world.client.get("/api/v1/cplugs", headers=world.owner_headers)
        assert r_list.status_code == 200, r_list.text
        rows_by_id = {row["id"]: row for row in r_list.json()["cplugs"]}
        assert set(EXPECTED_12_BUILTINS).issubset(rows_by_id)

        tm_def = host_runtime.find("taskmanager")
        assert tm_def is not None and tm_def.manifest.renamed_from == "huddle"
        assert any(t.startswith("task_manager_") for t in tm_def.manifest.surfaces.mcp_tools)
        assert any(t.startswith("task_manager_") for t in tm_def.tools)
        assert world.host.storage("taskmanager").previous_path == state / "cplugs" / "huddle"
        r_huddle = world.client.get("/api/v1/cplugs/huddle", headers=world.owner_headers)
        assert r_huddle.status_code == 200
        assert r_huddle.json()["id"] == "taskmanager"
        assert huddle_db.read_bytes() == huddle_bytes
        assert _read_sqlite_note(huddle_db, "legacy_items", "row1") == "preserve-sentinel"

        sc_row = rows_by_id["sessionchat"]
        assert sc_row["enabled"] is False
        assert sc_row["state"] == "disabled"
        assert timeline_db.read_bytes() == timeline_bytes
        assert sc_timeline_db.read_bytes() == sc_timeline_bytes

        for dep_id in ("flow", "reviewboard"):
            cur = world.client.get(f"/api/v1/cplugs/{dep_id}", headers=world.owner_headers).json()
            r_en = world.client.put(
                f"/api/v1/cplugs/{dep_id}",
                json={
                    "revision": cur["revision"],
                    "enabled": True,
                    "grants": {"app": list(cur["permissions"]["app"])},
                },
                headers=world.owner_headers,
            )
            assert r_en.status_code == 200, r_en.text
            assert r_en.json()["state"] == "active"

        tm_row = world.client.get("/api/v1/cplugs/taskmanager", headers=world.owner_headers).json()
        r_tm_off_409 = world.client.put(
            "/api/v1/cplugs/taskmanager",
            json={"revision": tm_row["revision"], "enabled": False},
            headers=world.owner_headers,
        )
        assert r_tm_off_409.status_code == 409
        assert r_tm_off_409.json()["detail"]["code"] == "has_dependents"
        assert set(r_tm_off_409.json()["detail"]["dependents"]) >= {"flow", "reviewboard"}

        r_tm_off = world.client.put(
            "/api/v1/cplugs/taskmanager",
            json={"revision": tm_row["revision"], "enabled": False, "confirm_dependents": True},
            headers=world.owner_headers,
        )
        assert r_tm_off.status_code == 200, r_tm_off.text

        for dep_id in ("flow", "reviewboard"):
            gated = world.client.get(f"/api/v1/cplugs/{dep_id}", headers=world.owner_headers).json()
            assert gated["blocked_by"] == ["taskmanager"]
            assert gated["state"] == "inert"

        tm_row2 = world.client.get("/api/v1/cplugs/taskmanager", headers=world.owner_headers).json()
        r_tm_on = world.client.put(
            "/api/v1/cplugs/taskmanager",
            json={"revision": tm_row2["revision"], "enabled": True},
            headers=world.owner_headers,
        )
        assert r_tm_on.status_code == 200, r_tm_on.text
        for dep_id in ("flow", "reviewboard"):
            active = world.client.get(f"/api/v1/cplugs/{dep_id}", headers=world.owner_headers).json()
            assert active["blocked_by"] == []
            assert active["state"] == "active"

        assert _read_sqlite_note(huddle_db, "legacy_items", "row1") == "preserve-sentinel"
        backups = list((state / "cplugs" / "huddle").glob("huddle.db.pre-work-import-*"))
        assert len(backups) == 1 and _read_sqlite_note(backups[0], "legacy_items", "row1") == "preserve-sentinel"
        assert timeline_db.read_bytes() == timeline_bytes
        assert sc_timeline_db.read_bytes() == sc_timeline_bytes

        assert rows_by_id["flow"]["popout"] is True
        assert rows_by_id["reviewboard"]["popout"] is True
        assert rows_by_id["taskmanager"]["popout"] == {"enabled": True, "multi": True}
        assert "/static/popout.html" in security_headers.SELF_FRAMEABLE_PATHS
        assert dict(security_headers.CSP_DIRECTIVES)["frame-ancestors"] == "'none'"
        view_csp = security_headers.build_view_csp("https://127.0.0.1:8000")
        assert "frame-ancestors 'self'" in view_csp
        assert "sandbox allow-scripts" in view_csp


@pytest.mark.skipif(not DARWIN_SANDBOX, reason="needs macOS sandbox-exec and framework Python")
def test_catalog_mcphealth_sidecar_real_sandbox_boot_stamp_and_clean_disable(
    tmp_path: Path,
    owner_jwt: str,  # noqa: F811
    key_store: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if minisign_binary() is None:
        pytest.skip("minisign binary not found: brew install minisign")

    mcphealth_files = {
        p.relative_to(MCPHEALTH_PKG).as_posix(): p.read_bytes()
        for p in sorted(MCPHEALTH_PKG.rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts
    }
    assert "carnivore.toml" in mcphealth_files and "mcphealth_main.py" in mcphealth_files

    with build_plugins_v3_world(tmp_path, owner_jwt, key_store, monkeypatch) as world:
        assert world.client.portal is not None
        cert_pem = tmp_path / "tls" / "static_http_cert.pem"
        world.client.portal.call(functools.partial(catalog_client.init, verify=str(cert_pem)))
        try:
            index_kp = _load_keypair(tmp_path / "keys" / "k-index")
            publisher_kp = _load_keypair(tmp_path / "keys" / "k-publisher")

            pkg = build_skill(
                tmp_path / "pub_pkg",
                publisher="carnivore",
                name="mcphealth",
                files=mcphealth_files,
                repo=FIXTURE_REPO,
                commit=FIXTURE_COMMIT,
                folder=kinds.archive_folder(kinds.KIND_CPLUG),
            )
            served_root = tmp_path / "served"
            serve_archive(served_root, pkg.tar_bytes, repo=FIXTURE_REPO, commit=FIXTURE_COMMIT)
            item = skill_item(
                "mcphealth",
                "carnivore",
                pkg.digest,
                version="1.0.1",
                scripts=0,
                kind=kinds.KIND_CPLUG,
                repo=FIXTURE_REPO,
                path=f"{kinds.archive_folder(kinds.KIND_CPLUG)}/carnivore/mcphealth",
                commit=FIXTURE_COMMIT,
            )
            sign_work = tmp_path / "sign_work"
            sign_work.mkdir(parents=True, exist_ok=True)
            publish_index(
                sign_work,
                served_root,
                index_keypair=index_kp,
                publisher_keypair=publisher_kp,
                items=[item],
                publisher_handle="carnivore",
            )
            r_ref = world.client.post("/api/v1/catalog/refresh", headers=world.owner_headers)
            assert r_ref.status_code == 200, r_ref.text

            r_prev = world.client.post(
                "/api/v1/catalog/install/preview",
                json={"item_id": "carnivore/mcphealth", "scope": "global"},
                headers=world.owner_headers,
            )
            assert r_prev.status_code == 200, r_prev.text
            sheet = r_prev.json()
            r_inst = world.client.post(
                "/api/v1/catalog/install",
                json={
                    "item_id": "carnivore/mcphealth",
                    "scope": "global",
                    "plan_token": sheet["plan_token"],
                    "consent": {
                        "digest": sheet["digest"],
                        "body_sha": sheet["body_sha"],
                        "scripts": True,
                        "cplug_accepted": True,
                        "cplug_facts_sha": sheet["cplug_facts_sha"],
                    },
                },
                headers=world.owner_headers,
            )
            assert r_inst.status_code == 200, r_inst.text

            world.rt.supervisor.override_index("mcphealth", True)
            _rev, _c_sheet, put_body = world.consent_for("mcphealth", grant_all=True)
            r_en = world.client.put("/api/v1/cplugs/mcphealth", json=put_body, headers=world.owner_headers)
            assert r_en.status_code == 200, r_en.text
            assert r_en.json()["state"] == "active"

            port = world.rt.mcp_health
            assert isinstance(port, HostMcpHealth)
            assert ports.get(mcp_health_sdk.PORT_NAME) is port
            proc = world.client.portal.call(world.rt.supervisor.ensure, "mcphealth")
            assert proc is not None and proc.ended is None

            stamped = port.stamp(world.app.state, [], datetime.now(timezone.utc))
            assert stamped == []
            world.client.portal.call(port.refresh)
            assert isinstance(port._document, dict)
            assert port._document.get("data", {}).get("sessions") == {}

            cur_rev = world.client.get("/api/v1/cplugs/mcphealth", headers=world.owner_headers).json()["revision"]
            r_dis = world.client.put(
                "/api/v1/cplugs/mcphealth",
                json={"revision": cur_rev, "enabled": False},
                headers=world.owner_headers,
            )
            assert r_dis.status_code == 200, r_dis.text
            assert world.rt.mcp_health is None
            assert ports.get(mcp_health_sdk.PORT_NAME) is None
            assert world.rt.supervisor.process("mcphealth") is None
        finally:
            world.client.portal.call(catalog_client.shutdown)


def test_legacy_deletions_two_member_plugin_surface_and_doc_links_resolve() -> None:
    for rel in DELETED_LEGACY_PATHS:
        target = REPO_ROOT / rel
        assert not target.exists(), f"deleted legacy artifact reappeared: {target}"

    types_ts = (REPO_ROOT / "web" / "src" / "lib" / "plugins" / "types.ts").read_text(encoding="utf-8")
    match = re.search(r"export\s+type\s+PluginSurface\s*=\s*([^;]+);", types_ts, re.MULTILINE)
    assert match is not None, "PluginSurface union missing in web/src/lib/plugins/types.ts"
    members = re.findall(r"'([^']+)'", match.group(1))
    assert members == ["session-card-action", "settings-panel"]

    guide = REPO_ROOT / "docs" / "plugin-creation-guide.md"
    guide_text = guide.read_text(encoding="utf-8")
    links = re.findall(r"\[[^\]]+\]\(([^)]+)\)", guide_text)
    assert links, "expected internal links in docs/plugin-creation-guide.md"
    for href in links:
        if href.startswith(("http://", "https://", "#")):
            continue
        rel_path = href.split("#", 1)[0]
        resolved = (guide.parent / rel_path).resolve()
        assert resolved.exists(), f"broken internal link {href!r} in {guide}"


def test_registry_atomic_persistence_tmp_recovery_and_pre_v2_migration(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    ensure_db_migrated(state, 4, "0.8.2")

    out = registry_boot.run(state, retired=lambda: None)
    assert out.action == registry_boot.A_NORMAL
    reg_path = registry_store.registry_path(state)
    lock_path = registry_store.lock_path(state)
    assert reg_path.is_file()
    assert stat.S_IMODE(reg_path.stat().st_mode) == registry_store.REGISTRY_FILE_MODE
    assert stat.S_IMODE(lock_path.stat().st_mode) == 0o600

    registry_store.commit(
        state,
        lambda doc: doc["items"].__setitem__(
            "demo",
            {"kind": "plugin", "enabled": True, "grants": ["notify"], "settings": {}, "revision": 1},
        ),
    )
    owner_switch.write(state, True)
    bak_path = reg_path.with_suffix(".json.bak")
    assert bak_path.is_file()

    stale_tmp = reg_path.with_name("registry.json.tmp-crash-12345")
    stale_tmp.write_text('{"schema": 2, "corrupt": ', encoding="utf-8")
    out_with_tmp = registry_boot.run(state, retired=lambda: None)
    assert out_with_tmp.action == registry_boot.A_NORMAL
    assert owner_state.stored_enabled(state, "demo") is True

    reg_path.write_text("{truncated-after-crash", encoding="utf-8")
    alerts: List[tuple] = []
    recovered = registry_boot.run(state, retired=lambda: None, alert=lambda *a, **kw: alerts.append((a, kw)))
    assert recovered.action == registry_boot.A_RESTORED
    doc_after, status = registry_store.load_registry(state)
    assert status == registry_store.STATUS_OK and doc_after is not None
    assert doc_after["items"]["demo"]["enabled"] is True

    state2 = tmp_path / "state_v1"
    state2.mkdir()
    ensure_db_migrated(state2, 4, "0.8.2")
    reg_v1 = registry_store.registry_path(state2)
    reg_v1.parent.mkdir(parents=True, exist_ok=True)
    reg_v1.write_text(
        json.dumps(
            {
                "schema": 1,
                "generation": 7,
                "switches": {"third_party": True, "sideload": {"enabled_at": None, "hours": 12, "expires_at": None}},
                "items": {
                    "legacy_item": {
                        "kind": "plugin",
                        "install_uuid": "u-leg-1",
                        "catalog_id": "acme/legacy",
                        "enabled": True,
                        "grants": ["sessions.read"],
                        "settings": {"x": 1},
                        "revision": 3,
                    }
                },
                "tombstones": {},
            }
        ),
        encoding="utf-8",
    )
    mig_out = registry_boot.run(state2, retired=lambda: None)
    assert mig_out.action == registry_boot.A_NORMAL
    migrated = json.loads(reg_v1.read_text(encoding="utf-8"))
    assert migrated["schema"] == 2
    assert migrated["migration"]["version"] == 2
    assert migrated["generation"] == 8
    assert migrated["switches"]["third_party"] is True
    assert migrated["items"]["legacy_item"]["enabled"] is True
    assert migrated["items"]["legacy_item"]["settings"] == {"x": 1}
