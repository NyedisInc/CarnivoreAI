
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.api import catalog_cplug_gates
from src.core.conversation_writers import Proc, ProcessTable
from src.core.mcp_health import host_methods, process_match
from src.core.mcp_health.client_log import LinkState
from src.core.mcp_health.monitor import Measure, Target
from src.core.mcp_health.servers import ServerSpec
from src.cplugs.host import install_gates, ui_doc
from src.cplugs.host.mcp_health_port import health_from_document
from src.cplugs.host.sidecar_manifest import load_sidecar_manifest
from src.cplugs.runtime import sandbox
from src.cplugs.runtime.dispatch import HostDispatcher, HostServices, PluginContext
from src.cplugs.runtime.owner_tokens import OwnerTokens
from src.cplugs.runtime.process import PluginSpec, ProcessEnded
from src.cplugs.runtime.supervisor import Supervisor

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / "packages" / "cplugs" / "mcphealth"
ITEM = "carnivore/mcphealth"
NOW = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)

try:
    sandbox.find_interpreter()
    SANDBOX = os.path.exists("/usr/bin/sandbox-exec") and sys.platform == "darwin"
except sandbox.SandboxUnavailable:
    SANDBOX = False
needs_sandbox = pytest.mark.skipif(not SANDBOX, reason="needs macOS sandbox-exec and the framework Python")


def _spec(name, transport, command=None, url=None):
    return ServerSpec(name=name, transport=transport, command=command, url=url, scope="user")


def _link(name, transport, state, reason):
    return LinkState(dir_name=name, transport=transport, state=state, reason=reason)


def seed():
    table = ProcessTable.from_rows([
        Proc(100, 1, "x", "claude"), Proc(101, 100, "x", "node /x/bin/mcp-server-memory --token=SECRET"), Proc(102, 100, "x", "zsh -l"),
        Proc(200, 1, "x", "codex"), Proc(201, 200, "x", "python3 /x/bridge.py")])
    a_specs = (_spec("memory", "stdio", "node"), _spec("gone", "stdio", "uvx"), _spec("docs", "http", url="https://docs.example/mcp"),
               _spec("figma", "http", url="https://figma.example/mcp"), _spec("notion", "sse", url="https://notion.example/sse"),
               _spec("old", "stdio", "node"))
    a_links = {k: v for k, v in (
        ("figma", _link("figma", "http", "down", "closed")), ("notion", _link("notion", "sse", "needs_auth", "needs_auth")),
        ("claude_ai_gmail", _link("claude.ai Gmail", "proxy", "connected", "connected")), ("plugin_x_y", _link("plugin:x:y", "stdio", "down", "gave_up")))}
    b_specs = (_spec("bridge", "stdio", "python3"),)

    def alive(specs, root):
        return {s.key: process_match.alive(s, root, {p: r.command for p, r in table.rows.items()}, table.children) for s in specs}

    c_specs = (_spec("plugin:x:y", "stdio", "uvx"), _spec("cmem", "stdio", "node"))
    started = NOW - timedelta(hours=1)
    measures = {"ses_a": Measure(a_specs, frozenset({"old"}), a_links, alive(a_specs, 100), started, NOW),
                "ses_b": Measure(b_specs, frozenset(), None, alive(b_specs, 200), NOW - timedelta(seconds=5), NOW),
                "adopted:tm_c": Measure(c_specs, frozenset(), None, alive(c_specs, 100), started, NOW)}
    targets = [Target("ses_a", "tm_a", "claude", pane_pid=99, agent_pid=100), Target("ses_b", "tm_b", "codex", pane_pid=199, agent_pid=200),
               Target("adopted:tm_c", "tm_c", "claude", pane_pid=99, agent_pid=100)]
    return targets, measures, table


def golden(measures=None, tmp_path=None):
    raw = json.loads((Path(__file__).parent / "fixtures" / "mcphealth_in_process_golden.json").read_text())
    return {sid: ([tuple(s) for s in v["servers"]], [tuple(d) for d in v["dropped"]]) for sid, v in raw.items()}


def project(health):
    return (sorted((s.name, s.transport, s.state, s.reason, s.source, s.exact) for s in health.servers),
            sorted((d.name, d.state, d.exact, d.source) for d in health.dropped))


async def render(code_dir, tmp, targets, measures, table, settings=None, granted=None, log=None):
    roots = {t.session_id: t.agent_pid for t in targets}
    services = HostServices(
        activity=(log if log is not None else []).append,
        process_snapshot=lambda: _async(host_methods.process_rows(table, targets, roots), "processes"),
        mcp_config=lambda ref: _async(host_methods.config_rows(targets, measures, NOW), "sessions"),
        mcp_links=lambda ref: _async(host_methods.link_rows(targets, measures), "sessions"))
    sup = Supervisor(tmp / "state", "9.9.9", HostDispatcher(services, OwnerTokens(), home=tmp / "home"), lambda *a: None,
                     lambda pid: {"inbox": 0, "timers": 0, "routes": 0}, lambda row: None, index={"expires_at": "2999-01-01T00:00:00Z"})
    manifest = load_sidecar_manifest(code_dir, "mcphealth")
    data = tmp / "state" / "cplugs" / ("0" * 32)
    data.mkdir(parents=True, exist_ok=True)
    ctx = PluginContext(plugin_id="mcphealth", install_key="0" * 32, data_dir=data,
                        granted=frozenset(manifest.permissions if granted is None else granted), manifest_tools=(), tier="local")
    spec = PluginSpec(ctx=ctx, code_dir=code_dir, entry="mcphealth_main", capabilities=frozenset({"events"}), subscriptions=frozenset(manifest.subscriptions),
                      settings=settings or {})
    try:
        assert await sup.enable(spec) == "running"
        return await sup.process("mcphealth").request("ui.render", {"surface": "status_source", "params": {}})
    finally:
        await sup.shutdown()


