
from __future__ import annotations

import base64
import io
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

from src.core.cli_command import service as cli_service
from src.plugins.host import sidecar_registry, sidecar_spec
from src.plugins.host.plugin_manifest import load_sidecar_manifest
from src.plugins.runtime import sandbox, sock_cli
from src.plugins.runtime.dispatch import HostDispatcher, HostServices, PluginContext
from src.plugins.runtime.owner_tokens import OwnerTokens
from src.plugins.runtime.socket_server import PluginSocketManager
from src.plugins.runtime.supervisor import Supervisor


def _can_run_darwin_sandbox() -> bool:
    if sys.platform != "darwin" or not os.path.exists("/usr/bin/sandbox-exec"):
        return False
    try:
        sandbox.find_interpreter()
        return True
    except sandbox.SandboxUnavailable:
        return False


DARWIN_SANDBOX = _can_run_darwin_sandbox()


def test_sock_cli_parses_all_33_host_methods(monkeypatch: pytest.MonkeyPatch) -> None:
    expected_methods = {
        "sessions.list",
        "sessions.get",
        "sessions.output",
        "sessions.permission_mode",
        "sessions.message",
        "sessions.create",
        "sessions.control",
        "notify.toast",
        "notify.alert",
        "storage.get",
        "storage.put",
        "storage.delete",
        "storage.list",
        "topic.publish",
        "ui.invalidate",
        "ui.slot.publish",
        "http.fetch",
        "ai.call",
        "ledger.read",
        "projects.list",
        "projects.git",
        "projects.snapshot",
        "exports.write",
        "log",
        "process.snapshot",
        "mcp.config",
        "mcp.links",
        "flow.run",
        "flow.run_part",
        "flow.feed",
        "flow.tasks",
        "service.call",
        "events.emit",
    }

    invocations: List[List[str]] = [
        ["sessions", "list", "--json"],
        ["sessions", "get", "ses_1", "--json"],
        ["sessions", "output", "ses_1", "--lines=40"],
        ["sessions", "permission-mode", "ses_1"],
        ["sessions", "message", "ses_1", "hello", "--owner-token", "tok_1"],
        ["sessions", "create", "--project", "1", "--prompt", "hi", "--family", "claude"],
        ["sessions", "control", "ses_1", "wake"],
        ["notify", "toast", "Build finished", "--ref", "ses_1"],
        ["notify", "alert", "k1", "info", "Alert title", '{"x":1}'],
        ["storage", "get", "k1"],
        ["storage", "put", "k1", '{"a":2}'],
        ["storage", "delete", "k1"],
        ["storage", "list", "--prefix", "k"],
        ["topic", "publish", "updates", "--key", "1"],
        ["ui", "invalidate", "widget"],
        ["ui", "slot-publish", "session.badges", "--items", '[{"id":"b1","badge":"OK"}]'],
        ["fetch", "https://api.github.com/zen", "-X", "POST", "-H", "Accept: application/json", "--json", '{"a":1}'],
        ["ai", "call", "sum", "chat", "--prompt", "hi", "--max-tokens", "32"],
        ["ledger", "read"],
        ["projects", "list"],
        ["projects", "git", "1", "status"],
        ["projects", "snapshot", "1", "3"],
        ["exports", "write", "/tmp/exp", "out.txt", "--text", "hello"],
        ["log", "info", "evt", '{"ok":true}'],
        ["process", "snapshot"],
        ["mcp", "config", "--session", "ses_1"],
        ["mcp", "links", "ses_1"],
        ["flow", "run", "12", "--seed", "huddle_item", "--refresh"],
        ["flow", "run-part", "tok", "0"],
        ["flow", "feed", "12", "updates", "--cursor", "5"],
        ["flow", "tasks", "--query", "bug", "--limit", "10"],
        ["service", "call", "svc", "meth", "--args", '{"x":1}'],
        ["events", "emit", "demo.ev", '{"n":1}'],
    ]

    seen = set()
    for argv in invocations:
        cleaned, _timeout, want_help = sock_cli._strip_global_flags(argv)
        assert not want_help
        method, params = sock_cli._build_request(cleaned)
        assert isinstance(params, dict)
        seen.add(method)

    assert seen == expected_methods

    monkeypatch.setattr(sys, "stdin", io.StringIO('{"from_stdin":true}'))
    m, p = sock_cli._build_request(["call", "storage.put", "-"])
    assert m == "storage.put" and p == {"from_stdin": True}

    _, exp_params = sock_cli._build_request(["exports", "write", "/tmp/x", "a.txt", "--text", "abc"])
    assert base64.b64decode(exp_params["bytes"]).decode("utf-8") == "abc"


