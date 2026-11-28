
from __future__ import annotations

import base64
import io
import json
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

import pytest

from src.api import catalog_cplug_gates
from src.core.catalog.permission_diff import compute_permission_diff
from src.core.plugin_studio import dev_session
from src.core.plugin_studio.errors import WorkspaceConflictError
from src.plugins.cli import install_publish
from src.plugins.host import (
    runtime as host_runtime,
    sidecar_registry,
    sideload_routes,
    state as owner_state,
)
from src.plugins.host.plugin_manifest import load_sidecar_manifest
from src.plugins.host.sidecar_registry import SidecarDefinition
from src.plugins.sdk import _settings_schema_fallback
from src.plugins.sdk.manifest_v2 import ManifestV2Error, parse_manifest_v2
from tests.helpers import hosted_catalog_fake as hcf
from tests.helpers import submissions_harness as sh
from tests.helpers.plugins_v3_e2e_world import DARWIN_SANDBOX, build_plugins_v3_world
from tests.helpers.plugins_v3_polyglot_fixtures import DEFAULT_MIT_LICENSE, write_plugin_files
from tests.python.api_keys.conftest import key_store, owner_jwt  # noqa: F401

REPO_ROOT = Path(__file__).resolve().parents[3]
WAREZ_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "cplugs" / "warezsmoke"


class _TestClientCliAdapter:

    def __init__(self, client: Any, headers: Dict[str, str]) -> None:
        self._client = client
        self._headers = headers

    def request(self, method: str, path: str, *, json_body: Optional[Dict[str, Any]] = None) -> Tuple[int, Any]:
        resp = self._client.request(method, path, json=json_body, headers=self._headers)
        try:
            data = resp.json()
        except ValueError:
            data = resp.text
        return resp.status_code, data


class _TtyStringIO(io.StringIO):

    def isatty(self) -> bool:
        return True


def _make_studio_plugin_files(plugin_id: str, marker: str) -> Dict[str, str]:
    toml = f"""
        schema = 2
        id = "{plugin_id}"
        name = "{plugin_id.title()}"
        version = "1.0.0"
        kind = "plugin"
        description = "Studio dev lock plugin"
        author = "Tester"
        license = "MIT"
        tier = "local"

        [run]
        cmd = ["python3", "main.py"]
        mode = "rpc"

        [mcp]
        [[mcp.tools]]
        name = "ping"
        description = "Return current marker"
        gate = "read"
        inputSchema = {{ type = "object", properties = {{}} }}
    """
    main_py = f"""
        from cplug_sdk import Plugin

        plugin = Plugin()

        @plugin.tool("ping", "Return current marker", {{"type": "object", "properties": {{}}}}, gate="read")
        async def ping(_args, _caller):
            return {{"marker": "{marker}"}}
    """
    return {"carnivore.toml": toml, "main.py": main_py, "LICENSE.md": DEFAULT_MIT_LICENSE}




