
from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, Tuple

import pytest

from src.core.plugin_registry import plugin_layout
from src.core.plugin_studio import actions as studio_actions, dev_session, store as studio_store
from src.plugins.host import (
    developer_mode,
    runtime as host_runtime,
    sideload_routes,
    state as owner_state,
    system_lifecycle,
)
from tests.helpers.plugins_v3_e2e_world import (
    DARWIN_SANDBOX,
    build_plugins_v3_world,
    init_bare_git_repo,
    wire_bare_github,
)
from tests.helpers.plugins_v3_polyglot_fixtures import DEFAULT_MIT_LICENSE, write_plugin_files
from tests.python.api_keys.conftest import key_store, owner_jwt  # noqa: F401


def _plugin_files(plugin_id: str, ver: str, *, tier: str = "local") -> Dict[str, str]:
    toml = (
        f'schema = 2\nid = "{plugin_id}"\nname = "{plugin_id.title()}"\nversion = "{ver}"\n'
        f'kind = "plugin"\ndescription = "R5 race plugin"\nauthor = "Tester"\nlicense = "MIT"\ntier = "{tier}"\n'
        '[run]\ncmd = ["python3", "main.py"]\nmode = "rpc"\n'
        '[mcp]\n[[mcp.tools]]\nname = "ping"\ndescription = "Return version"\ngate = "read"\n'
        'inputSchema = { type = "object", properties = {} }\n'
    )
    main_py = (
        "from cplug_sdk import Plugin\n"
        "plugin = Plugin()\n"
        '@plugin.tool("ping", "Return version", {"type": "object", "properties": {}}, gate="read")\n'
        "async def ping(_args, _caller):\n"
        f'    return {{"v": "{ver}"}}\n'
    )
    return {"carnivore.toml": toml, "main.py": main_py, "LICENSE.md": DEFAULT_MIT_LICENSE}


def _github_consent_body(client: Any, headers: Dict[str, str], source: str, *, enable: bool) -> Dict[str, Any]:
    r_prev = client.post("/api/v1/cplug-owner/github/preview", json={"source": source}, headers=headers)
    assert r_prev.status_code == 200, r_prev.text
    sheet = r_prev.json()["consent_sheet"]
    ticks = [p["name"] for p in sheet.get("permissions", []) if p.get("needs_tick")]
    slot_ticks = [s["slot"] for s in sheet.get("ui_slots", []) if s.get("needs_tick")]
    return {
        "source": source,
        "enable": enable,
        "consent": {
            "digest": sheet["digest"],
            "body_sha": sheet["body_sha"],
            "grants_sha": sheet["grants_sha"],
            "ticks": ticks,
            "ui_slots_sha": sheet.get("ui_slots_sha"),
            "slot_ticks": slot_ticks,
        },
    }


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False




