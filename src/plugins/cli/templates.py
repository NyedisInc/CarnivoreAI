
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict

from src.plugins.host import identity
from src.plugins.sdk import cplug_validate
from src.plugins.sdk.manifest_v2 import ID_PATTERN

TEMPLATES = ("no-code", "python", "typescript", "bash", "widget", "channel", "agent-harness")
DEFAULT_TEMPLATE = "python"
DEFAULT_AUTHOR = "me"

_SHIPPED_ROOT = Path(__file__).resolve().parents[1]


class TemplateError(ValueError):
    pass


def name_problem(name: str) -> str:
    if not isinstance(name, str) or not ID_PATTERN.match(name):
        return f"{name!r} must match {ID_PATTERN.pattern} (lowercase letters and digits, no hyphen)"
    shipped = sorted(p.parent.name for p in _SHIPPED_ROOT.glob("*/carnivore.toml"))
    if name in cplug_validate.RESERVED_IDS or name in identity.reserved_names(shipped):
        return f"{name} is reserved (a first-party feature or a host word)"
    return ""


def _safe_toml_str(value: str) -> str:
    return json.dumps(value)


def _mit_license(author: str) -> str:
    holder = (author or DEFAULT_AUTHOR).strip() or DEFAULT_AUTHOR
    return (
        f"# MIT License\n\n"
        f"Copyright (c) 2026 {holder}\n\n"
        "Permission is hereby granted, free of charge, to any person obtaining a copy\n"
        "of this software and associated documentation files (the \"Software\"), to deal\n"
        "in the Software without restriction, including without limitation the rights\n"
        "to use, copy, modify, merge, publish, distribute, sublicense, and/or sell\n"
        "copies of the Software, and to permit persons to whom the Software is\n"
        "furnished to do so, subject to the following conditions:\n\n"
        "The above copyright notice and this permission notice shall be included in all\n"
        "copies or substantial portions of the Software.\n\n"
        "THE SOFTWARE IS PROVIDED \"AS IS\", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR\n"
        "IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,\n"
        "FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE\n"
        "AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER\n"
        "LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,\n"
        "OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE\n"
        "SOFTWARE.\n"
    )


def _no_code_files(name: str, author: str) -> Dict[str, str]:
    toml = "\n".join([
        "schema = 2",
        f"id = {_safe_toml_str(name)}",
        f"name = {_safe_toml_str(name.title())}",
        'version = "0.1.0"',
        'kind = "plugin"',
        f'description = "Tier 0 no-code declarative plugin for {name}."',
        f"author = {_safe_toml_str(author)}",
        'license = "MIT"',
        'min_app_version = "1.16.0"',
        "",
        "[permissions]",
        'write = ["notify"]',
        "",
        "[permissions.reasons]",
        'notify = "Send greeting notifications from macro actions."',
        "",
        "[macros.greet]",
        'title = "Send Hello Notification"',
        'steps = [{ action = "notify.toast", params = { ref = "app", title = "Hello from ' + name + '" } }]',
        "",
    ])
    test_py = f'''"""Manifest validation test for Tier 0 plugin {name}."""

from pathlib import Path

from src.plugins.sdk.manifest_v2 import load_manifest_v2


def test_{name}_manifest_is_tier0() -> None:
    manifest = load_manifest_v2(Path(__file__).resolve().parents[1], allow_tier_override=True)
    assert manifest.id == "{name}"
    assert manifest.tier0 is True
    assert "greet" in manifest.macros
'''
    readme = f"# {name}\n\nTier 0 No-Code Declarative Carnivore plugin (`schema = 2`).\n"
    return {
        "carnivore.toml": toml,
        "README.md": readme,
        f"tests/test_{name}.py": test_py,
    }