def test_r2_bug1_cli_install_ui_slots_prompts_and_enables_with_slot_grants(
    tmp_path: Path,
    owner_jwt: str,  # noqa: F811
    key_store: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with build_plugins_v3_world(tmp_path, owner_jwt, key_store, monkeypatch, with_http_probe=False) as w:
        assert w.client.put("/api/v1/cplug-owner/switch", json={"enabled": True}, headers=w.owner_headers).status_code == 200
        assert w.client.put("/api/v1/cplug-owner/sideload/switch", json={"enabled": True}, headers=w.owner_headers).status_code == 200

        plug_dir = write_plugin_files(
            tmp_path / "slotplug_src",
            {
                "carnivore.toml": """
                    schema = 2
                    id = "slotcli"
                    name = "Slot CLI"
                    version = "1.0.0"
                    kind = "plugin"
                    description = "Plugin contributing UI slots"
                    author = "Tester"
                    license = "MIT"
                    tier = "local"

                    [permissions]
                    write = ["notify"]

                    [permissions.reasons]
                    notify = "Send slot test notification"
                    "ui.slot:commands" = "Register command palette actions"
                    "ui.slot:terminal.toolbar" = "Show toolbar button"

                    [ui.contribute]
                    commands = [{ id = "slotcli.hello", title = "Hello" }]
                    "terminal.toolbar" = [{ id = "slotcli.btn", label = "Run" }]
                """,
                "LICENSE.md": DEFAULT_MIT_LICENSE,
            },
        )
        cli = _TestClientCliAdapter(w.client, w.owner_headers)

        monkeypatch.setattr("sys.stdin", io.StringIO(""))
        rc_abort = install_publish.run_install(str(plug_dir), mode="local", client=cli, assume_yes=False, enable=True)
        captured_abort = capsys.readouterr()
        assert rc_abort == 2, captured_abort.err
        assert "commands" in captured_abort.err and "terminal.toolbar" in captured_abort.err
        row_before = w.client.get("/api/v1/cplugs/slotcli", headers=w.owner_headers).json()
        assert row_before["enabled"] is False
        assert row_before["grants"]["ui_slots"] == []

        monkeypatch.setattr("sys.stdin", _TtyStringIO("y\n"))
        rc_tty = install_publish.run_install(str(plug_dir), mode="local", client=cli, assume_yes=False, enable=True, as_json=True)
        captured_tty = capsys.readouterr()
        assert rc_tty == 0, captured_tty.err
        row_tty = w.client.get("/api/v1/cplugs/slotcli", headers=w.owner_headers).json()
        assert row_tty["enabled"] is True and row_tty["state"] == "active"
        assert row_tty["grants"]["ui_slots"] == ["commands", "terminal.toolbar"]
        defn = host_runtime.find("slotcli")
        assert defn is not None
        assert owner_state.granted_ui_slots(w.state, defn.manifest) == ("commands", "terminal.toolbar")

        (plug_dir / "README.md").write_text("Updated docs\n", encoding="utf-8")
        rc_yes = install_publish.run_install(str(plug_dir), mode="local", client=cli, assume_yes=True, enable=True, as_json=True)
        captured_yes = capsys.readouterr()
        assert rc_yes == 0, captured_yes.err
        row_after = w.client.get("/api/v1/cplugs/slotcli", headers=w.owner_headers).json()
        assert row_after["enabled"] is True and row_after["state"] == "active"
        assert row_after["grants"]["ui_slots"] == ["commands", "terminal.toolbar"]




@pytest.mark.skipif(not DARWIN_SANDBOX, reason="macOS sandbox-exec required")
def test_r2_bug2_studio_reload_once_serializes_with_dev_reload_and_tool_calls(
    tmp_path: Path,
    owner_jwt: str,  # noqa: F811
    key_store: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with build_plugins_v3_world(tmp_path, owner_jwt, key_store, monkeypatch, with_http_probe=False) as w:
        assert w.client.put("/api/v1/cplug-owner/sideload/switch", json={"enabled": True}, headers=w.owner_headers).status_code == 200
        src = write_plugin_files(tmp_path / "studiolock_src", _make_studio_plugin_files("studiolock", "v1"))
        w.sideload_and_enable(src, "studiolock")

        r_lease = w.client.post("/api/v1/cplug-owner/dev/lease", json={"path": str(src)}, headers=w.owner_headers)
        assert r_lease.status_code == 200, r_lease.text

        mgr = dev_session.manager_for(w.app)
        write_plugin_files(src, _make_studio_plugin_files("studiolock", "v2"))

        orig_commit = sideload_routes._commit_blocking
        commit_started = threading.Event()
        commit_gate = threading.Event()
        commit_calls = {"n": 0}

        def _paused_commit(state_dir: Path, source: Path, staged: Dict[str, Any]) -> list:
            commit_calls["n"] += 1
            if commit_calls["n"] == 1:
                commit_started.set()
                commit_gate.wait(timeout=3.0)
            return orig_commit(state_dir, source, staged)

        monkeypatch.setattr(sideload_routes, "_commit_blocking", _paused_commit)

        results: Dict[str, Tuple[int, Any]] = {}

        def _run_studio_reload() -> None:
            assert w.client.portal is not None
            res = w.client.portal.call(mgr.reload_once, "studio-1", "studiolock", src)
            results["studio"] = (200, res)

        def _run_dev_reload() -> None:
            resp = w.client.post(
                "/api/v1/cplug-owner/dev/reload",
                json={"path": str(src), "probe_ui": False},
                headers=w.owner_headers,
            )
            results["dev"] = (resp.status_code, resp.json())

        def _run_tool() -> None:
            resp = w.client.post(
                "/api/v1/cplug-owner/tool",
                json={"cplug_id": "studiolock", "tool": "ping", "args": {}},
                headers=w.owner_headers,
            )
            results["tool"] = (resp.status_code, resp.json())

        t_studio = threading.Thread(target=_run_studio_reload, daemon=True)
        t_studio.start()
        assert commit_started.wait(timeout=3.0)

        write_plugin_files(src, _make_studio_plugin_files("studiolock", "v3"))
        t_dev = threading.Thread(target=_run_dev_reload, daemon=True)
        t_tool = threading.Thread(target=_run_tool, daemon=True)
        t_dev.start()
        t_tool.start()
        time.sleep(0.1)
        commit_gate.set()

        t_studio.join(timeout=10.0)
        t_dev.join(timeout=10.0)
        t_tool.join(timeout=10.0)

        assert results["studio"][0] == 200 and results["studio"][1]["status"] == "reloaded", results["studio"]
        assert results["dev"][0] == 200 and results["dev"][1]["status"] == "reloaded", results["dev"]
        assert results["tool"][0] == 200, results["tool"]

        defn_final = host_runtime.find("studiolock")
        assert defn_final is not None
        st_final = owner_state.get(w.state, defn_final.manifest)
        assert st_final.digest == defn_final.manifest.code_digest
        assert results["dev"][1]["digest"] == defn_final.manifest.code_digest

        r_ping = w.client.post(
            "/api/v1/cplug-owner/tool",
            json={"cplug_id": "studiolock", "tool": "ping", "args": {}},
            headers=w.owner_headers,
        )
        assert r_ping.status_code == 200 and json.loads(r_ping.json()["result"]["content"][0]["text"]) == {"marker": "v3"}




def test_r2_bug3_permission_diff_tracks_ui_slots_harnesses_channels_and_strip_clears_slots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_dir = write_plugin_files(
        tmp_path / "base",
        {
            "carnivore.toml": """
                schema = 2
                id = "diffplug"
                name = "Diff Plug"
                version = "1.0.0"
                kind = "plugin"
                description = "Base plugin"
                author = "Tester"
                license = "MIT"
                tier = "catalog"
            """,
            "LICENSE.md": DEFAULT_MIT_LICENSE,
        },
    )
    slots_dir = write_plugin_files(
        tmp_path / "with_slots",
        {
            "carnivore.toml": """
                schema = 2
                id = "diffplug"
                name = "Diff Plug"
                version = "1.1.0"
                kind = "plugin"
                description = "Adds UI slots"
                author = "Tester"
                license = "MIT"
                tier = "catalog"

                [ui.contribute]
                commands = [{ id = "diffplug.cmd", title = "Run" }]
                "terminal.toolbar" = [{ id = "diffplug.btn", label = "Go" }]
            """,
            "LICENSE.md": DEFAULT_MIT_LICENSE,
        },
    )
    harnesses_dir = write_plugin_files(
        tmp_path / "with_harnesses",
        {
            "carnivore.toml": """
                schema = 2
                id = "diffplug"
                name = "Diff Plug"
                version = "1.2.0"
                kind = "plugin"
                description = "Adds harnesses"
                author = "Tester"
                license = "MIT"
                tier = "catalog"
                harnesses = ["rules/claude.toml"]
            """,
            "rules/claude.toml": 'id = "customagent"\nnames = ["customagent"]\n',
            "LICENSE.md": DEFAULT_MIT_LICENSE,
        },
    )
    channels_dir = write_plugin_files(
        tmp_path / "with_channels",
        {
            "carnivore.toml": """
                schema = 2
                id = "diffplug"
                name = "Diff Plug"
                version = "1.3.0"
                kind = "plugin"
                description = "Adds channels"
                author = "Tester"
                license = "MIT"
                tier = "catalog"

                [permissions]
                network = ["hooks.example.com"]

                [channels.pager]
                url = "https://hooks.example.com/notify"
                method = "POST"
            """,
            "LICENSE.md": DEFAULT_MIT_LICENSE,
        },
    )

    d_slots = compute_permission_diff(base_dir, slots_dir).as_dict()
    assert d_slots["requires_reconsent"] is True
    assert d_slots["added"]["ui_slots"] == ["commands", "terminal.toolbar"]

    d_harness = compute_permission_diff(base_dir, harnesses_dir).as_dict()
    assert d_harness["requires_reconsent"] is True
    assert d_harness["added"]["harnesses"] == ["rules/claude.toml"]

    d_chan = compute_permission_diff(base_dir, channels_dir).as_dict()
    assert d_chan["requires_reconsent"] is True
    assert d_chan["added"]["channels"] == ["pager"]

    d_narrow = compute_permission_diff(slots_dir, base_dir).as_dict()
    assert d_narrow["requires_reconsent"] is False
    assert d_narrow["removed"]["ui_slots"] == ["commands", "terminal.toolbar"]

    raw_dir = write_plugin_files(
        tmp_path / "raw_fallback",
        {
            "carnivore.json": json.dumps({
                "schema": 1,
                "id": "diffplug",
                "ui": {"contribute": {"session.badges": [{"id": "b"}]}},
                "harnesses": {"files": ["rules/codex.toml"]},
                "channels": {"ops": {"url": "https://hooks.example.com/ops"}},
            }),
        },
    )
    d_raw = compute_permission_diff(base_dir, raw_dir).as_dict()
    assert d_raw["requires_reconsent"] is True
    assert d_raw["added"]["ui_slots"] == ["session.badges"]
    assert d_raw["added"]["harnesses"] == ["rules/codex.toml"]
    assert d_raw["added"]["channels"] == ["ops"]

    state_dir = tmp_path / "state_strip"
    state_dir.mkdir()
    strip_v1_dir = write_plugin_files(
        tmp_path / "strip_v1",
        {
            "carnivore.toml": """
                schema = 2
                id = "slotstrip"
                name = "Slot Strip"
                version = "1.0.0"
                kind = "plugin"
                description = "Tier 0 slot plugin"
                author = "Tester"
                tier = "catalog"

                [ui.contribute]
                commands = [{ id = "slotstrip.a", title = "A" }]
            """,
            "LICENSE.md": DEFAULT_MIT_LICENSE,
        },
    )
    strip_v2_dir = write_plugin_files(
        tmp_path / "strip_v2",
        {
            "carnivore.toml": """
                schema = 2
                id = "slotstrip"
                name = "Slot Strip"
                version = "1.1.0"
                kind = "plugin"
                description = "Tier 0 slot plugin v2"
                author = "Tester"
                tier = "catalog"

                [ui.contribute]
                commands = [{ id = "slotstrip.a", title = "A" }]
                "terminal.toolbar" = [{ id = "slotstrip.b", label = "B" }]
            """,
            "LICENSE.md": DEFAULT_MIT_LICENSE,
        },
    )
    m_v1 = load_sidecar_manifest(strip_v1_dir, "slotstrip")
    owner_state.update(
        state_dir,
        m_v1,
        None,
        lambda cur: replace(cur, enabled=True, grants=(), ui_slot_grants=("commands",), digest=m_v1.code_digest),
    )

    m_v2 = load_sidecar_manifest(strip_v2_dir, "slotstrip")
    defn_v2 = SidecarDefinition(
        manifest=m_v2,
        item_id="harbor/slotstrip",
        install_key="inst-slotstrip",
        code_root=strip_v2_dir,
        folder=tmp_path / "data_slotstrip",
    )
    monkeypatch.setattr(catalog_cplug_gates, "reload_and_push", lambda _req: None)
    monkeypatch.setattr(catalog_cplug_gates.runtime, "find", lambda pid: defn_v2 if pid == "slotstrip" else None)

    req = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(services=SimpleNamespace(settings_reader=SimpleNamespace(state_dir=lambda: state_dir)))))
    row = SimpleNamespace(item_id="harbor/slotstrip")
    assert catalog_cplug_gates.strip_grant_after_update(req, row) is True
    st_after = owner_state.get(state_dir, m_v2)
    assert st_after.grants == ()
    assert st_after.ui_slot_grants == ()
    assert st_after.digest == ""