@pytest.mark.skipif(not DARWIN_SANDBOX, reason="macOS sandbox-exec required")
def test_r5_bug1_exited_paused_at_children_forget_vs_restart_preserves_proc2(
    tmp_path: Path, owner_jwt: str, key_store: Any, monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    with build_plugins_v3_world(tmp_path, owner_jwt, key_store, monkeypatch, with_http_probe=False) as w:
        assert w.client.put("/api/v1/cplug-owner/sideload/switch", json={"enabled": True}, headers=w.owner_headers).status_code == 200
        src = write_plugin_files(tmp_path / "exrace_src", _plugin_files("exrace", "0.1.0"))
        w.sideload_and_enable(src, "exrace")

        r1 = w.client.post("/api/v1/cplug-owner/tool", json={"cplug_id": "exrace", "tool": "ping", "args": {}}, headers=w.owner_headers)
        assert r1.status_code == 200, r1.text
        proc1 = w.rt.supervisor.process("exrace")
        assert proc1 is not None and proc1.pid is not None
        assert w.rt.supervisor._children is not None

        orig_forget = w.rt.supervisor._children.forget
        entered = threading.Event()
        gate = threading.Event()
        armed = {"on": True}

        def _paused_forget(plugin_id: str) -> None:
            if plugin_id == "exrace" and armed["on"]:
                armed["on"] = False
                entered.set()
                gate.wait(timeout=5.0)
            orig_forget(plugin_id)

        monkeypatch.setattr(w.rt.supervisor._children, "forget", _paused_forget)

        defn = host_runtime.find("exrace")
        assert defn is not None
        spec = w.host.sidecar_spec(defn)
        assert w.client.portal is not None

        assert proc1._proc is not None
        proc1._proc.kill()
        assert entered.wait(timeout=4.0), "_exited did not enter children.forget"

        restart_out: Dict[str, Any] = {}

        def _do_restart() -> None:
            restart_out["state"] = w.client.portal.call(w.rt.supervisor.restart, spec)

        t_res = threading.Thread(target=_do_restart, daemon=True)
        t_res.start()
        time.sleep(0.10)
        assert "state" not in restart_out, "Supervisor.restart bypassed _hold_lock while _exited was active"

        gate.set()
        t_res.join(timeout=8.0)
        assert restart_out.get("state") == "running", restart_out

        w.client.portal.call(asyncio.sleep, 0.05)

        proc2 = w.rt.supervisor.process("exrace")
        assert proc2 is not None and proc2 is not proc1
        assert proc2.ended is None and proc2.pid is not None and _pid_alive(proc2.pid)
        assert w.rt.supervisor.state("exrace") == "running"
        assert w.rt.supervisor._strikes.get("exrace") is None
        assert w.rt.supervisor._restarts.get("exrace") is None
        sock = w.rt.supervisor._sockets.path_for("exrace")
        assert sock is not None and sock.exists()
        child_raw = json.loads((w.state / "cplugs" / "children.json").read_text(encoding="utf-8"))
        assert child_raw["children"].get("exrace", {}).get("pid") == proc2.pid

        r2 = w.client.post("/api/v1/cplug-owner/tool", json={"cplug_id": "exrace", "tool": "ping", "args": {}}, headers=w.owner_headers)
        assert r2.status_code == 200 and w.rt.supervisor.process("exrace") is proc2


@pytest.mark.skipif(not DARWIN_SANDBOX, reason="macOS sandbox-exec required")
def test_r5_bug1_exited_paused_at_sockets_stop_vs_restart_preserves_proc2_socket(
    tmp_path: Path, owner_jwt: str, key_store: Any, monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    with build_plugins_v3_world(tmp_path, owner_jwt, key_store, monkeypatch, with_http_probe=False) as w:
        assert w.client.put("/api/v1/cplug-owner/sideload/switch", json={"enabled": True}, headers=w.owner_headers).status_code == 200
        src = write_plugin_files(tmp_path / "exsock_src", _plugin_files("exsock", "0.1.0"))
        w.sideload_and_enable(src, "exsock")

        r1 = w.client.post("/api/v1/cplug-owner/tool", json={"cplug_id": "exsock", "tool": "ping", "args": {}}, headers=w.owner_headers)
        assert r1.status_code == 200, r1.text
        proc1 = w.rt.supervisor.process("exsock")
        assert proc1 is not None and proc1._proc is not None

        orig_stop = w.rt.supervisor._sockets.stop
        entered = threading.Event()
        gate_box: Dict[str, Any] = {"loop": None, "event": None, "armed": True}

        async def _paused_sock_stop(plugin_id: str) -> None:
            if plugin_id == "exsock" and gate_box["armed"]:
                gate_box["armed"] = False
                ev = asyncio.Event()
                gate_box["loop"] = asyncio.get_running_loop()
                gate_box["event"] = ev
                entered.set()
                await asyncio.wait_for(ev.wait(), timeout=5.0)
            await orig_stop(plugin_id)

        monkeypatch.setattr(w.rt.supervisor._sockets, "stop", _paused_sock_stop)

        defn = host_runtime.find("exsock")
        assert defn is not None
        spec = w.host.sidecar_spec(defn)
        assert w.client.portal is not None

        proc1._proc.kill()
        assert entered.wait(timeout=4.0), "_exited did not enter _sockets.stop"

        restart_out: Dict[str, Any] = {}

        def _do_restart() -> None:
            restart_out["state"] = w.client.portal.call(w.rt.supervisor.restart, spec)

        t_res = threading.Thread(target=_do_restart, daemon=True)
        t_res.start()
        time.sleep(0.10)
        assert "state" not in restart_out, "Supervisor.restart bypassed _hold_lock while _sockets.stop was active"

        gate_box["loop"].call_soon_threadsafe(gate_box["event"].set)
        t_res.join(timeout=8.0)
        assert restart_out.get("state") == "running", restart_out

        w.client.portal.call(asyncio.sleep, 0.05)

        proc2 = w.rt.supervisor.process("exsock")
        assert proc2 is not None and proc2 is not proc1 and proc2.ended is None
        assert w.rt.supervisor.state("exsock") == "running"
        assert w.rt.supervisor._strikes.get("exsock") is None
        assert w.rt.supervisor._restarts.get("exsock") is None
        sock = w.rt.supervisor._sockets.path_for("exsock")
        assert sock is not None and sock.exists(), f"proc2 socket destroyed: {sock}"

        w.client.portal.call(lambda: w.rt.supervisor._exited("exsock", "exited", proc=proc1, epoch=0))
        assert w.rt.supervisor.process("exsock") is proc2
        assert w.rt.supervisor.state("exsock") == "running"
        assert w.rt.supervisor._sockets.path_for("exsock") == sock
        assert w.rt.supervisor._strikes.get("exsock") is None




@pytest.mark.skipif(not DARWIN_SANDBOX, reason="macOS sandbox-exec required")
def test_r5_bug2_purge_cplug_serializes_with_github_install_and_forget_guards_live_proc(
    tmp_path: Path, owner_jwt: str, key_store: Any, monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    with build_plugins_v3_world(tmp_path, owner_jwt, key_store, monkeypatch, with_http_probe=False) as w:
        bare, _work, _sha1 = init_bare_git_repo(tmp_path / "repo_purgerace", _plugin_files("purgerace", "0.1.0"))
        wire_bare_github(monkeypatch, bare, owner="acme", repo="purgerace")

        r_inst0 = w.client.post(
            "/api/v1/cplug-owner/github/install",
            json={"source": "acme/purgerace", "enable": False},
            headers=w.owner_headers,
        )
        assert r_inst0.status_code == 200, r_inst0.text
        r_dry = w.client.post("/api/v1/cplugs/purgerace/purge", json={"dry_run": True}, headers=w.owner_headers)
        assert r_dry.status_code == 200, r_dry.text
        token = r_dry.json()["confirm_token"]

        orig_before_purge = system_lifecycle.before_purge
        entered = threading.Event()
        gate_box: Dict[str, Any] = {"loop": None, "event": None, "armed": True}

        async def _paused_before_purge(app: Any, cplug_id: str) -> None:
            if cplug_id == "purgerace" and gate_box["armed"]:
                gate_box["armed"] = False
                ev = asyncio.Event()
                gate_box["loop"] = asyncio.get_running_loop()
                gate_box["event"] = ev
                entered.set()
                await asyncio.wait_for(ev.wait(), timeout=5.0)
            await orig_before_purge(app, cplug_id)

        monkeypatch.setattr(system_lifecycle, "before_purge", _paused_before_purge)

        body_enable = _github_consent_body(w.client, w.owner_headers, "acme/purgerace", enable=True)
        out: Dict[str, Tuple[int, Any]] = {}

        def _do_purge() -> None:
            r = w.client.post(
                "/api/v1/cplugs/purgerace/purge",
                json={"dry_run": False, "confirm_token": token},
                headers=w.owner_headers,
            )
            out["purge"] = (r.status_code, r.json())

        def _do_gh_install() -> None:
            r = w.client.post("/api/v1/cplug-owner/github/install", json=body_enable, headers=w.owner_headers)
            out["gh"] = (r.status_code, r.json())

        t_purge = threading.Thread(target=_do_purge, daemon=True)
        t_purge.start()
        assert entered.wait(timeout=4.0), "purge_cplug did not enter before_purge"

        t_gh = threading.Thread(target=_do_gh_install, daemon=True)
        t_gh.start()
        time.sleep(0.12)
        assert "gh" not in out, f"github/install bypassed reload_lock during purge_cplug: {out}"

        gate_box["loop"].call_soon_threadsafe(gate_box["event"].set)
        t_purge.join(timeout=8.0)
        t_gh.join(timeout=8.0)

        assert out["purge"][0] == 200, out["purge"]
        assert out["gh"][0] == 200 and out["gh"][1]["enabled"] is True, out["gh"]

        r_tool = w.client.post(
            "/api/v1/cplug-owner/tool",
            json={"cplug_id": "purgerace", "tool": "ping", "args": {}},
            headers=w.owner_headers,
        )
        assert r_tool.status_code == 200, r_tool.text
        proc = w.rt.supervisor.process("purgerace")
        assert proc is not None and proc.pid is not None and _pid_alive(proc.pid)
        assert w.rt.supervisor.state("purgerace") == "running"

        with pytest.raises(RuntimeError):
            w.rt.supervisor.forget("purgerace")
        assert w.rt.supervisor.process("purgerace") is proc
        assert _pid_alive(proc.pid)

        r_purge_live = w.client.post(
            "/api/v1/cplugs/purgerace/purge",
            json={"dry_run": False, "confirm_token": token},
            headers=w.owner_headers,
        )
        assert r_purge_live.status_code == 409
        assert r_purge_live.json()["detail"]["code"] == "cplug_enabled"
        assert w.rt.supervisor.process("purgerace") is proc
        assert w.rt.supervisor.state("purgerace") == "running"




@pytest.mark.skipif(not DARWIN_SANDBOX, reason="macOS sandbox-exec required")
def test_studio_install_and_dev_start_hold_reload_lock_across_consent_digest_stamp(
    tmp_path: Path, owner_jwt: str, key_store: Any, monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    with build_plugins_v3_world(tmp_path, owner_jwt, key_store, monkeypatch, with_http_probe=False) as w:
        monkeypatch.setattr(developer_mode, "is_on", lambda: True)
        ws_dir = w.state / "plugin-studio" / "workspaces" / "studiorace"
        write_plugin_files(ws_dir, _plugin_files("studiorace", "0.1.0"))
        studio_store.upsert_workspace(
            w.state,
            {"studio_id": "ws-race", "plugin_id": "studiorace", "name": "Studiorace", "folder": str(ws_dir)},
        )

        orig_consent_enable = dev_session._consent_and_enable_blocking
        entered = threading.Event()
        gate = threading.Event()
        armed = {"on": True}

        def _paused_consent_enable(*args: Any, **kwargs: Any) -> None:
            orig_consent_enable(*args, **kwargs)
            if armed["on"]:
                armed["on"] = False
                entered.set()
                gate.wait(timeout=5.0)

        monkeypatch.setattr(dev_session, "_consent_and_enable_blocking", _paused_consent_enable)

        v2_src = write_plugin_files(tmp_path / "studiorace_v2", _plugin_files("studiorace", "0.2.0"))
        out: Dict[str, Any] = {}
        assert w.client.portal is not None

        def _do_install() -> None:
            out["install"] = w.client.portal.call(studio_actions.install_workspace, w.app, ws_dir)

        def _do_sync_v2() -> None:
            out["sync_v2"] = w.client.portal.call(sideload_routes.sync_folder, w.rt, v2_src, None)

        t_inst = threading.Thread(target=_do_install, daemon=True)
        t_inst.start()
        assert entered.wait(timeout=4.0), "install_workspace did not enter _consent_and_enable_blocking"

        t_sync = threading.Thread(target=_do_sync_v2, daemon=True)
        t_sync.start()
        time.sleep(0.12)
        assert "sync_v2" not in out, f"sync_folder bypassed reload_lock during install_workspace: {out}"

        gate.set()
        t_inst.join(timeout=8.0)
        t_sync.join(timeout=8.0)

        assert out["install"]["ok"] is True
        defn_v2 = host_runtime.find("studiorace")
        assert defn_v2 is not None and defn_v2.manifest.version == "0.2.0"
        st_now = owner_state.get(w.state, defn_v2.manifest)
        assert st_now.digest == out["install"]["digest"]
        assert st_now.digest != defn_v2.manifest.code_digest
        assert out["sync_v2"]["needs_approval"] is True

        ws_dir2 = w.state / "plugin-studio" / "workspaces" / "studiodev"
        write_plugin_files(ws_dir2, _plugin_files("studiodev", "0.1.0"))
        row2 = studio_store.upsert_workspace(
            w.state,
            {"studio_id": "ws-dev", "plugin_id": "studiodev", "name": "Studiodev", "folder": str(ws_dir2)},
        )
        mgr = dev_session.manager_for(w.app)
        try:
            start_res = w.client.portal.call(mgr.start, "ws-dev", row2)
            assert start_res["active"] is True and start_res["plugin_id"] == "studiodev"
            defn_dev = host_runtime.find("studiodev")
            assert defn_dev is not None
            assert owner_state.get(w.state, defn_dev.manifest).digest == defn_dev.manifest.code_digest
            assert (plugin_layout.code_root(w.state, "studiodev") / "main.py").is_file()
        finally:
            w.client.portal.call(mgr.stop, "ws-dev", row2)