def _python_files(name: str, author: str) -> Dict[str, str]:
    toml = "\n".join([
        "schema = 2",
        f"id = {_safe_toml_str(name)}",
        f"name = {_safe_toml_str(name.title())}",
        'version = "0.1.0"',
        'kind = "plugin"',
        f'description = "Python sidecar plugin for {name}."',
        f"author = {_safe_toml_str(author)}",
        'license = "MIT"',
        'min_app_version = "1.16.0"',
        "",
        "[run]",
        'cmd = ["python3", "main.py"]',
        'mode = "rpc"',
        "",
        "[permissions]",
        'read = ["sessions"]',
        "",
        "[permissions.reasons]",
        '"sessions.read" = "Read active sessions for plugin context."',
        "",
        "[ui]",
        'routes = ["status"]',
        "",
        "[[mcp.tools]]",
        f'name = "{name}_hello"',
        'description = "Says hello from the plugin."',
        'gate = "read"',
        'inputSchema = { type = "object", properties = {}, additionalProperties = false }',
        "",
    ])
    main_py = f'''"""Entry point for the {name} Carnivore plugin."""

from __future__ import annotations

import asyncio
from typing import Any, Dict

from cplug_sdk import Plugin

plugin = Plugin()


@plugin.tool(
    "{name}_hello",
    "Says hello from the plugin.",
    {{"type": "object", "properties": {{}}, "additionalProperties": False}},
    gate="read",
)
async def hello(args: Dict[str, Any], caller: Any) -> str:
    return "hello"


@plugin.route("status")
async def status(request: Dict[str, Any]) -> Dict[str, Any]:
    return {{"status": 200, "body": {{"ok": True, "plugin": "{name}"}}}}


@plugin.ui("widget")
async def render_widget(params: Dict[str, Any]) -> Dict[str, Any]:
    return {{
        "schema": 1,
        "root": {{
            "type": "section",
            "title": "{name}",
            "children": [{{"type": "text", "value": "Ready"}}],
        }},
    }}


if __name__ == "__main__":
    asyncio.run(plugin.serve())
'''
    test_py = f'''"""Unit tests for {name}."""

import asyncio

from cplug_sdk.testing import FakeHost, attach, render_ui

import main as entry


def test_{name}_hello_and_ui() -> None:
    attach(entry.plugin, FakeHost())
    out = asyncio.run(entry.plugin.handle("tools/call", {{"name": "{name}_hello", "arguments": {{}}}}))
    assert out["content"][0]["text"] == "hello"
    ui = asyncio.run(render_ui(entry.plugin, "widget"))
    assert ui["document"]["schema"] == 1
'''
    return {
        "carnivore.toml": toml,
        "main.py": main_py,
        "README.md": f"# {name}\n\nPython Carnivore plugin (`schema = 2`).\n",
        f"tests/test_{name}.py": test_py,
    }