def test_r2_bug4_autopublish_partial_copy_rolls_back_approved_s3_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with hcf.lambda_modules(sh.JWT_TEST_SECRET) as api:
        hcf.seed_index(api, {sh.PUBLISHED_ITEM})
        sh.reset(api)
        monkeypatch.setattr(api.http_api, "ADMIN_GITHUB_USER_ID", sh.ADMIN_ID)
        monkeypatch.setenv("GATES_REQUIRED", "1")
        monkeypatch.delenv("AUTO_PUBLISH", raising=False)

        admin_tok = sh.token(api, sh.ADMIN_ID)
        st_tok = api.app.handler(sh.event("POST", "/v1/bot-tokens", json.dumps({"label": "g", "scopes": ["list", "gate", "verify"]}), admin_tok))
        bot_tok = sh.body_of(st_tok)["token"]

        members = {p.relative_to(WAREZ_FIXTURE).as_posix(): p.read_bytes() for p in sorted(WAREZ_FIXTURE.rglob("*")) if p.is_file()}
        members["carnivore.toml"] = members["carnivore.toml"].decode("utf-8").replace('id = "warezsmoke"', 'id = "partialcopy"').encode("utf-8")
        assert len(members) >= 2
        sub_body = {"name": "partialcopy", "files": [{"path": p, "content_base64": base64.b64encode(b).decode()} for p, b in members.items()]}

        r_sub = api.app.handler(sh.event("POST", "/v1/submissions", json.dumps(sub_body), sh.token(api)))
        assert r_sub["statusCode"] == 201, r_sub["body"]
        sid = sh.body_of(r_sub)["submission_id"]

        r_claim = api.app.handler(sh.event("POST", f"/v1/submissions/{sid}/gate-claim", json.dumps({"owner": "gate-1"}), bot_tok))
        assert r_claim["statusCode"] == 200
        digest = api.submissions.get_row(sid)["folder_digest"]
        report = {
            "outcome": "passed",
            "folder_digest": digest,
            "digest": digest,
            "gates": [{"n": n, "id": "g", "verdict": "pass"} for n in range(1, 13)],
            "review": {"digest": digest, "status": "reviewed", "verdict": "clean", "summary": "Runs safely. No issues found.", "warnings": []},
        }

        orig_copy = api.s3.copy_object
        copy_count = {"n": 0}

        def _failing_second_copy(**kwargs: Any) -> Any:
            copy_count["n"] += 1
            if copy_count["n"] == 2:
                raise OSError("simulated S3 copy failure on 2nd object")
            return orig_copy(**kwargs)

        monkeypatch.setattr(api.s3, "copy_object", _failing_second_copy)

        r_gate = api.app.handler(
            sh.event("POST", f"/v1/submissions/{sid}/gate-result", json.dumps({"owner": "gate-1", "outcome": "passed", "report": report}), bot_tok)
        )
        assert r_gate["statusCode"] == 503, r_gate["body"]
        assert copy_count["n"] == 2
        assert len(api.submissions._list_keys(f"pending/{sid}/")) == len(members) + 1
        assert api.submissions._list_keys(f"approved/{sid}/") == []




