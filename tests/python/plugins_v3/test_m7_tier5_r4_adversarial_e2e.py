
from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Optional, Tuple

import pytest

from src.api import catalog_installed_routes
from src.core.plugin_registry import plugin_layout
from src.core.skills.consent_via_ddl import CONSENT_SHEET
from src.core.skills.ledger_types import GLOBAL_PROJECT_PATH, SCOPE_GLOBAL, InstalledItem
from src.plugins.host import (
    github_install_support,
    identity,
    runtime as host_runtime,
)
from src.plugins.runtime.supervisor import IDLE
from tests.helpers.plugins_v3_e2e_world import (
    DARWIN_SANDBOX,
    build_plugins_v3_world,
    git_run,
    init_bare_git_repo,
    wire_bare_github,
)
from tests.helpers.plugins_v3_polyglot_fixtures import DEFAULT_MIT_LICENSE, write_plugin_files
from tests.python.api_keys.conftest import key_store, owner_jwt  # noqa: F401


def _versioned_plugin_files(plugin_id: str, ver: str, *, tier: str = "local") -> Dict[str, str]:
    toml = (
        f'schema = 2\nid = "{plugin_id}"\nname = "{plugin_id.title()}"\nversion = "{ver}"\n'
        f'kind = "plugin"\ndescription = "R4 race plugin"\nauthor = "Tester"\nlicense = "MIT"\ntier = "{tier}"\n'
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


def _pause_sockets_ensure_once(w: Any, monkeypatch: pytest.MonkeyPatch) -> Tuple[threading.Event, Dict[str, Any]]:
    orig_ensure = w.rt.supervisor._sockets.ensure
    entered = threading.Event()
    gate_box: Dict[str, Any] = {"loop": None, "event": None, "armed": True}

    async def _paused_ensure(*args: Any, **kwargs: Any) -> Path:
        if gate_box["armed"]:
            gate_box["armed"] = False
            ev = asyncio.Event()
            gate_box["loop"] = asyncio.get_running_loop()
            gate_box["event"] = ev
            entered.set()
            await asyncio.wait_for(ev.wait(), timeout=5.0)
        return await orig_ensure(*args, **kwargs)

    monkeypatch.setattr(w.rt.supervisor._sockets, "ensure", _paused_ensure)
    return entered, gate_box


def _release_async_gate(gate_box: Dict[str, Any]) -> None:
    loop, ev = gate_box.get("loop"), gate_box.get("event")
    assert loop is not None and ev is not None
    loop.call_soon_threadsafe(ev.set)




@pytest.mark.skipif(not DARWIN_SANDBOX, reason="macOS sandbox-exec required")
def test_r4_bug1_disable_vs_ensure_at_sockets_ensure_never_leaves_running(
    tmp_path: Path, owner_jwt: str, key_store: Any, monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    with build_plugins_v3_world(tmp_path, owner_jwt, key_store, monkeypatch, with_http_probe=False) as w:
        assert w.client.put("/api/v1/cplug-owner/sideload/switch", json={"enabled": True}, headers=w.owner_headers).status_code == 200
        src = write_plugin_files(tmp_path / "disrace_src", _versioned_plugin_files("disrace", "0.1.0"))
        row = w.sideload_and_enable(src, "disrace")
        assert w.rt.supervisor.state("disrace") == IDLE

        entered, gate = _pause_sockets_ensure_once(w, monkeypatch)
        out: Dict[str, Tuple[int, Any]] = {}

        def _call_tool() -> None:
            r = w.client.post("/api/v1/cplug-owner/tool", json={"cplug_id": "disrace", "tool": "ping", "args": {}}, headers=w.owner_headers)
            out["tool"] = (r.status_code, r.json())

        def _disable_put() -> None:
            r = w.client.put("/api/v1/cplugs/disrace", json={"revision": row["revision"], "enabled": False}, headers=w.owner_headers)
            out["put"] = (r.status_code, r.json())

        t_tool = threading.Thread(target=_call_tool, daemon=True)
        t_tool.start()
        assert entered.wait(timeout=3.0)

        t_put = threading.Thread(target=_disable_put, daemon=True)
        t_put.start()
        time.sleep(0.08)
        _release_async_gate(gate)
        t_tool.join(timeout=8.0)
        t_put.join(timeout=8.0)

        assert out["put"][0] == 200 and out["put"][1]["enabled"] is False, out["put"]
        assert w.rt.supervisor.state("disrace") == "disabled"
        assert w.rt.supervisor.process("disrace") is None

        _rev, _sheet, put_on = w.consent_for("disrace")
        assert w.client.put("/api/v1/cplugs/disrace", json=put_on, headers=w.owner_headers).status_code == 200
        entered2, gate2 = _pause_sockets_ensure_once(w, monkeypatch)
        assert w.client.portal is not None

        async def _direct_race() -> Optional[Any]:
            t_ens = asyncio.create_task(w.rt.supervisor.ensure("disrace"))
            while not entered2.is_set():
                await asyncio.sleep(0.01)
            t_dis = asyncio.create_task(w.rt.supervisor.disable("disrace", "direct_race"))
            await asyncio.sleep(0.05)
            assert not t_dis.done(), "Supervisor.disable must await supervisor._lock during _spawn"
            gate2["event"].set()
            await asyncio.gather(t_ens, t_dis)
            return w.rt.supervisor.process("disrace")

        proc_after = w.client.portal.call(_direct_race)
        assert proc_after is None
        assert w.rt.supervisor.state("disrace") == "disabled"


@pytest.mark.skipif(not DARWIN_SANDBOX, reason="macOS sandbox-exec required")
def test_r4_bug1_github_update_enable_false_vs_tool_call_never_runs_v2_under_v1_judge(
    tmp_path: Path, owner_jwt: str, key_store: Any, monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    with build_plugins_v3_world(tmp_path, owner_jwt, key_store, monkeypatch, with_http_probe=False) as w:
        bare, work, _sha1 = init_bare_git_repo(tmp_path / "repo_ghsock", _versioned_plugin_files("ghsock", "0.1.0"))
        wire_bare_github(monkeypatch, bare, owner="acme", repo="ghsock")

        body_v1 = _github_consent_body(w.client, w.owner_headers, "acme/ghsock", enable=True)
        r_v1 = w.client.post("/api/v1/cplug-owner/github/install", json=body_v1, headers=w.owner_headers)
        assert r_v1.status_code == 200 and r_v1.json()["enabled"] is True, r_v1.text

        write_plugin_files(work, _versioned_plugin_files("ghsock", "0.2.0"))
        git_run(work, "add", ".")
        git_run(work, "commit", "-q", "-m", "v2")
        git_run(work, "push", "-q", str(bare), "main")

        entered, gate = _pause_sockets_ensure_once(w, monkeypatch)
        out: Dict[str, Tuple[int, Any]] = {}

        def _call_tool() -> None:
            r = w.client.post("/api/v1/cplug-owner/tool", json={"cplug_id": "ghsock", "tool": "ping", "args": {}}, headers=w.owner_headers)
            out["tool"] = (r.status_code, r.json())

        def _update_disable() -> None:
            r = w.client.post(
                "/api/v1/cplug-owner/github/install",
                json={"source": "acme/ghsock", "enable": False},
                headers=w.owner_headers,
            )
            out["gh"] = (r.status_code, r.json())

        t_tool = threading.Thread(target=_call_tool, daemon=True)
        t_tool.start()
        assert entered.wait(timeout=3.0)

        t_gh = threading.Thread(target=_update_disable, daemon=True)
        t_gh.start()
        time.sleep(0.15)
        assert "gh" not in out, f"github/install bypassed reload_lock: {out}"
        _release_async_gate(gate)
        t_tool.join(timeout=8.0)
        t_gh.join(timeout=8.0)

        assert out["tool"][0] == 200
        assert json.loads(out["tool"][1]["result"]["content"][0]["text"]) == {"v": "0.1.0"}, out["tool"]
        assert out["gh"][0] == 200 and out["gh"][1]["enabled"] is False, out["gh"]
        assert w.rt.supervisor.state("ghsock") == "disabled"
        assert w.rt.supervisor.process("ghsock") is None

        r_after = w.client.post("/api/v1/cplug-owner/tool", json={"cplug_id": "ghsock", "tool": "ping", "args": {}}, headers=w.owner_headers)
        assert r_after.status_code == 409, r_after.text




@pytest.mark.skipif(not DARWIN_SANDBOX, reason="macOS sandbox-exec required")
def test_r4_bug2_github_install_vs_resume_and_put_cplug_never_trips_safe_mode(
    tmp_path: Path, owner_jwt: str, key_store: Any, monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    with build_plugins_v3_world(tmp_path, owner_jwt, key_store, monkeypatch, with_http_probe=False) as w:
        bare, work, _sha1 = init_bare_git_repo(tmp_path / "repo_ghrace", _versioned_plugin_files("ghrace", "0.1.0"))
        wire_bare_github(monkeypatch, bare, owner="acme", repo="ghrace")

        body_v1 = _github_consent_body(w.client, w.owner_headers, "acme/ghrace", enable=True)
        assert w.client.post("/api/v1/cplug-owner/github/install", json=body_v1, headers=w.owner_headers).status_code == 200
        rev_v1 = w.client.get("/api/v1/cplugs/ghrace", headers=w.owner_headers).json()["revision"]

        write_plugin_files(work, _versioned_plugin_files("ghrace", "0.2.0"))
        git_run(work, "add", ".")
        git_run(work, "commit", "-q", "-m", "v2")
        git_run(work, "push", "-q", str(bare), "main")
        body_v2 = _github_consent_body(w.client, w.owner_headers, "acme/ghrace", enable=True)

        orig_commit = github_install_support.commit_cplug_github_tx
        swapped = threading.Event()
        gate = threading.Event()

        def _paused_commit(*args: Any, **kwargs: Any) -> Any:
            tx = orig_commit(*args, **kwargs)
            swapped.set()
            gate.wait(timeout=5.0)
            return tx

        monkeypatch.setattr(github_install_support, "commit_cplug_github_tx", _paused_commit)
        out: Dict[str, Tuple[int, Any]] = {}

        def _do_gh() -> None:
            r = w.client.post("/api/v1/cplug-owner/github/install", json=body_v2, headers=w.owner_headers)
            out["gh"] = (r.status_code, r.json())

        def _do_resume() -> None:
            r = w.client.post("/api/v1/cplugs/ghrace/resume", headers=w.owner_headers)
            out["resume"] = (r.status_code, r.json())

        def _do_put() -> None:
            r = w.client.put("/api/v1/cplugs/ghrace", json={"revision": rev_v1, "enabled": True}, headers=w.owner_headers)
            out["put"] = (r.status_code, r.json())

        t_gh = threading.Thread(target=_do_gh, daemon=True)
        t_gh.start()
        assert swapped.wait(timeout=4.0)

        t_res = threading.Thread(target=_do_resume, daemon=True)
        t_put = threading.Thread(target=_do_put, daemon=True)
        t_res.start()
        t_put.start()
        time.sleep(0.12)
        assert "resume" not in out and "put" not in out, f"Routes bypassed reload_lock: {out}"

        gate.set()
        t_gh.join(timeout=8.0)
        t_res.join(timeout=8.0)
        t_put.join(timeout=8.0)

        assert out["gh"][0] == 200, out["gh"]
        assert out["resume"][0] == 200 and out["resume"][1]["state"] != "disabled (safe mode)", out["resume"]
        assert w.rt.supervisor._safe_mode is False
        assert w.rt.safe_mode() == {"env": False, "owner": False, "off": False}
        assert w.rt.supervisor.state("ghrace") in (IDLE, "running")


@pytest.mark.skipif(not DARWIN_SANDBOX, reason="macOS sandbox-exec required")
def test_r4_bug2_catalog_apply_version_vs_resume_and_tool_never_trips_safe_mode(
    tmp_path: Path, owner_jwt: str, key_store: Any, monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    with build_plugins_v3_world(tmp_path, owner_jwt, key_store, monkeypatch, with_http_probe=False) as w:
        v1_files = _versioned_plugin_files("catrace", "1.0.0", tier="catalog")
        v2_files = _versioned_plugin_files("catrace", "2.0.0", tier="catalog")
        v1_src = write_plugin_files(tmp_path / "catrace_v1", v1_files)
        v2_src = write_plugin_files(tmp_path / "catrace_v2", v2_files)

        code_root = plugin_layout.code_root(w.state, "catrace")
        code_root.parent.mkdir(parents=True, exist_ok=True)
        for rel, content in v1_files.items():
            dst = code_root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(content, encoding="utf-8")

        item_id = "harbor/catrace"
        rec = identity.register_install(w.state, "catrace", item_id, host_runtime.reserved_plugin_ids())
        w.ledger.insert(
            InstalledItem(
                install_id=rec.uuid, item_id=item_id, kind="cplug", publisher="harbor",
                name="catrace", version="1.0.0", digest="d1", scope=SCOPE_GLOBAL,
                project_path=GLOBAL_PROJECT_PATH, auto_update=False, source_index_url="https://idx.test/i.json",
                consented_digest=None, consented_body_sha=None, publisher_key_id="",
                revision=1, installed_at="2026-11-26T00:00:00Z", updated_at="2026-11-26T00:00:00Z",
                consent_via=CONSENT_SHEET,
            )
        )
        w.rt.load_registry()
        w.rt.supervisor.override_index("catrace", True)
        _rev, _sheet, put_on = w.consent_for("catrace")
        assert w.client.put("/api/v1/cplugs/catrace", json=put_on, headers=w.owner_headers).status_code == 200
        assert w.client.post("/api/v1/cplug-owner/tool", json={"cplug_id": "catrace", "tool": "ping", "args": {}}, headers=w.owner_headers).status_code == 200

        swapped = threading.Event()
        gate = threading.Event()

        async def _fake_stage(*_a: Any, **_k: Any) -> Tuple[Path, Any]:
            return tmp_path / "cat_stg", SimpleNamespace(path=v2_src, digest="d2")

        def _paused_apply(request: Any, **kw: Any) -> Any:
            for rel, content in v2_files.items():
                (code_root / rel).write_text(content, encoding="utf-8")
            swapped.set()
            gate.wait(timeout=5.0)
            return SimpleNamespace(install_id=rec.uuid, item_id=item_id, version="2.0.0")

        monkeypatch.setattr(catalog_installed_routes, "carries_scripts", lambda _v: False)
        monkeypatch.setattr(catalog_installed_routes, "fetch_and_stage", _fake_stage)
        monkeypatch.setattr(catalog_installed_routes, "check_digest", lambda *_: None)
        monkeypatch.setattr(catalog_installed_routes, "hash_file", lambda *_: ("sha2", 0))
        monkeypatch.setattr(catalog_installed_routes, "staged_plugin_declares_code", lambda *_: False)
        monkeypatch.setattr(catalog_installed_routes, "consent_carried", lambda *_a, **_k: True)
        monkeypatch.setattr(catalog_installed_routes, "discard_staging", lambda *_: None)
        monkeypatch.setattr(catalog_installed_routes, "apply_update_now", _paused_apply)
        monkeypatch.setattr(catalog_installed_routes.install_reporter, "schedule_for", lambda *_: None)
        monkeypatch.setattr(catalog_installed_routes, "installed_view", lambda *_, **__: {"ok": True})
        monkeypatch.setattr(catalog_installed_routes, "annotate_watch", lambda *_a, **_k: None)

        row_arg = w.ledger.get(rec.uuid)
        assert row_arg is not None and v1_src.is_dir()
        out: Dict[str, Any] = {}

        def _do_apply() -> None:
            assert w.client.portal is not None
            req = SimpleNamespace(app=w.app)
            ver = SimpleNamespace(v="2.0.0", digest="d2", sig=None, provenance=None, review=None, requires_warning_ack=False)
            body = SimpleNamespace(consent=None, expected_revision=1)
            out["apply"] = w.client.portal.call(catalog_installed_routes.apply_version, req, row_arg, SimpleNamespace(id=item_id), ver, body, None)

        def _do_resume() -> None:
            r = w.client.post("/api/v1/cplugs/catrace/resume", headers=w.owner_headers)
            out["resume"] = (r.status_code, r.json())

        def _do_tool() -> None:
            r = w.client.post("/api/v1/cplug-owner/tool", json={"cplug_id": "catrace", "tool": "ping", "args": {}}, headers=w.owner_headers)
            out["tool"] = (r.status_code, r.json())

        t_apply = threading.Thread(target=_do_apply, daemon=True)
        t_apply.start()
        assert swapped.wait(timeout=4.0)

        t_res = threading.Thread(target=_do_resume, daemon=True)
        t_tool = threading.Thread(target=_do_tool, daemon=True)
        t_res.start()
        t_tool.start()
        time.sleep(0.12)
        assert "resume" not in out and "tool" not in out, f"Routes bypassed reload_lock: {out}"

        gate.set()
        t_apply.join(timeout=8.0)
        t_res.join(timeout=8.0)
        t_tool.join(timeout=8.0)

        assert out["apply"] == {"ok": True}
        assert w.rt.supervisor._safe_mode is False
        assert out["resume"][0] == 409 and (out["resume"][1].get("detail") or {}).get("code") == "needs_approval", out["resume"]
        assert out["tool"][0] == 409 and (out["tool"][1].get("detail") or {}).get("code") == "needs_approval", out["tool"]




@pytest.mark.skipif(not DARWIN_SANDBOX, reason="macOS sandbox-exec required")
def test_r4_bug1_safe_mode_from_judge_inside_lock_does_not_deadlock(
    tmp_path: Path, owner_jwt: str, key_store: Any, monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    with build_plugins_v3_world(tmp_path, owner_jwt, key_store, monkeypatch, with_http_probe=False) as w:
        assert w.client.put("/api/v1/cplug-owner/sideload/switch", json={"enabled": True}, headers=w.owner_headers).status_code == 200
        src_t = write_plugin_files(tmp_path / "tampered_src", _versioned_plugin_files("tampered", "1.0.0"))
        src_b = write_plugin_files(tmp_path / "bystander_src", _versioned_plugin_files("bystander", "1.0.0"))
        w.sideload_and_enable(src_t, "tampered")
        w.sideload_and_enable(src_b, "bystander")

        r_by = w.client.post("/api/v1/cplug-owner/tool", json={"cplug_id": "bystander", "tool": "ping", "args": {}}, headers=w.owner_headers)
        assert r_by.status_code == 200, r_by.text
        assert w.rt.supervisor.state("tampered") == IDLE
        assert w.rt.supervisor.state("bystander") == "running"

        (plugin_layout.code_root(w.state, "tampered") / "main.py").write_text("# tampered\n", encoding="utf-8")

        assert w.client.portal is not None

        async def _trigger_judge() -> Optional[Any]:
            return await asyncio.wait_for(w.rt.supervisor.ensure("tampered"), timeout=4.5)

        t0 = time.monotonic()
        proc = w.client.portal.call(_trigger_judge)
        elapsed = time.monotonic() - t0

        assert elapsed < 5.0
        assert proc is None
        assert w.rt.supervisor._safe_mode is True
        assert w.rt.supervisor.state("tampered") == "disabled (safe mode)"
        assert w.rt.supervisor.state("bystander") == "disabled (safe mode)"
        assert w.rt.supervisor.process("bystander") is None