def _typescript_files(name: str, author: str) -> Dict[str, str]:
    toml = "\n".join([
        "schema = 2",
        f"id = {_safe_toml_str(name)}",
        f"name = {_safe_toml_str(name.title())}",
        'version = "0.1.0"',
        'kind = "plugin"',
        f'description = "TypeScript sidecar plugin for {name}."',
        f"author = {_safe_toml_str(author)}",
        'license = "MIT"',
        'min_app_version = "1.16.0"',
        "",
        "[run]",
        'cmd = ["node", "--experimental-strip-types", "main.ts"]',
        'mode = "rpc"',
        "",
        "[permissions]",
        'read = ["sessions"]',
        "",
        "[permissions.reasons]",
        '"sessions.read" = "Read active sessions for plugin context."',
        "",
        "[ui]",
        'routes = ["status"]',
        "",
        "[[mcp.tools]]",
        f'name = "{name}_hello"',
        'description = "Says hello from the TypeScript plugin."',
        'gate = "read"',
        'inputSchema = { type = "object", properties = {}, additionalProperties = false }',
        "",
    ])
    pkg = json.dumps(
        {
            "name": name,
            "version": "0.1.0",
            "type": "module",
            "scripts": {"test": "node --experimental-strip-types --test tests/main.test.ts"},
            "dependencies": {"@carnivore/plugin-sdk": "^1.0.0"},
        },
        indent=2,
    ) + "\n"
    tsconfig = json.dumps(
        {
            "compilerOptions": {
                "target": "ES2022",
                "module": "NodeNext",
                "moduleResolution": "NodeNext",
                "strict": True,
                "noEmit": True,
                "allowImportingTsExtensions": True,
            },
            "include": ["main.ts", "tests/**/*.ts"],
        },
        indent=2,
    ) + "\n"
    main_ts = f'''import fs from "node:fs";
import {{ pathToFileURL }} from "node:url";
import {{ Plugin }} from "@carnivore/plugin-sdk";

export const plugin = new Plugin()
  .tool(
    "{name}_hello",
    "Says hello from the TypeScript plugin.",
    {{ type: "object", properties: {{}}, additionalProperties: false }},
    "read",
    async () => "hello",
  )
  .route("status", async () => ({{ status: 200, body: {{ ok: true, plugin: "{name}" }} }}))
  .ui("widget", async () => ({{
    schema: 1,
    root: {{
      type: "section",
      title: "{name}",
      children: [{{ type: "text", value: "Ready from TypeScript" }}],
    }},
  }}));

if (process.argv[1] && import.meta.url === pathToFileURL(fs.realpathSync(process.argv[1])).href) {{
  void plugin.serve();
}}
'''
    test_ts = f'''import assert from "node:assert/strict";
import {{ describe, it }} from "node:test";
import {{ FakeHost, attach, renderUi }} from "@carnivore/plugin-sdk/testing";
import {{ plugin }} from "../main.ts";

describe("{name}", () => {{
  it("handles tool calls and ui.render", async () => {{
    attach(plugin, new FakeHost());
    const toolRes = (await plugin.handle("tools/call", {{
      name: "{name}_hello",
      arguments: {{}},
    }})) as {{ content: Array<{{ text: string }}> }};
    assert.equal(toolRes.content[0].text, "hello");

    const uiRes = (await renderUi(plugin, "widget")) as {{ document: {{ schema: number }} }};
    assert.equal(uiRes.document.schema, 1);
  }});
}});
'''
    return {
        "carnivore.toml": toml,
        "package.json": pkg,
        "tsconfig.json": tsconfig,
        "main.ts": main_ts,
        "README.md": f"# {name}\n\nTypeScript Carnivore plugin (`schema = 2`).\n",
        "tests/main.test.ts": test_ts,
    }