def _base_schema_manifest(settings_schema: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "schema": 2,
        "id": "schparity",
        "name": "Schema Parity",
        "version": "1.0.0",
        "kind": "plugin",
        "description": "Settings schema parity check",
        "author": "Tester",
        "license": "MIT",
        "tier": "catalog",
        "settings_schema": settings_schema,
    }


def test_r2_bug5_settings_schema_lambda_fallback_parity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invalid_schemas: List[Dict[str, Any]] = [
        {"version": 1, "fields": {"BAD_KEY": {"kind": "boolean", "labelKey": "cplug.schparity.bad", "default": True}}},
        {"version": 1, "fields": {"okKey": {"kind": "boolean", "labelKey": "badlabel", "default": True}}},
        {"version": 1, "fields": {"okKey": {"kind": "boolean", "labelKey": "cplug.schparity.ok", "default": "not_a_boolean"}}},
        {"version": 1, "fields": {"limit": {"kind": "number", "labelKey": "cplug.schparity.limit", "min": 1, "max": 10, "default": 0}}},
        {"version": 1, "fields": {"mode": {"kind": "enum", "labelKey": "cplug.schparity.mode", "options": [], "default": "a"}}},
        {"version": 1, "fields": {"mode": {"kind": "enum", "labelKey": "cplug.schparity.mode", "options": ["a", "a"], "default": "a"}}},
        {"version": 1, "fields": {"mode": {"kind": "enum", "labelKey": "cplug.schparity.mode", "options": ["a", "b"], "default": "c"}}},
        {"version": 1, "fields": {"tag": {"kind": "string", "labelKey": "cplug.schparity.tag", "maxLength": 0, "default": ""}}},
        {"version": 1, "fields": {"tag": {"kind": "string", "labelKey": "cplug.schparity.tag", "maxLength": 3, "default": "toolong"}}},
        {
            "version": 1,
            "fields": {"a": {"kind": "boolean", "labelKey": "cplug.schparity.a", "default": False}},
            "groups": [{"labelKey": "badgroup", "fields": ["a"]}],
        },
        {
            "version": 1,
            "fields": {
                "a": {"kind": "boolean", "labelKey": "cplug.schparity.a", "default": False},
                "b": {"kind": "boolean", "labelKey": "cplug.schparity.b", "default": True},
            },
            "groups": [{"labelKey": "cplug.schparity.grp", "fields": ["a"]}],
        },
    ]

    valid_schema: Dict[str, Any] = {
        "version": 1,
        "fields": {
            "enabledFlag": {"kind": "boolean", "labelKey": "cplug.schparity.flag", "default": True},
            "maxRows": {"kind": "number", "labelKey": "cplug.schparity.rows", "min": 1, "max": 100, "default": 25},
            "mode": {"kind": "enum", "labelKey": "cplug.schparity.mode", "options": ["fast", "safe"], "control": "segmented", "default": "fast"},
            "prefix": {"kind": "string", "labelKey": "cplug.schparity.prefix", "maxLength": 16, "default": "ok"},
        },
        "groups": [
            {
                "labelKey": "cplug.schparity.grp",
                "fields": ["enabledFlag", "maxRows", "mode", "prefix"],
            }
        ],
    }

    assert parse_manifest_v2(_base_schema_manifest(valid_schema)).settings_schema == valid_schema
    for bad in invalid_schemas:
        with pytest.raises(ManifestV2Error):
            parse_manifest_v2(_base_schema_manifest(bad))

    monkeypatch.setitem(sys.modules, "src.core.item_settings_schema", None)
    assert parse_manifest_v2(_base_schema_manifest(valid_schema)).settings_schema == valid_schema
    for bad in invalid_schemas:
        with pytest.raises(ManifestV2Error):
            parse_manifest_v2(_base_schema_manifest(bad))

    stage = tmp_path / "lambda_stage"
    stage.mkdir()
    sdk_dir = REPO_ROOT / "src" / "plugins" / "sdk"
    for fname in (
        "cplug_validate.py", "manifest_v2.py", "_manifest_v2_sections.py", "_settings_schema_fallback.py",
        "api_contract.py", "renamed_from.py", "ai_features.py", "core_features.py", "data_decl.py",
        "network.py", "ownership.py", "permission_registry.py", "tool_families.py", "schema_check.py",
    ):
        shutil.copy2(sdk_dir / fname, stage / fname)
    assert _settings_schema_fallback.__name__ == "src.plugins.sdk._settings_schema_fallback"

    bad_payload = json.dumps(_base_schema_manifest(invalid_schemas[0]))
    good_payload = json.dumps(_base_schema_manifest(valid_schema))
    probe_code = (
        "import json, sys\n"
        "sys.path.insert(0, sys.argv[1])\n"
        "import manifest_v2\n"
        "manifest_v2.parse_manifest_v2(json.loads(sys.argv[2]))\n"
        "try:\n"
        "    manifest_v2.parse_manifest_v2(json.loads(sys.argv[3]))\n"
        "except manifest_v2.ManifestV2Error:\n"
        "    pass\n"
        "else:\n"
        "    raise AssertionError('expected ManifestV2Error in isolated Lambda layout')\n"
    )
    proc = subprocess.run(
        [sys.executable, "-I", "-S", "-c", probe_code, str(stage), good_payload, bad_payload],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"stdout={proc.stdout}\nstderr={proc.stderr}"




def _make_tier0_race_files(plugin_id: str, version: str) -> Dict[str, str]:
    toml = (
        f'schema = 2\nid = "{plugin_id}"\nname = "Race Side"\nversion = "{version}"\n'
        f'kind = "plugin"\ndescription = "Tier 0 race plugin"\nauthor = "Tester"\nlicense = "MIT"\ntier = "local"\n'
        f'[permissions.reasons]\n"ui.slot:commands" = "Register test command"\n'
        f'[ui.contribute]\ncommands = [{{ id = "{plugin_id}.cmd", title = "Cmd {version}" }}]\n'
    )
    return {"carnivore.toml": toml, "LICENSE.md": DEFAULT_MIT_LICENSE}


def _spy_sidecar_skipped(monkeypatch: pytest.MonkeyPatch) -> List[Tuple[str, Dict[str, Any]]]:
    events: List[Tuple[str, Dict[str, Any]]] = []
    orig = sidecar_registry.logger.warning
    monkeypatch.setattr(
        sidecar_registry.logger,
        "warning",
        lambda event, **kw: (events.append((event, dict(kw))) if event == "cplug_sidecar_skipped" else None, orig(event, **kw))[1],
    )
    return events


def _install_commit_spy(monkeypatch: pytest.MonkeyPatch, *, hook_delete: bool = False) -> Dict[str, Any]:
    orig_commit, orig_delete = sideload_routes._commit_blocking, sideload_routes._delete_blocking
    st: Dict[str, Any] = {"n": 0, "overlaps": [], "guard": threading.Lock(), "arm": True, "started": threading.Event(), "gate": threading.Event()}

    def _enter(*, pause: bool) -> None:
        with st["guard"]:
            st["n"] += 1
            if st["n"] > 1:
                st["overlaps"].append(st["n"])
            should_pause = pause and st["arm"]
            if should_pause:
                st["arm"] = False
        if should_pause:
            st["started"].set()
            st["gate"].wait(timeout=4.0)

    def _exit() -> None:
        with st["guard"]:
            st["n"] -= 1

    def _hooked_commit(state_dir: Path, source: Path, staged: Dict[str, Any]) -> list:
        _enter(pause=True)
        try:
            return orig_commit(state_dir, source, staged)
        finally:
            _exit()

    monkeypatch.setattr(sideload_routes, "_commit_blocking", _hooked_commit)
    if hook_delete:
        def _hooked_delete(state_dir: Path, name: str) -> bool:
            _enter(pause=False)
            try:
                return orig_delete(state_dir, name)
            finally:
                _exit()

        monkeypatch.setattr(sideload_routes, "_delete_blocking", _hooked_delete)
    return st


def _run_raced_pair(
    spy: Dict[str, Any],
    first_fn: Any,
    second_fn: Any,
    second_key: str,
    out: Dict[str, Any],
) -> None:
    t1 = threading.Thread(target=first_fn, daemon=True)
    t1.start()
    assert spy["started"].wait(timeout=3.0)
    t2 = threading.Thread(target=second_fn, daemon=True)
    t2.start()
    time.sleep(0.08)
    assert second_key not in out, f"{second_key} bypassed reload_lock"
    spy["gate"].set()
    t1.join(timeout=5.0)
    t2.join(timeout=5.0)
    assert not t1.is_alive() and not t2.is_alive()


def test_r3_bug1_sideload_and_reload_once_serialize_and_enforce_needs_approval(
    tmp_path: Path,
    owner_jwt: str,  # noqa: F811
    key_store: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with build_plugins_v3_world(tmp_path, owner_jwt, key_store, monkeypatch, with_http_probe=False) as w:
        assert w.client.put("/api/v1/cplug-owner/sideload/switch", json={"enabled": True}, headers=w.owner_headers).status_code == 200
        src = write_plugin_files(tmp_path / "raceside_src", _make_tier0_race_files("raceside", "0.1.0"))
        w.sideload_and_enable(src, "raceside")
        assert w.client.post("/api/v1/cplug-owner/dev/lease", json={"path": str(src)}, headers=w.owner_headers).status_code == 200

        mgr = dev_session.manager_for(w.app)
        skipped_events = _spy_sidecar_skipped(monkeypatch)
        spy = _install_commit_spy(monkeypatch)

        def _do_sideload(out: Dict[str, Any]) -> None:
            resp = w.client.post("/api/v1/cplug-owner/sideload", json={"path": str(src)}, headers=w.owner_headers)
            out["sideload"] = (resp.status_code, resp.json())

        def _do_reload(out: Dict[str, Any]) -> None:
            assert w.client.portal is not None
            try:
                out["reload"] = ("ok", w.client.portal.call(mgr.reload_once, "studio-r3", "raceside", src))
            except WorkspaceConflictError as exc:
                out["reload"] = ("conflict", exc.code)

        write_plugin_files(src, _make_tier0_race_files("raceside", "0.1.1"))
        phase_a: Dict[str, Any] = {}
        _run_raced_pair(spy, lambda: _do_sideload(phase_a), lambda: _do_reload(phase_a), "reload", phase_a)
        assert spy["overlaps"] == [] and skipped_events == []
        assert phase_a["sideload"][0] == 200 and phase_a["sideload"][1]["needs_approval"] is True, phase_a["sideload"]
        assert phase_a["reload"] == ("conflict", "no_lease"), phase_a["reload"]
        defn_a = host_runtime.find("raceside")
        assert defn_a is not None and defn_a.manifest.version == "0.1.1"
        row_a = w.client.get("/api/v1/cplugs/raceside", headers=w.owner_headers).json()
        assert row_a["state"] == "needs_approval" and row_a["enabled"] is True

        w.sideload_and_enable(src, "raceside")
        assert w.client.post("/api/v1/cplug-owner/dev/lease", json={"path": str(src)}, headers=w.owner_headers).status_code == 200
        write_plugin_files(src, _make_tier0_race_files("raceside", "0.1.2"))
        spy["started"].clear()
        spy["gate"].clear()
        spy["arm"] = True
        phase_b: Dict[str, Any] = {}
        _run_raced_pair(spy, lambda: _do_reload(phase_b), lambda: _do_sideload(phase_b), "sideload", phase_b)
        assert spy["overlaps"] == [] and skipped_events == []
        assert phase_b["reload"][0] == "ok" and phase_b["reload"][1]["status"] == "reloaded", phase_b["reload"]
        assert phase_b["sideload"][0] == 200 and phase_b["sideload"][1]["needs_approval"] is False, phase_b["sideload"]
        defn_b = host_runtime.find("raceside")
        assert defn_b is not None and defn_b.manifest.version == "0.1.2"


def test_r3_bug1_delete_sideload_serializes_with_reload_once(
    tmp_path: Path,
    owner_jwt: str,  # noqa: F811
    key_store: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with build_plugins_v3_world(tmp_path, owner_jwt, key_store, monkeypatch, with_http_probe=False) as w:
        assert w.client.put("/api/v1/cplug-owner/sideload/switch", json={"enabled": True}, headers=w.owner_headers).status_code == 200
        src = write_plugin_files(tmp_path / "delside_src", _make_tier0_race_files("delside", "0.1.0"))
        w.sideload_and_enable(src, "delside")
        assert w.client.post("/api/v1/cplug-owner/dev/lease", json={"path": str(src)}, headers=w.owner_headers).status_code == 200

        mgr = dev_session.manager_for(w.app)
        skipped_events = _spy_sidecar_skipped(monkeypatch)
        spy = _install_commit_spy(monkeypatch, hook_delete=True)
        write_plugin_files(src, _make_tier0_race_files("delside", "0.1.1"))
        out: Dict[str, Any] = {}

        def _do_reload() -> None:
            assert w.client.portal is not None
            out["reload"] = w.client.portal.call(mgr.reload_once, "studio-r3-del", "delside", src)

        def _do_delete() -> None:
            resp = w.client.delete("/api/v1/cplug-owner/sideload", params={"name": "delside"}, headers=w.owner_headers)
            out["delete"] = (resp.status_code, resp.json())

        _run_raced_pair(spy, _do_reload, _do_delete, "delete", out)
        assert spy["overlaps"] == [] and skipped_events == []
        assert out["reload"]["status"] == "reloaded"
        assert out["delete"] == (200, {"removed": "delside"})
        assert host_runtime.find("delside") is None
        assert w.client.get("/api/v1/cplugs/delside", headers=w.owner_headers).status_code == 404