def test_sock_cli_help_timeouts_errors_and_plugin_fail_fast(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    assert sock_cli.main(["--help"]) == 0
    assert "sessions" in capsys.readouterr().out

    monkeypatch.delenv("CARNIVORE_PLUGIN_SOCK", raising=False)
    assert sock_cli.main(["sessions", "list"]) == 2
    assert "CARNIVORE_PLUGIN_SOCK" in capsys.readouterr().err

    monkeypatch.setenv("CARNIVORE_PLUGIN_SOCK", str(tmp_path / "p.sock"))
    assert sock_cli.main(["plugin", "dev"]) == 2
    assert "disabled inside a plugin sandbox" in capsys.readouterr().err

    assert sock_cli.main(["fetch", "https://example.com", "-X"]) == 2
    assert "requires a value" in capsys.readouterr().err

    assert sock_cli._default_timeout("sessions.control", {"action": "stop"}) >= 130.0
    assert sock_cli._default_timeout("ai.call", {}) >= 60.0


@pytest.mark.asyncio
async def test_sock_cli_end_to_end_against_socket_server(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    class _FakeAi:
        async def call(self, feature: str, cap: str, inp: Dict[str, Any]) -> Dict[str, Any]:
            return {"output": {"feature": feature, "cap": cap, "prompt": inp.get("prompt")}}

    disp = HostDispatcher(
        HostServices(
            activity=lambda _r: None,
            list_sessions=lambda: _async_val([{"session": {"id": "ses_1"}, "label": "dev"}]),
            list_projects=lambda: _async_val([{"id": 7, "name": "core"}]),
            ai_for=lambda _ctx: _FakeAi(),
        ),
        OwnerTokens(b"s" * 32),
    )
    ctx = PluginContext(
        plugin_id="cliplug",
        install_key="k1",
        data_dir=tmp_path / "data",
        granted=frozenset({"sessions.read", "ai_features:cliplug:sum"}),
    )
    (tmp_path / "data" / "files").mkdir(parents=True)
    mgr = PluginSocketManager()
    sock_path = await mgr.ensure(tmp_path, ctx, disp)
    try:
        monkeypatch.setenv("CARNIVORE_PLUGIN_SOCK", str(sock_path))

        import asyncio

        rc = await asyncio.to_thread(sock_cli.main, ["sessions", "list", "--json"])
        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        assert out["sessions"][0]["id"] == "ses_1"

        rc_ai = await asyncio.to_thread(sock_cli.main, ["ai", "call", "cliplug:sum", "chat", "--prompt", "yo"])
        assert rc_ai == 0
        assert json.loads(capsys.readouterr().out)["output"]["prompt"] == "yo"

        rc_err = await asyncio.to_thread(sock_cli.main, ["notify", "toast", "Hi"])
        assert rc_err == 1
        err_text = capsys.readouterr().err
        assert "-32002:not_granted" in err_text
        assert '"permission":"notify"' in err_text
    finally:
        await mgr.stop_all()


async def _async_val(val: Any) -> Any:
    return val


@pytest.mark.asyncio
@pytest.mark.skipif(not DARWIN_SANDBOX, reason="needs macOS sandbox-exec and framework Python")
async def test_carnivore_bin_inside_bash_sandbox_runs_all_socket_commands(tmp_path: Path) -> None:
    code_dir = tmp_path / "bashplug"
    code_dir.mkdir()
    (code_dir / "carnivore.toml").write_text(
        "\n".join([
            "schema = 2",
            'id = "bashsock"',
            'name = "Bash Sock"',
            'version = "1.0.0"',
            'kind = "plugin"',
            'description = "Tests $CARNIVORE_BIN inside sandbox-exec"',
            'author = "Tester"',
            "",
            "[run]",
            'cmd = ["bash", "main.sh"]',
            'mode = "oneshot"',
            "",
            "[permissions]",
            'read = ["sessions"]',
            'write = ["notify"]',
            "",
        ]),
        encoding="utf-8",
    )
    (code_dir / "main.sh").write_text(
        "\n".join([
            "#!/bin/bash",
            "set -euo pipefail",
            '"$CARNIVORE_BIN" storage put bash_key \'{"ok":true}\' >/dev/null',
            '"$CARNIVORE_BIN" notify toast "From bash" >/dev/null',
            'SESS=$("$CARNIVORE_BIN" sessions list --json)',
            'printf \'{"sessions":%s}\' "$SESS"',
            "",
        ]),
        encoding="utf-8",
    )
    (code_dir / "main.sh").chmod(0o755)

    state_dir = tmp_path / "state"
    cli_service.write_shim(state_dir)
    data_dir = state_dir / "cplugs" / "inst-bash-1"
    (data_dir / "files").mkdir(parents=True)

    manifest = load_sidecar_manifest(code_dir, "bashsock", allow_local=True)
    defn = sidecar_registry.SidecarDefinition(
        manifest=manifest,
        item_id="local/bashsock",
        install_key="inst-bash-1",
        code_root=code_dir,
        folder=data_dir,
    )
    spec = sidecar_spec.build_spec(defn, frozenset(manifest.permissions), {}, consented=True, consent_owed=False)

    toasts: List[tuple[str, str, str]] = []
    disp = HostDispatcher(
        HostServices(
            activity=lambda _r: None,
            list_sessions=lambda: _async_val([{"session": {"id": "ses_b"}, "label": "b"}]),
            toast=lambda pid, ref, title: toasts.append((pid, ref, title)),
        ),
        OwnerTokens(b"b" * 32),
    )
    sup = Supervisor(
        state_dir,
        "1.0.0",
        disp,
        lambda _p, _k, _r: None,
        lambda _p: {},
        lambda _r: None,
        index={"expires_at": "2999-01-01T00:00:00Z"},
    )
    try:
        assert await sup.enable(spec) == "running"
        proc = sup.process("bashsock")
        assert proc is not None
        res = await proc.request("tools/call", {"name": "run", "arguments": {}})
        payload = json.loads(res["content"][0]["text"])
        assert payload["sessions"]["sessions"][0]["id"] == "ses_b"
        assert disp.storage(spec.ctx).get("bash_key") == {"ok": True}
        assert toasts == [("bashsock", "app", "[plugin] From bash")]
    finally:
        await sup.shutdown()