def _bash_files(name: str, author: str) -> Dict[str, str]:
    toml = "\n".join([
        "schema = 2",
        "api_version = 1",
        f"id = {_safe_toml_str(name)}",
        f"name = {_safe_toml_str(name.title())}",
        'version = "0.1.0"',
        'kind = "plugin"',
        f'description = "Bash sidecar plugin for {name}."',
        f"author = {_safe_toml_str(author)}",
        'license = "MIT"',
        'min_app_version = "1.16.0"',
        "",
        "[run]",
        'cmd = ["bash", "run.sh"]',
        'mode = "rpc"',
        "",
        "[permissions]",
        'read = ["sessions"]',
        "",
        "[permissions.reasons]",
        '"sessions.read" = "Read active sessions for plugin status output."',
        "",
        "[ui]",
        'routes = ["status"]',
        "",
        "[[mcp.tools]]",
        f'name = "{name}_hello"',
        'description = "Says hello from the Bash plugin."',
        'gate = "read"',
        'inputSchema = { type = "object", properties = {}, additionalProperties = false }',
        "",
    ])
    run_sh = f'''#!/bin/bash
set -u

extract_id() {{
  local line="$1"
  local rest="${{line#*\\"id\\":}}"
  rest="${{rest%%,*}}"
  rest="${{rest%%\\}}*}}"
  rest="${{rest//[!0-9]/}}"
  if [[ -z "$rest" ]]; then
    printf '0'
  else
    printf '%s' "$rest"
  fi
}}

while IFS= read -r line; do
  [[ -z "$line" ]] && continue
  id=$(extract_id "$line")
  if [[ "$line" =~ \\"method\\"[[:space:]]*:[[:space:]]*\\"initialize\\" ]]; then
    printf '{{"jsonrpc":"2.0","id":%s,"result":{{"api_version":1,"capabilities":{{"tools":true,"ui":true,"routes":true}},"subscriptions":[]}}}}\\n' "$id"
  elif [[ "$line" =~ \\"method\\"[[:space:]]*:[[:space:]]*\\"ping\\" ]]; then
    printf '{{"jsonrpc":"2.0","id":%s,"result":{{"ok":true}}}}\\n' "$id"
  elif [[ "$line" =~ \\"method\\"[[:space:]]*:[[:space:]]*\\"tools/list\\" ]]; then
    printf '{{"jsonrpc":"2.0","id":%s,"result":{{"tools":[{{"name":"{name}_hello","description":"Says hello from the Bash plugin.","gate":"read","inputSchema":{{"type":"object","properties":{{}},"additionalProperties":false}}}}]}}}}\\n' "$id"
  elif [[ "$line" =~ \\"method\\"[[:space:]]*:[[:space:]]*\\"ui\\.render\\" ]]; then
    printf '{{"jsonrpc":"2.0","id":%s,"result":{{"document":{{"schema":1,"root":{{"type":"section","title":"{name}","children":[{{"type":"text","value":"Ready from Bash"}}]}} }}}}}}\\n' "$id"
  elif [[ "$line" =~ \\"method\\"[[:space:]]*:[[:space:]]*\\"route\\.handle\\" ]]; then
    printf '{{"jsonrpc":"2.0","id":%s,"result":{{"status":200,"body":{{"ok":true,"plugin":"{name}"}}}}}}\\n' "$id"
  elif [[ "$line" =~ \\"method\\"[[:space:]]*:[[:space:]]*\\"tools/call\\" ]]; then
    if [[ -n "${{CARNIVORE_BIN:-}}" && -n "${{CARNIVORE_PLUGIN_SOCK:-}}" && -S "${{CARNIVORE_PLUGIN_SOCK:-}}" ]]; then
      "$CARNIVORE_BIN" sessions list >/dev/null 2>&1 || true
    fi
    printf '{{"jsonrpc":"2.0","id":%s,"result":{{"content":[{{"type":"text","text":"hello"}}]}}}}\\n' "$id"
  elif [[ "$line" =~ \\"method\\"[[:space:]]*:[[:space:]]*\\"shutdown\\" ]]; then
    printf '{{"jsonrpc":"2.0","id":%s,"result":{{"ok":true}}}}\\n' "$id"
    exit 0
  else
    printf '{{"jsonrpc":"2.0","id":%s,"error":{{"code":-32601,"message":"method not found"}}}}\\n' "$id"
  fi
done
'''
    test_py = f'''"""JSON-RPC 2.0 protocol tests for Bash plugin {name}."""

import json
import subprocess
from pathlib import Path


def test_{name}_bash_jsonrpc() -> None:
    root = Path(__file__).resolve().parents[1]
    frames = "\\n".join([
        json.dumps({{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {{}}}}),
        json.dumps({{"jsonrpc": "2.0", "id": 2, "method": "ping", "params": {{}}}}),
        json.dumps({{"jsonrpc": "2.0", "id": 3, "method": "ui.render", "params": {{"surface": "widget", "params": {{}}}}}}),
        json.dumps({{"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {{"name": "{name}_hello", "arguments": {{}}}}}}),
        json.dumps({{"jsonrpc": "2.0", "id": 5, "method": "shutdown", "params": {{}}}}),
    ]) + "\\n"
    proc = subprocess.run(
        [str(root / "run.sh")],
        cwd=str(root),
        input=frames,
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    replies = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    assert [r["id"] for r in replies] == [1, 2, 3, 4, 5]
    assert replies[1]["result"] == {{"ok": True}}
    assert replies[2]["result"]["document"]["schema"] == 1
    assert replies[3]["result"]["content"][0]["text"] == "hello"
'''
    return {
        "carnivore.toml": toml,
        "run.sh": run_sh,
        "README.md": f"# {name}\n\nBash Carnivore plugin (`schema = 2`).\n",
        f"tests/test_{name}.py": test_py,
    }


