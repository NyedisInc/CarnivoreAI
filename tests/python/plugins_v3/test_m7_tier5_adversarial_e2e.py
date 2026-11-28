
from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import threading
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

import pytest

from src.core.mcp import pending
from src.core.skills.digest import digest_directory
from src.plugins.cli import install_publish
from src.plugins.host import (
    runtime as host_runtime,
    sidecar_registry,
    sidecar_routes,
    sidecar_services,
    sideload,
    sideload_routes,
    state as owner_state,
)
from src.plugins.sdk.manifest_v2 import ManifestV2Error, parse_manifest_v2
from tests.helpers import hosted_catalog_fake as hcf
from tests.helpers import submissions_harness as sh
from tests.helpers.minisign_keys import SKIP_REASON, minisign_binary
from tests.helpers.plugins_v3_e2e_world import (
    DARWIN_SANDBOX,
    build_plugins_v3_world,
)
from tests.helpers.plugins_v3_polyglot_fixtures import DEFAULT_MIT_LICENSE, build_python_plugin, write_plugin_files
from tests.helpers.warez_slice5_e2e_fixtures import (
    build_and_publish_checkout_index,
    open_e2e_bridge,
    publish_cplug_to_checkout,
)
from tests.python.api_keys.conftest import key_store, owner_jwt  # noqa: F401

REPO_ROOT = Path(__file__).resolve().parents[3]
WAREZ_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "cplugs" / "warezsmoke"


def _base_v2_manifest(plugin_id: str, settings_schema: Any) -> Dict[str, Any]:
    return {
        "schema": 2,
        "id": plugin_id,
        "name": plugin_id.title(),
        "version": "1.0.0",
        "kind": "plugin",
        "description": "Tier 5 adversarial settings test plugin",
        "author": "Tester",
        "license": "MIT",
        "tier": "catalog",
        "run": {"cmd": ["python3", "main.py"], "mode": "rpc"},
        "settings_schema": settings_schema,
    }


def _make_dev_plugin_files(plugin_id: str, marker: str) -> Dict[str, str]:
    toml = f"""
        schema = 2
        id = "{plugin_id}"
        name = "{plugin_id.title()}"
        version = "1.0.0"
        kind = "plugin"
        description = "Concurrent dev reload plugin"
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

        @plugin.ui("widget")
        async def render_widget(_params):
            return {{"schema": 2, "root": {{"type": "column", "children": [{{"type": "text", "text": "{marker}"}}]}}}}

        @plugin.tool("ping", "Return current marker", {{"type": "object", "properties": {{}}}}, gate="read")
        async def ping(_args, _caller):
            return {{"marker": "{marker}"}}
    """
    return {"carnivore.toml": toml, "main.py": main_py, "LICENSE.md": DEFAULT_MIT_LICENSE}