async def _async(rows, key):
    return {key: rows}


def staged(tmp_path, drop_permission=None):
    dest = tmp_path / "code" / "mcphealth"
    shutil.copytree(PACKAGE, dest, ignore=shutil.ignore_patterns("__pycache__"))
    if drop_permission:
        doc = json.loads((dest / "cplug.json").read_text())
        doc["permissions"]["app"].remove(drop_permission)
        (dest / "cplug.json").write_text(json.dumps(doc))
    return dest


def test_the_folder_passes_the_install_gates_and_the_sidecar_parser(tmp_path):
    copy = staged(tmp_path)
    facts = install_gates.evaluate(ITEM, copy).facts
    assert facts["id"] == "mcphealth" and [p["name"] for p in facts["permissions"]] == ["mcp.health.read", "notify"]
    assert all(p["reason"] for p in facts["permissions"]) and facts["tools"] == []
    manifest = load_sidecar_manifest(copy, "mcphealth")
    assert manifest.entry == "mcphealth_main.py" and manifest.subscriptions == ("mcp.health",) and manifest.default_enabled is False
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(services=SimpleNamespace(settings_reader=SimpleNamespace(state_dir=lambda: tmp_path)))))
    via_route_gate = asyncio.run(catalog_cplug_gates.gate_staged_cplug(request, SimpleNamespace(id=ITEM), copy))
    assert via_route_gate.facts["version"] == "1.0.1"
    assert not any(p.stat().st_mode & 0o111 for p in PACKAGE.rglob("*") if p.is_file()) and not (PACKAGE / "scripts").exists()


@needs_sandbox
def test_the_package_renders_what_the_in_process_plugin_judges(tmp_path):
    targets, measures, table = seed()
    want = golden(measures, tmp_path)
    assert want["ses_a"][0] and any(s[2] == "down" for s in want["ses_a"][0]) and any(s[2] == "connected" for s in want["ses_a"][0])
    result = asyncio.run(asyncio.wait_for(render(staged(tmp_path), tmp_path, targets, measures, table), 90))
    document = ui_doc.validate(result["document"], routes=(), tools=())
    got = {sid: project(health_from_document(document, sid)) for sid in want}
    assert got == want
    assert set(want) == {"ses_a", "ses_b", "adopted:tm_c"} and all(want[sid][0] for sid in want)
    states = {(sid, s[0]): (s[2], s[3]) for sid in want for s in want[sid][0]}
    assert states[("ses_a", "gone")] == ("down", "process_gone") and states[("adopted:tm_c", "plugin:x:y")] == ("down", "process_gone")
    assert states[("ses_a", "plugin:x:y")][0] == "down" and states[("ses_b", "bridge")] == ("connected", "process_running")
    assert "old" not in {s[0] for s in got["ses_a"][0]} and "SECRET" not in json.dumps(result)


@needs_sandbox
def test_without_the_permission_the_host_refuses(tmp_path):
    targets, measures, table = seed()
    log = []
    with pytest.raises(ProcessEnded):
        asyncio.run(asyncio.wait_for(render(staged(tmp_path, "mcp.health.read"), tmp_path, targets, measures, table, log=log), 90))
    assert any(row["method"] == "mcp.config" and row["outcome"] == "not_granted" for row in log)


def test_a_url_scheme_in_rendered_text_is_refused_wherever_it_comes_from_but_data_may_carry_ids():
    def refused(document, **kw):
        with pytest.raises(ui_doc.UiDocError) as exc:
            ui_doc.validate(document, routes=(), tools=("t",))
        assert exc.value.code == "link_not_allowed", document

    for node in ({"type": "text", "value": "javascript:alert(1)"},
                 {"type": "button", "label": "javascript:alert(1)", "action": {"call": "tool", "name": "t"}},
                 {"type": "button", "label": "go", "action": {"call": "tool", "name": "t", "payload": {"u": "javascript:alert"}}}):
        refused({"schema": 1, "root": node})
    for hostile in ("javascript:alert(1)", "data:text/html,x", "vbscript:msgbox", "https://evil.example/x", "see https://evil.example", "plugin:x javascript:y"):
        refused({"schema": 1, "root": {"type": "text", "value": {"bind": "/a"}}, "data": {"a": hostile}})
        refused({"schema": 1, "root": {"type": "text", "value": "x"}, "data": {hostile: 1}})
    ok = ui_doc.validate({"schema": 1, "root": {"type": "text", "value": {"bind": "/a"}}, "data": {"adopted:tm": {"n": "plugin:x:y", "r": "remote:peer-1"}, "a": "hello"}},
                         routes=(), tools=())
    assert ok["data"]["adopted:tm"] == {"n": "plugin:x:y", "r": "remote:peer-1"}
    with pytest.raises(ui_doc.UiDocError):
        ui_doc.validate({"schema": 1, "root": {"type": "text", "value": "x"}, "data": {"k": "a\u202eb"}}, routes=(), tools=())


def test_nothing_under_src_imports_the_package():
    src = ROOT / "src"
    files = [p for p in src.rglob("*.py")]
    assert len(files) > 500
    assert sum("from src.cplugs" in p.read_text(errors="replace") for p in files) > 50
    needles = ("packages.cplugs", "packages/cplugs", "mcphealth_main", "mh_combine", "mh_vocab", "mh_notices", "mh_warn_filter")
    hits = [str(p) for p in files if any(n in p.read_text(errors="replace") for n in needles)]
    assert hits == []
    assert not (ROOT / "packages" / "__init__.py").exists() and not (ROOT / "packages" / "cplugs" / "__init__.py").exists()