def _widget_files(name: str, author: str) -> Dict[str, str]:
    toml = "\n".join([
        "schema = 2",
        f"id = {_safe_toml_str(name)}",
        f"name = {_safe_toml_str(name.title())}",
        'version = "0.1.0"',
        'kind = "widget"',
        f'description = "Declarative widget plugin for {name}."',
        f"author = {_safe_toml_str(author)}",
        'license = "MIT"',
        'min_app_version = "1.16.0"',
        "",
        "[run]",
        'cmd = ["python3", "main.py"]',
        'mode = "rpc"',
        "",
        "[permissions]",
        'read = ["sessions"]',
        "",
        "[permissions.reasons]",
        '"sessions.read" = "Read session counts to display in the widget."',
        "",
        "[ui]",
        'routes = ["refresh"]',
        "",
        "[ui.widget]",
        f'title = "{name.title()}"',
        'sizes = ["medium", "large"]',
        "",
    ])
    main_py = f'''"""Widget plugin {name}: renders validated schema = 1 declarative UI."""

from __future__ import annotations

import asyncio
from typing import Any, Dict

from cplug_sdk import Plugin

plugin = Plugin()


@plugin.route("refresh")
async def refresh(request: Dict[str, Any]) -> Dict[str, Any]:
    await plugin.host.call("ui.invalidate", {{"surface": "widget"}})
    return {{"status": 200, "body": {{"refreshed": True}}}}


@plugin.ui("widget")
async def render_widget(params: Dict[str, Any]) -> Dict[str, Any]:
    return {{
        "schema": 1,
        "root": {{
            "type": "section",
            "title": "{name.title()}",
            "children": [
                {{
                    "type": "row",
                    "gap": 2,
                    "children": [
                        {{"type": "stat", "label": "Status", "value": "OK", "tone": "accent"}},
                        {{"type": "button", "label": "Refresh", "action": {{"call": "route", "route": "refresh"}}}},
                    ],
                }}
            ],
        }},
    }}


if __name__ == "__main__":
    asyncio.run(plugin.serve())
'''
    test_py = f'''"""UI document validation tests for widget plugin {name}."""

import asyncio

from cplug_sdk.testing import FakeHost, attach, render_ui
from src.plugins.host import ui_doc

import main as entry


def test_{name}_widget_doc_validates() -> None:
    attach(entry.plugin, FakeHost())
    res = asyncio.run(render_ui(entry.plugin, "widget"))
    validated = ui_doc.validate(res["document"], routes=("refresh",), tools=())
    assert validated["schema"] == 1
'''
    return {
        "carnivore.toml": toml,
        "main.py": main_py,
        "README.md": f"# {name}\n\nWidget Carnivore plugin (`schema = 2`).\n",
        f"tests/test_{name}.py": test_py,
    }


def _channel_files(name: str, author: str) -> Dict[str, str]:
    toml = "\n".join([
        "schema = 2",
        f"id = {_safe_toml_str(name)}",
        f"name = {_safe_toml_str(name.title())}",
        'version = "0.1.0"',
        'kind = "plugin"',
        f'description = "Webhook and notification channel plugin for {name}."',
        f"author = {_safe_toml_str(author)}",
        'license = "MIT"',
        'min_app_version = "1.16.0"',
        "",
        "[run]",
        'cmd = ["python3", "main.py"]',
        'mode = "rpc"',
        "",
        "[permissions]",
        'write = ["notify"]',
        'secrets = [{ key = "webhook_secret", label = "Inbound HMAC secret" }]',
        'network = [{ host = "hooks.example.com", reason = "Deliver outbound channel alerts", methods = ["POST"] }]',
        "",
        "[permissions.reasons]",
        'notify = "Display toast notifications for incoming webhook events."',
        '"hooks.inbound:inbound" = "Receive verified inbound webhook events."',
        "",
        "[webhooks.inbound]",
        'hmac_secret = "webhook_secret"',
        'header = "X-Webhook-Signature"',
        "",
        "[channels.alerts]",
        'url = "https://hooks.example.com/ingest"',
        'method = "POST"',
        'label = "Alerts Webhook"',
        "",
    ])
    main_py = f'''"""Inbound webhook + outbound notification handler for {name}."""

from __future__ import annotations

import asyncio
from typing import Any, Dict

from cplug_sdk import Plugin

plugin = Plugin()


@plugin.on_event("webhook.inbound")
async def on_inbound(seq: Any, payload: Dict[str, Any]) -> None:
    title = str((payload or {{}}).get("hook") or "{name}")
    await plugin.host.notify.toast(ref="app", title=f"Webhook {{title}}")


if __name__ == "__main__":
    asyncio.run(plugin.serve())
'''
    test_py = f'''"""Webhook event delivery test for {name}."""

import asyncio

from cplug_sdk.testing import FakeHost, attach

import main as entry


def test_{name}_webhook_event() -> None:
    fake = FakeHost()
    attach(entry.plugin, fake)
    asyncio.run(entry.plugin.handle("event.deliver", {{"family": "webhook.inbound", "seq": 1, "payload": {{"hook": "inbound", "payload": {{"ok": True}}}}}}))
    assert fake.calls and fake.calls[0][0] == "notify.toast"
'''
    return {
        "carnivore.toml": toml,
        "main.py": main_py,
        "README.md": f"# {name}\n\nChannel & Webhook Carnivore plugin (`schema = 2`).\n",
        f"tests/test_{name}.py": test_py,
    }