def test_tier5_bug1_third_party_invalid_settings_schema_rejected_at_sideload_and_parse(
    tmp_path: Path, owner_jwt: str, key_store: Any, monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    bad_kind = {"version": 1, "fields": {"bad": {"kind": "nonexistent_type", "labelKey": "cplug.bad.k", "default": "x"}}}
    bad_fields = {"version": 1, "fields": ["not", "a", "dict"]}
    for tier in ("catalog", "local"):
        with pytest.raises(ManifestV2Error):
            parse_manifest_v2(_base_v2_manifest("badkind", bad_kind), tier=tier)
        with pytest.raises(ManifestV2Error):
            parse_manifest_v2(_base_v2_manifest("badlist", bad_fields), tier=tier)

    with build_plugins_v3_world(tmp_path, owner_jwt, key_store, monkeypatch, with_http_probe=False) as w:
        assert w.client.put("/api/v1/cplug-owner/sideload/switch", json={"enabled": True}, headers=w.owner_headers).status_code == 200
        plug_a = write_plugin_files(
            tmp_path / "src_bad_kind",
            {
                "carnivore.toml": (
                    'schema = 2\nid = "badkind"\nname = "Badkind"\nversion = "1.0.0"\nkind = "plugin"\n'
                    'description = "Bad kind"\nauthor = "Tester"\nlicense = "MIT"\n'
                    '[run]\ncmd = ["python3", "main.py"]\nmode = "rpc"\n'
                    '[settings_schema]\nversion = 1\n[settings_schema.fields.bad]\n'
                    'kind = "nonexistent_type"\nlabelKey = "cplug.badkind.bad"\ndefault = "x"\n'
                ),
                "main.py": "from cplug_sdk import Plugin\nplugin = Plugin()\n",
                "LICENSE.md": DEFAULT_MIT_LICENSE,
            },
        )
        r_a = w.client.post("/api/v1/cplug-owner/sideload", json={"path": str(plug_a)}, headers=w.owner_headers)
        assert r_a.status_code == 422 and (r_a.json().get("detail") or {}).get("code") == "manifest_invalid", r_a.text

        plug_b = write_plugin_files(
            tmp_path / "src_bad_list",
            {
                "carnivore.toml": (
                    'schema = 2\nid = "badlist"\nname = "Badlist"\nversion = "1.0.0"\nkind = "plugin"\n'
                    'description = "Bad fields"\nauthor = "Tester"\nlicense = "MIT"\n'
                    '[run]\ncmd = ["python3", "main.py"]\nmode = "rpc"\n'
                    '[settings_schema]\nversion = 1\nfields = ["not", "a", "dict"]\n'
                ),
                "main.py": "from cplug_sdk import Plugin\nplugin = Plugin()\n",
                "LICENSE.md": DEFAULT_MIT_LICENSE,
            },
        )
        r_b = w.client.post("/api/v1/cplug-owner/sideload", json={"path": str(plug_b)}, headers=w.owner_headers)
        assert r_b.status_code == 422 and (r_b.json().get("detail") or {}).get("code") == "manifest_invalid", r_b.text


def test_tier5_bug1_corrupt_on_disk_settings_schema_never_500s_list_or_put(
    tmp_path: Path, owner_jwt: str, key_store: Any, monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    assert host_runtime.settings_defaults({"version": 1, "fields": ["not", "a", "dict"]}) == {}

    with build_plugins_v3_world(tmp_path, owner_jwt, key_store, monkeypatch, with_http_probe=False) as w:
        assert w.client.put("/api/v1/cplug-owner/sideload/switch", json={"enabled": True}, headers=w.owner_headers).status_code == 200
        plug = build_python_plugin(tmp_path / "src_ok", plugin_id="corruptsch")
        row = w.sideload_and_enable(plug, "corruptsch")
        defn = host_runtime.find("corruptsch")
        assert defn is not None

        reg = sidecar_registry.current()
        assert reg is not None
        corrupt_list_defn = replace(defn, manifest=replace(defn.manifest, settings_schema={"version": 1, "fields": ["bad"]}))
        reg._entries["corruptsch"] = corrupt_list_defn

        r_list = w.client.get("/api/v1/cplugs", headers=w.owner_headers)
        assert r_list.status_code == 200, r_list.text
        r_put_list = w.client.put(
            "/api/v1/cplugs/corruptsch",
            json={"revision": row["revision"], "settings": {"bad": "y"}},
            headers=w.owner_headers,
        )
        assert r_put_list.status_code == 422 and (r_put_list.json().get("detail") or {}).get("code") == "settings_invalid", r_put_list.text

        corrupt_kind_defn = replace(
            defn,
            manifest=replace(defn.manifest, settings_schema={"version": 1, "fields": {"bad": {"kind": "nonexistent"}}}),
        )
        reg._entries["corruptsch"] = corrupt_kind_defn
        r_put_kind = w.client.put(
            "/api/v1/cplugs/corruptsch",
            json={"revision": row["revision"], "settings": {"bad": "y"}},
            headers=w.owner_headers,
        )
        assert r_put_kind.status_code == 422 and (r_put_kind.json().get("detail") or {}).get("code") == "settings_invalid", r_put_kind.text




@pytest.mark.skipif(not DARWIN_SANDBOX, reason="macOS sandbox-exec required")
def test_tier5_bug2_owner_tool_slow_execution_past_5s_returns_200_and_hung_returns_504(
    tmp_path: Path, owner_jwt: str, key_store: Any, monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    with build_plugins_v3_world(tmp_path, owner_jwt, key_store, monkeypatch, with_http_probe=False) as w:
        assert w.client.put("/api/v1/cplug-owner/sideload/switch", json={"enabled": True}, headers=w.owner_headers).status_code == 200
        plug = write_plugin_files(
            tmp_path / "src_slow",
            {
                "carnivore.toml": """
                    schema = 2
                    id = "slowtool"
                    name = "Slowtool"
                    version = "1.0.0"
                    kind = "plugin"
                    description = "Slow inbox tool test"
                    author = "Tester"
                    license = "MIT"
                    tier = "catalog"

                    [run]
                    cmd = ["python3", "main.py"]
                    mode = "rpc"

                    [mcp]
                    [[mcp.tools]]
                    name = "slow_write"
                    description = "Sleeps after approval"
                    gate = "inbox"
                    inputSchema = { type = "object", properties = { delay = { type = "number" } } }
                """,
                "main.py": """
                    import asyncio
                    from cplug_sdk import Plugin

                    plugin = Plugin()

                    @plugin.tool("slow_write", "Sleeps after approval", {"type": "object", "properties": {"delay": {"type": "number"}}}, gate="inbox")
                    async def slow_write(args, _caller):
                        delay = float(args.get("delay", 0.0))
                        await asyncio.sleep(delay)
                        return {"slept": delay, "ok": True}
                """,
                "LICENSE.md": DEFAULT_MIT_LICENSE,
            },
        )
        w.sideload_and_enable(plug, "slowtool")

        store = pending.get_store()
        seen_ids = {row["id"] for row in store.list()}

        def _approve_next_item(delay_before_approve: float = 0.05) -> None:
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                for row in store.list():
                    if row["id"] not in seen_ids and row["action"] == "slowtool__slow_write":
                        seen_ids.add(row["id"])
                        if delay_before_approve > 0:
                            time.sleep(delay_before_approve)
                        assert w.client.portal is not None
                        w.client.portal.call(store.approve, row["id"])
                        return
                time.sleep(0.02)

        t_a = threading.Thread(target=_approve_next_item, args=(0.05,), daemon=True)
        t_a.start()
        r_a = w.client.post(
            "/api/v1/cplug-owner/tool",
            json={"cplug_id": "slowtool", "tool": "slow_write", "args": {"delay": 5.3}},
            headers=w.owner_headers,
        )
        t_a.join(timeout=10.0)
        assert r_a.status_code == 200, r_a.text
        parsed_a = json.loads(r_a.json()["result"]["content"][0]["text"])
        assert parsed_a["slept"] == 5.3

        monkeypatch.setattr(sidecar_routes, "TOOL_CALL_TIMEOUT", 0.4)
        t_b = threading.Thread(target=_approve_next_item, args=(0.05,), daemon=True)
        t_b.start()
        r_b = w.client.post(
            "/api/v1/cplug-owner/tool",
            json={"cplug_id": "slowtool", "tool": "slow_write", "args": {"delay": 1.1}},
            headers=w.owner_headers,
        )
        t_b.join(timeout=5.0)
        assert r_b.status_code == 504 and (r_b.json().get("detail") or {}).get("code") in ("owner_settle_timeout", "cplug_timeout"), r_b.text


@pytest.mark.skipif(not DARWIN_SANDBOX, reason="macOS sandbox-exec required")
def test_tier5_bug2_owner_tool_timeout_vs_approve_race_returns_200_result(
    tmp_path: Path, owner_jwt: str, key_store: Any, monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    with build_plugins_v3_world(tmp_path, owner_jwt, key_store, monkeypatch, with_http_probe=False) as w:
        assert w.client.put("/api/v1/cplug-owner/sideload/switch", json={"enabled": True}, headers=w.owner_headers).status_code == 200
        plug = write_plugin_files(
            tmp_path / "src_race",
            {
                "carnivore.toml": """
                    schema = 2
                    id = "racetool"
                    name = "Racetool"
                    version = "1.0.0"
                    kind = "plugin"
                    description = "Race inbox tool test"
                    author = "Tester"
                    license = "MIT"
                    tier = "catalog"

                    [run]
                    cmd = ["python3", "main.py"]
                    mode = "rpc"

                    [mcp]
                    [[mcp.tools]]
                    name = "race_write"
                    description = "Fast inbox tool"
                    gate = "inbox"
                    inputSchema = { type = "object", properties = { tag = { type = "string" } } }
                """,
                "main.py": """
                    from cplug_sdk import Plugin

                    plugin = Plugin()

                    @plugin.tool("race_write", "Fast inbox tool", {"type": "object", "properties": {"tag": {"type": "string"}}}, gate="inbox")
                    async def race_write(args, _caller):
                        return {"executed": True, "tag": args.get("tag", "")}
                """,
                "LICENSE.md": DEFAULT_MIT_LICENSE,
            },
        )
        w.sideload_and_enable(plug, "racetool")

        monkeypatch.setattr(sidecar_routes, "TOOL_CALL_TIMEOUT", 0.25)
        store = pending.get_store()
        orig_withdraw = store.withdraw
        race_fired = {"done": False}

        def _racing_withdraw(action_id: str, reason: str) -> bool:
            item = store.get(action_id)
            if not race_fired["done"] and item is not None and item.action == "racetool__race_write" and "timed out" in reason:
                race_fired["done"] = True
                claimed = store._claim(action_id)
                asyncio.get_running_loop().create_task(store.execute_claimed(claimed))
            return orig_withdraw(action_id, reason)

        monkeypatch.setattr(store, "withdraw", _racing_withdraw)

        resp = w.client.post(
            "/api/v1/cplug-owner/tool",
            json={"cplug_id": "racetool", "tool": "race_write", "args": {"tag": "win"}},
            headers=w.owner_headers,
        )
        assert race_fired["done"] is True
        assert resp.status_code == 200, resp.text
        assert json.loads(resp.json()["result"]["content"][0]["text"]) == {"executed": True, "tag": "win"}




@pytest.mark.skipif(not DARWIN_SANDBOX, reason="macOS sandbox-exec required")
def test_tier5_bug3_stop_via_inbox_never_returns_ok_before_destroy_settles_or_refuses(
    tmp_path: Path, owner_jwt: str, key_store: Any, monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    with build_plugins_v3_world(tmp_path, owner_jwt, key_store, monkeypatch, with_http_probe=False) as w:
        assert w.client.put("/api/v1/cplug-owner/sideload/switch", json={"enabled": True}, headers=w.owner_headers).status_code == 200
        plug = write_plugin_files(
            tmp_path / "src_stop",
            {
                "carnivore.toml": """
                    schema = 2
                    id = "stopplug"
                    name = "Stopplug"
                    version = "1.0.0"
                    kind = "plugin"
                    description = "Stop via inbox test plugin"
                    author = "Tester"
                    license = "MIT"
                    tier = "catalog"

                    [run]
                    cmd = ["python3", "main.py"]
                    mode = "rpc"

                    [permissions]
                    write = ["sessions.control"]

                    [permissions.reasons]
                    "sessions.control" = "Stop target session in E2E test"

                    [mcp]
                    [[mcp.tools]]
                    name = "stop_ses"
                    description = "Call sessions.control stop"
                    gate = "read"
                    inputSchema = { type = "object", properties = { ref = { type = "string" } } }
                """,
                "main.py": """
                    from cplug_sdk import HostError, Plugin

                    plugin = Plugin()

                    @plugin.tool("stop_ses", "Call sessions.control stop", {"type": "object", "properties": {"ref": {"type": "string"}}}, gate="read")
                    async def stop_ses(args, _caller):
                        try:
                            res = await plugin.host.sessions.control(ref=args["ref"], action="stop")
                            return {"ok": True, "res": res}
                        except HostError as exc:
                            return {"ok": False, "reason": exc.reason, "message": str(exc)}
                """,
                "LICENSE.md": DEFAULT_MIT_LICENSE,
            },
        )
        w.sideload_and_enable(plug, "stopplug")

        fake_info = SimpleNamespace(
            session=SimpleNamespace(id="ses_stop_1"),
            tmux_session="cl_stop_1",
            session_uuid="uuid_stop_1",
            host_key="local",
        )
        behavior = {"delay": 0.45, "exc": pending.ActionRefused("destroy failed after settle timeout")}

        async def _list_infos() -> List[Any]:
            return [fake_info]

        async def _destroy_session(*, session_id: str) -> None:
            assert session_id == "ses_stop_1"
            if behavior["delay"] > 0:
                await asyncio.sleep(behavior["delay"])
            raise behavior["exc"]

        w.app.state.session_manager.list_session_infos = _list_infos
        w.app.state.session_manager.destroy_session = _destroy_session
        monkeypatch.setattr(sidecar_services, "_STOP_WAIT_SECONDS", 0.1)
        monkeypatch.setattr(sidecar_services, "_STOP_SETTLE_SECONDS", 0.1)

        store = pending.get_store()
        seen = {row["id"] for row in store.list()}

        def _approve_stop() -> None:
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                for row in store.list():
                    if row["id"] not in seen and row["action"] == "plugin_session_stop":
                        seen.add(row["id"])
                        assert w.client.portal is not None
                        w.client.portal.call(store.approve, row["id"])
                        return
                time.sleep(0.02)

        behavior["delay"] = 0.6
        t1 = threading.Thread(target=_approve_stop, daemon=True)
        t1.start()
        r1 = w.client.post(
            "/api/v1/cplug-owner/tool",
            json={"cplug_id": "stopplug", "tool": "stop_ses", "args": {"ref": "ses_stop_1"}},
            headers=w.owner_headers,
        )
        t1.join(timeout=5.0)
        assert r1.status_code == 200, r1.text
        out1 = json.loads(r1.json()["result"]["content"][0]["text"])
        assert out1["ok"] is False and out1["reason"] == "timeout", out1

        monkeypatch.setattr(sidecar_services, "_STOP_WAIT_SECONDS", 5.0)
        behavior["delay"] = 0.0
        behavior["exc"] = pending.ActionRefused("refused by backend")
        t2 = threading.Thread(target=_approve_stop, daemon=True)
        t2.start()
        r2 = w.client.post(
            "/api/v1/cplug-owner/tool",
            json={"cplug_id": "stopplug", "tool": "stop_ses", "args": {"ref": "ses_stop_1"}},
            headers=w.owner_headers,
        )
        t2.join(timeout=5.0)
        assert r2.status_code == 200, r2.text
        out2 = json.loads(r2.json()["result"]["content"][0]["text"])
        assert out2["ok"] is False and out2["reason"] == "permission_denied", out2




@pytest.mark.skipif(not DARWIN_SANDBOX, reason="macOS sandbox-exec required")
def test_tier5_bug4_concurrent_dev_reload_and_mid_reload_tool_call_and_unique_backup(
    tmp_path: Path, owner_jwt: str, key_store: Any, monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    with build_plugins_v3_world(tmp_path, owner_jwt, key_store, monkeypatch, with_http_probe=False) as w:
        assert w.client.put("/api/v1/cplug-owner/sideload/switch", json={"enabled": True}, headers=w.owner_headers).status_code == 200
        src = write_plugin_files(tmp_path / "devrace_src", _make_dev_plugin_files("devrace", "v1"))
        w.sideload_and_enable(src, "devrace")

        r_lease = w.client.post("/api/v1/cplug-owner/dev/lease", json={"path": str(src)}, headers=w.owner_headers)
        assert r_lease.status_code == 200, r_lease.text

        write_plugin_files(src, _make_dev_plugin_files("devrace", "v2"))
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

        def _run_reload(key: str) -> None:
            resp = w.client.post(
                "/api/v1/cplug-owner/dev/reload",
                json={"path": str(src), "probe_ui": False},
                headers=w.owner_headers,
            )
            results[key] = (resp.status_code, resp.json())

        def _run_tool() -> None:
            resp = w.client.post(
                "/api/v1/cplug-owner/tool",
                json={"cplug_id": "devrace", "tool": "ping", "args": {}},
                headers=w.owner_headers,
            )
            results["tool"] = (resp.status_code, resp.json())

        t_rel1 = threading.Thread(target=_run_reload, args=("rel1",), daemon=True)
        t_rel1.start()
        assert commit_started.wait(timeout=3.0)

        write_plugin_files(src, _make_dev_plugin_files("devrace", "v3"))
        t_rel2 = threading.Thread(target=_run_reload, args=("rel2",), daemon=True)
        t_tool = threading.Thread(target=_run_tool, daemon=True)
        t_rel2.start()
        t_tool.start()
        time.sleep(0.1)
        commit_gate.set()

        t_rel1.join(timeout=10.0)
        t_rel2.join(timeout=10.0)
        t_tool.join(timeout=10.0)

        assert results["rel1"][0] == 200, results["rel1"]
        assert results["rel2"][0] == 200, results["rel2"]
        assert results["tool"][0] == 200, results["tool"]

        r_row = w.client.get("/api/v1/cplugs/devrace", headers=w.owner_headers)
        assert r_row.status_code == 200, r_row.text
        assert r_row.json()["state"] == "active", r_row.json()

        defn_final = host_runtime.find("devrace")
        assert defn_final is not None
        st_final = owner_state.get(w.state, defn_final.manifest)
        assert st_final.digest == defn_final.manifest.code_digest

        r_ping = w.client.post("/api/v1/cplug-owner/tool", json={"cplug_id": "devrace", "tool": "ping", "args": {}}, headers=w.owner_headers)
        assert r_ping.status_code == 200 and json.loads(r_ping.json()["result"]["content"][0]["text"]) == {"marker": "v3"}

        stale_dir = sideload.code_root_of(w.state, f".sideload-old-uniqplug-{os.getpid()}")
        stale_dir.mkdir(parents=True, exist_ok=True)
        (stale_dir / "leftover.txt").write_text("stale", encoding="utf-8")
        uniq_src = write_plugin_files(tmp_path / "uniq_src", _make_dev_plugin_files("uniqplug", "u1"))
        staging, files, manifest = sideload.stage(w.state, "uniqplug", uniq_src, dev=True)
        sideload.install_staged(w.state, "uniqplug", staging, files, manifest.code_digest, uniq_src)
        assert (sideload.code_root_of(w.state, "uniqplug") / "main.py").is_file()




def test_tier5_bug5_autopublish_cas_failure_preserves_pending_s3_and_leaves_approved_empty(
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
        members["carnivore.toml"] = members["carnivore.toml"].decode("utf-8").replace('id = "warezsmoke"', 'id = "raceplug"').encode("utf-8")
        sub_body = {"name": "raceplug", "files": [{"path": p, "content_base64": base64.b64encode(b).decode()} for p, b in members.items()]}

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

        orig_update = api.submissions.update_with_event
        raced = {"fired": False}

        def _racing_update(arguments: Dict[str, Any], event: Dict[str, str]) -> None:
            cond = arguments.get("ConditionExpression", "")
            if not raced["fired"] and arguments.get("Key", {}).get("submission_id") == sid and "#status = :pending AND gate_state = :awaiting" in cond:
                raced["fired"] = True
                api.submissions.table().update_item(
                    Key={"submission_id": sid},
                    UpdateExpression="SET report_sha256 = :other",
                    ExpressionAttributeValues={":other": "f" * 64},
                )
            return orig_update(arguments, event)

        monkeypatch.setattr(api.submissions, "update_with_event", _racing_update)

        r_gate = api.app.handler(
            sh.event("POST", f"/v1/submissions/{sid}/gate-result", json.dumps({"owner": "gate-1", "outcome": "passed", "report": report}), bot_tok)
        )
        assert r_gate["statusCode"] == 200, r_gate["body"]
        body = sh.body_of(r_gate)
        assert raced["fired"] is True
        assert body["auto_published"] is False
        assert api.submissions.get_row(sid)["status"] == "pending"

        pending_keys = api.submissions._list_keys(f"pending/{sid}/")
        approved_keys = api.submissions._list_keys(f"approved/{sid}/")
        assert len(pending_keys) > 0, "pending/ S3 objects must remain intact after CAS failure"
        assert len(approved_keys) == 0, "approved/ S3 prefix must be cleaned after CAS failure"

        monkeypatch.setattr(api.submissions, "update_with_event", orig_update)
        members2 = {k: v for k, v in members.items()}
        members2["carnivore.toml"] = members["carnivore.toml"].decode("utf-8").replace('id = "raceplug"', 'id = "cleanrace"').encode("utf-8")
        sub_body2 = {"name": "cleanrace", "files": [{"path": p, "content_base64": base64.b64encode(b).decode()} for p, b in members2.items()]}
        r_sub2 = api.app.handler(sh.event("POST", "/v1/submissions", json.dumps(sub_body2), sh.token(api)))
        assert r_sub2["statusCode"] == 201, r_sub2["body"]
        sid2 = sh.body_of(r_sub2)["submission_id"]
        assert api.app.handler(sh.event("POST", f"/v1/submissions/{sid2}/gate-claim", json.dumps({"owner": "gate-1"}), bot_tok))["statusCode"] == 200
        digest2 = api.submissions.get_row(sid2)["folder_digest"]
        report2 = {
            "outcome": "passed",
            "folder_digest": digest2,
            "digest": digest2,
            "gates": [{"n": n, "id": "g", "verdict": "pass"} for n in range(1, 13)],
            "review": {"digest": digest2, "status": "reviewed", "verdict": "clean", "summary": "Runs safely. No issues found.", "warnings": []},
        }
        r_ok = api.app.handler(
            sh.event("POST", f"/v1/submissions/{sid2}/gate-result", json.dumps({"owner": "gate-1", "outcome": "passed", "report": report2}), bot_tok)
        )
        assert r_ok["statusCode"] == 200 and sh.body_of(r_ok)["auto_published"] is True, r_ok["body"]
        assert len(api.submissions._list_keys(f"pending/{sid2}/")) == 0
        assert len(api.submissions._list_keys(f"approved/{sid2}/")) == len(pending_keys)




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


@pytest.mark.skipif(minisign_binary() is None, reason=SKIP_REASON)
def test_tier5_bug6_cli_install_flagged_warez_cplug_sends_flagged_ack_and_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    with open_e2e_bridge(tmp_path) as ctx:
        plug_dir = build_python_plugin(tmp_path / "src_flagged", plugin_id="flaggedplug")
        files = {p.relative_to(plug_dir).as_posix(): p.read_bytes() for p in plug_dir.rglob("*") if p.is_file()}
        digest, _ = digest_directory(plug_dir)
        rev_doc = {
            "digest": digest,
            "status": "reviewed",
            "verdict": "flagged",
            "summary": "Uses external telemetry. Review carefully before enabling.",
            "warnings": [{"kind": "telemetry", "detail": "Sends telemetry externally"}],
        }
        publish_cplug_to_checkout(
            ctx.checkout, tmp_path, handle="harbor", name="flaggedplug", version="1.0.0",
            files=files, publisher_kp=ctx.publisher_kp, served_root=ctx.served_root, review=rev_doc,
        )
        build_and_publish_checkout_index(
            ctx.checkout, tmp_path, ctx.served_root, index_kp=ctx.index_kp, publisher_kp=ctx.publisher_kp,
            serial=5, reviews_by_key={("harbor/flaggedplug", "1.0.0"): rev_doc},
        )
        hdrs = {"Authorization": f"Bearer {ctx.admin_token}"}
        assert ctx.client.post("/api/v1/catalog/refresh", headers=hdrs).status_code == 200

        cli = _TestClientCliAdapter(ctx.client, hdrs)
        monkeypatch.setattr("sys.stdin", io.StringIO(""))

        rc_no = install_publish.run_install("harbor/flaggedplug", mode="warez", client=cli, assume_yes=False, as_json=True)
        captured_no = capsys.readouterr()
        assert rc_no == 2, f"stdout={captured_no.out} stderr={captured_no.err}"
        assert "telemetry" in captured_no.err.lower()

        rc_yes = install_publish.run_install("harbor/flaggedplug", mode="warez", client=cli, assume_yes=True, enable=True, as_json=True)
        captured_yes = capsys.readouterr()
        assert rc_yes == 0, captured_yes.err
        assert "telemetry" in captured_yes.err.lower()

        r_row = ctx.client.get("/api/v1/cplugs/flaggedplug", headers=hdrs)
        assert r_row.status_code == 200 and r_row.json()["enabled"] is True, r_row.text