def _agent_harness_files(name: str, author: str) -> Dict[str, str]:
    toml = "\n".join([
        "schema = 2",
        f"id = {_safe_toml_str(name)}",
        f"name = {_safe_toml_str(name.title())}",
        'version = "0.1.0"',
        'kind = "plugin"',
        f'description = "Agent CLI harness rule plugin for {name}."',
        f"author = {_safe_toml_str(author)}",
        'license = "MIT"',
        'min_app_version = "1.16.0"',
        "",
        f'harnesses = ["harnesses/{name}.toml"]',
        "",
        "[permissions]",
        'read = ["sessions"]',
        "",
        "[permissions.reasons]",
        '"sessions.read" = "Read session metadata for harness rule matching."',
        "",
    ])
    harness_toml = "\n".join([
        f'id = "{name}cli"',
        'version = "0.1.0"',
        "min_engine_version = 1",
        f'aliases = ["{name}"]',
        "",
        "[[rules]]",
        'id = "approval_blocked"',
        'state = "blocked"',
        "priority = 300",
        'region = "bottom_non_empty_lines(10)"',
        'contains = ["approve?"]',
        "",
        "[[rules]]",
        'id = "busy_working"',
        'state = "working"',
        "priority = 100",
        'region = "bottom_non_empty_lines(4)"',
        'contains = ["working..."]',
        "",
    ])
    test_py = f'''"""Agent CLI harness manifest test for {name}."""

from pathlib import Path

from src.core.agent_manifests import engine
from src.plugins.sdk.manifest_v2 import load_manifest_v2


def test_{name}_harness_validates() -> None:
    root = Path(__file__).resolve().parents[1]
    manifest = load_manifest_v2(root, allow_tier_override=True)
    assert manifest.tier0 is True
    parsed = engine.parse_manifest((root / manifest.harnesses[0]).read_text(encoding="utf-8"))
    assert parsed is not None
    assert parsed.id == "{name}cli"
'''
    return {
        "carnivore.toml": toml,
        f"harnesses/{name}.toml": harness_toml,
        "README.md": f"# {name}\n\nAgent CLI Harness Carnivore plugin (`schema = 2`).\n",
        f"tests/test_{name}.py": test_py,
    }


def scaffold(dest: Path, name: str, template: str = DEFAULT_TEMPLATE, author: str = DEFAULT_AUTHOR) -> Dict[str, str]:
    if template not in TEMPLATES:
        raise TemplateError(f"template must be one of {', '.join(TEMPLATES)}")
    prob = name_problem(name)
    if prob:
        raise TemplateError(prob)
    if not re.match(r"^[A-Za-z0-9_ .@<>-]{1,80}$", author or ""):
        raise TemplateError("author must be 1..80 printable characters")
    if dest.exists():
        raise TemplateError(f"{dest} already exists")

    builders = {
        "no-code": _no_code_files,
        "python": _python_files,
        "typescript": _typescript_files,
        "bash": _bash_files,
        "widget": _widget_files,
        "channel": _channel_files,
        "agent-harness": _agent_harness_files,
    }
    files = builders[template](name, author)
    files.setdefault("LICENSE.md", _mit_license(author))
    for rel, content in files.items():
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        if target.suffix.lower() in (".sh", ".bash"):
            target.chmod(0o755)
    return files
