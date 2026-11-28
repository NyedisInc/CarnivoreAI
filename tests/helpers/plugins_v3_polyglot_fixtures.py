
from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path
from typing import Dict, Mapping, Optional, Sequence

from src.plugins.runtime import sandbox

DEFAULT_MIT_LICENSE = (
    "MIT License\n\nPermission is hereby granted, free of charge, to any person obtaining a copy "
    "of this software to deal in the Software without restriction.\n"
)


def has_node() -> bool:
    try:
        sandbox._find_node()
        return True
    except sandbox.SandboxUnavailable:
        return False


def has_bun() -> bool:
    try:
        sandbox._find_bun()
        return True
    except sandbox.SandboxUnavailable:
        return False


def has_cc() -> bool:
    return shutil.which("cc") is not None


def write_plugin_files(folder: Path, files: Mapping[str, str | bytes], *, exec_paths: Sequence[str] = ()) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        target = folder / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(textwrap.dedent(content).lstrip("\n"), encoding="utf-8")
        target.chmod(0o755 if rel in exec_paths else 0o644)
    return folder


def build_python_plugin(
    root: Path,
    plugin_id: str = "pyplug",
    *,
    mode: str = "rpc",
    version: str = "1.0.0",
    tier: str = "catalog",
    extra_toml: str = "",
    main_py: Optional[str] = None,
) -> Path:
    folder = root / plugin_id
    if main_py is None:
        if mode == "oneshot":
            main_py = """
                import json, sys
                req = json.loads(sys.stdin.read() or "{}")
                args = ((req.get("params") or {}).get("arguments") or {})
                print(json.dumps({"runtime": "python-oneshot", "echo": args.get("msg", "ok")}))
            """
        else:
            main_py = f"""
                from cplug_sdk import Plugin

                plugin = Plugin()

                @plugin.ui("widget")
                async def render_widget(params):
                    return {{
                        "schema": 2,
                        "root": {{
                            "type": "column",
                            "children": [{{"type": "text", "text": "{plugin_id}:" + str(params.get("theme", "dark"))}}],
                        }},
                    }}

                @plugin.tool("ping", "Ping tool", {{"type": "object", "properties": {{"msg": {{"type": "string"}}}}}}, gate="read")
                async def ping(args, _caller):
                    return {{"runtime": "python-rpc", "echo": args.get("msg", "pong")}}
            """
    toml = f"""
        schema = 2
        id = "{plugin_id}"
        name = "{plugin_id.title()}"
        version = "{version}"
        kind = "plugin"
        description = "Python E2E fixture plugin"
        author = "Tester"
        license = "MIT"
        tier = "{tier}"

        [run]
        cmd = ["python3", "main.py"]
        mode = "{mode}"

        [mcp]
        [[mcp.tools]]
        name = "ping"
        description = "Ping tool"
        gate = "read"
        inputSchema = {{ type = "object", properties = {{ msg = {{ type = "string" }} }} }}
        {extra_toml}
    """
    return write_plugin_files(
        folder,
        {
            "carnivore.toml": toml,
            "main.py": main_py,
            "LICENSE.md": DEFAULT_MIT_LICENSE,
        },
    )


def build_node_plugin(
    root: Path,
    plugin_id: str = "nodeplug",
    *,
    mode: str = "rpc",
    version: str = "1.0.0",
    tier: str = "catalog",
    extra_toml: str = "",
    main_mjs: Optional[str] = None,
) -> Path:
    folder = root / plugin_id
    if main_mjs is None:
        if mode == "oneshot":
            main_mjs = """
                import fs from "node:fs";
                const req = JSON.parse(fs.readFileSync(0, "utf8") || "{}");
                const args = (req.params && req.params.arguments) || {};
                process.stdout.write(JSON.stringify({ runtime: "node-oneshot", echo: args.msg ?? "ok" }) + "\\n");
            """
        else:
            main_mjs = """
                import { Plugin } from "@carnivore/plugin-sdk";

                const plugin = new Plugin();

                plugin.tool(
                  "ping",
                  "Ping tool",
                  { type: "object", properties: { msg: { type: "string" } } },
                  async (args) => ({ runtime: "node-rpc", echo: args?.msg ?? "pong" }),
                  { gate: "read" },
                );

                await plugin.serve();
            """
    toml = f"""
        schema = 2
        id = "{plugin_id}"
        name = "{plugin_id.title()}"
        version = "{version}"
        kind = "plugin"
        description = "Node.js E2E fixture plugin"
        author = "Tester"
        license = "MIT"
        tier = "{tier}"

        [run]
        cmd = ["node", "main.mjs"]
        mode = "{mode}"

        [mcp]
        [[mcp.tools]]
        name = "ping"
        description = "Ping tool"
        gate = "read"
        inputSchema = {{ type = "object", properties = {{ msg = {{ type = "string" }} }} }}
        {extra_toml}
    """
    return write_plugin_files(
        folder,
        {
            "carnivore.toml": toml,
            "main.mjs": main_mjs,
            "LICENSE.md": DEFAULT_MIT_LICENSE,
        },
    )


def build_bun_plugin(
    root: Path,
    plugin_id: str = "bunplug",
    *,
    mode: str = "rpc",
    version: str = "1.0.0",
    tier: str = "catalog",
    extra_toml: str = "",
    main_ts: Optional[str] = None,
) -> Path:
    folder = root / plugin_id
    if main_ts is None:
        if mode == "oneshot":
            main_ts = """
                const text = await new Response(Bun.stdin.stream()).text();
                const req = JSON.parse(text || "{}");
                const args = (req.params && req.params.arguments) || {};
                console.log(JSON.stringify({ runtime: "bun-oneshot", echo: args.msg ?? "ok" }));
            """
        else:
            main_ts = """
                const decoder = new TextDecoder();
                let buf = "";
                for await (const chunk of Bun.stdin.stream()) {
                  buf += decoder.decode(chunk);
                  let idx;
                  while ((idx = buf.indexOf("\\n")) >= 0) {
                    const line = buf.slice(0, idx).trim();
                    buf = buf.slice(idx + 1);
                    if (!line) continue;
                    const msg = JSON.parse(line);
                    if (msg.method === "initialize") {
                      console.log(JSON.stringify({ jsonrpc: "2.0", id: msg.id, result: { api_version: 1, capabilities: { tools: true }, subscriptions: [] } }));
                    } else if (msg.method === "tools/list") {
                      console.log(JSON.stringify({ jsonrpc: "2.0", id: msg.id, result: { tools: [{ name: "ping", description: "Ping tool", gate: "read", inputSchema: { type: "object", properties: { msg: { type: "string" } } } }] } }));
                    } else if (msg.method === "tools/call") {
                      console.log(JSON.stringify({ jsonrpc: "2.0", id: msg.id, result: { runtime: "bun-rpc", echo: msg.params?.arguments?.msg ?? "pong" } }));
                    } else if (msg.method === "shutdown") {
                      console.log(JSON.stringify({ jsonrpc: "2.0", id: msg.id, result: { ok: true } }));
                      process.exit(0);
                    }
                  }
                }
            """
    toml = f"""
        schema = 2
        id = "{plugin_id}"
        name = "{plugin_id.title()}"
        version = "{version}"
        kind = "plugin"
        description = "Bun E2E fixture plugin"
        author = "Tester"
        license = "MIT"
        tier = "{tier}"

        [run]
        cmd = ["bun", "run", "main.ts"]
        mode = "{mode}"

        [mcp]
        [[mcp.tools]]
        name = "ping"
        description = "Ping tool"
        gate = "read"
        inputSchema = {{ type = "object", properties = {{ msg = {{ type = "string" }} }} }}
        {extra_toml}
    """
    return write_plugin_files(
        folder,
        {
            "carnivore.toml": toml,
            "main.ts": main_ts,
            "LICENSE.md": DEFAULT_MIT_LICENSE,
        },
    )


def build_bash_plugin(
    root: Path,
    plugin_id: str = "bashplug",
    *,
    mode: str = "oneshot",
    version: str = "1.0.0",
    tier: str = "catalog",
    read_sessions: bool = True,
    extra_toml: str = "",
    main_sh: Optional[str] = None,
) -> Path:
    folder = root / plugin_id
    if main_sh is None:
        if mode == "oneshot":
            if read_sessions:
                main_sh = """#!/bin/bash
IFS= read -r _req || true
sess=$("$CARNIVORE_BIN" sessions list)
printf '{"runtime":"bash-oneshot","sessions":%s}\n' "$sess"
"""
            else:
                main_sh = """#!/bin/bash
IFS= read -r _req || true
printf '{"runtime":"bash-oneshot","ok":true}\n'
"""
        else:
            call_block = (
                '    sess=$("$CARNIVORE_BIN" sessions list)\n'
                '    printf \'{"jsonrpc":"2.0","id":%s,"result":{"runtime":"bash-rpc","sessions":%s}}\\n\' "$id" "$sess"'
                if read_sessions
                else '    printf \'{"jsonrpc":"2.0","id":%s,"result":{"runtime":"bash-rpc","ok":true}}\\n\' "$id"'
            )
            main_sh = f"""#!/bin/bash
while IFS= read -r line; do
  id="${{line#*\\"id\\":}}"
  id="${{id%%,*}}"
  id="${{id%%\\}}*}}"
  id="${{id//[!0-9]/}}"
  if [[ "$line" == *'"initialize"'* ]]; then
    printf '{{"jsonrpc":"2.0","id":%s,"result":{{"api_version":1,"capabilities":{{"tools":true}},"subscriptions":[]}}}}\\n' "$id"
  elif [[ "$line" == *'"tools/list"'* ]]; then
    printf '{{"jsonrpc":"2.0","id":%s,"result":{{"tools":[{{"name":"ping","description":"Ping tool","gate":"read","inputSchema":{{"type":"object","properties":{{"msg":{{"type":"string"}}}}}}}}]}}}}\\n' "$id"
  elif [[ "$line" == *'"tools/call"'* ]]; then
{call_block}
  elif [[ "$line" == *'"shutdown"'* ]]; then
    printf '{{"jsonrpc":"2.0","id":%s,"result":{{"ok":true}}}}\\n' "$id"
    exit 0
  fi
done
"""
    perms_block = ""
    if read_sessions:
        perms_block = """
        [permissions]
        read = ["sessions"]

        [permissions.reasons]
        "sessions.read" = "Read active session list via $CARNIVORE_BIN"
        """
    toml = f"""
        schema = 2
        id = "{plugin_id}"
        name = "{plugin_id.title()}"
        version = "{version}"
        kind = "plugin"
        description = "Bash $CARNIVORE_BIN E2E fixture plugin"
        author = "Tester"
        license = "MIT"
        tier = "{tier}"

        [run]
        cmd = ["bash", "main.sh"]
        mode = "{mode}"
        {perms_block}
        [mcp]
        [[mcp.tools]]
        name = "ping"
        description = "Ping tool"
        gate = "read"
        inputSchema = {{ type = "object", properties = {{ msg = {{ type = "string" }} }} }}
        {extra_toml}
    """
    return write_plugin_files(
        folder,
        {
            "carnivore.toml": toml,
            "main.sh": main_sh,
            "LICENSE.md": DEFAULT_MIT_LICENSE,
        },
        exec_paths=("main.sh",),
    )


def build_c_binary_plugin(
    root: Path,
    plugin_id: str = "cbinplug",
    *,
    mode: str = "rpc",
    version: str = "1.0.0",
    tier: str = "catalog",
    extra_toml: str = "",
) -> Path:
    if not has_cc():
        raise RuntimeError("cc compiler not available on PATH")
    folder = root / plugin_id
    folder.mkdir(parents=True, exist_ok=True)
    src_c = root / f"{plugin_id}.c"
    if mode == "oneshot":
        src_c.write_text(
            r"""
#include <stdio.h>
int main(void) {
    char buf[4096];
    size_t _n = fread(buf, 1, sizeof(buf) - 1, stdin);
    (void)_n;
    printf("{\"runtime\":\"binary-oneshot\",\"ok\":true}\n");
    return 0;
}
""",
            encoding="utf-8",
        )
    else:
        src_c.write_text(
            r"""
#include <stdio.h>
#include <string.h>

static void extract_id(const char *line, char *out, size_t cap) {
    const char *p = strstr(line, "\"id\"");
    if (!p) { snprintf(out, cap, "null"); return; }
    p = strchr(p + 4, ':');
    if (!p) { snprintf(out, cap, "null"); return; }
    p++;
    while (*p == ' ' || *p == '\t') p++;
    if (*p == '"') {
        size_t i = 0;
        out[i++] = *p++;
        while (*p && i + 2 < cap) {
            if (*p == '\\' && p[1]) {
                out[i++] = *p++;
                out[i++] = *p++;
                continue;
            }
            out[i++] = *p;
            if (*p == '"') break;
            p++;
        }
        out[i] = '\0';
        return;
    }
    size_t i = 0;
    while (*p && *p != ',' && *p != '}' && *p != ' ' && *p != '\t' && *p != '\r' && *p != '\n' && i + 1 < cap) {
        out[i++] = *p++;
    }
    out[i] = '\0';
    if (i == 0) snprintf(out, cap, "null");
}

int main(void) {
    char line[4096];
    char id[128];
    while (fgets(line, sizeof(line), stdin)) {
        extract_id(line, id, sizeof(id));
        if (strstr(line, "\"initialize\"")) {
            printf("{\"jsonrpc\":\"2.0\",\"id\":%s,\"result\":{\"api_version\":1,\"capabilities\":{\"tools\":true},\"subscriptions\":[]}}\n", id);
            fflush(stdout);
        } else if (strstr(line, "\"tools/list\"")) {
            printf("{\"jsonrpc\":\"2.0\",\"id\":%s,\"result\":{\"tools\":[{\"name\":\"ping\",\"description\":\"Ping tool\",\"gate\":\"read\",\"inputSchema\":{\"type\":\"object\",\"properties\":{\"msg\":{\"type\":\"string\"}}}}]}}\n", id);
            fflush(stdout);
        } else if (strstr(line, "\"tools/call\"")) {
            printf("{\"jsonrpc\":\"2.0\",\"id\":%s,\"result\":{\"runtime\":\"binary-rpc\",\"ok\":true}}\n", id);
            fflush(stdout);
        } else if (strstr(line, "\"shutdown\"")) {
            printf("{\"jsonrpc\":\"2.0\",\"id\":%s,\"result\":{\"ok\":true}}\n", id);
            fflush(stdout);
            break;
        }
    }
    return 0;
}
""",
            encoding="utf-8",
        )
    bin_path = folder / "plugbin"
    subprocess.run(["cc", "-O2", str(src_c), "-o", str(bin_path)], check=True)
    bin_path.chmod(0o755)
    toml = f"""
        schema = 2
        id = "{plugin_id}"
        name = "{plugin_id.title()}"
        version = "{version}"
        kind = "plugin"
        description = "Compiled binary E2E fixture plugin"
        author = "Tester"
        license = "MIT"
        tier = "{tier}"

        [run]
        cmd = ["./plugbin"]
        mode = "{mode}"

        [mcp]
        [[mcp.tools]]
        name = "ping"
        description = "Ping tool"
        gate = "read"
        inputSchema = {{ type = "object", properties = {{ msg = {{ type = "string" }} }} }}
        {extra_toml}
    """
    return write_plugin_files(
        folder,
        {
            "carnivore.toml": toml,
            "LICENSE.md": DEFAULT_MIT_LICENSE,
        },
    )


def build_tier0_declarative_plugin(
    root: Path,
    plugin_id: str = "tier0plug",
    *,
    version: str = "1.0.0",
    tier: str = "catalog",
    include_widget: bool = True,
    include_channel: bool = True,
    include_harness: bool = True,
    include_macro: bool = True,
    webhook_url: str = "https://hooks.example.com/notify",
) -> Path:
    folder = root / plugin_id
    lines = [
        "schema = 2",
        f'id = "{plugin_id}"',
        f'name = "{plugin_id.title()}"',
        f'version = "{version}"',
        'kind = "plugin"',
        'description = "Tier 0 no-code declarative plugin"',
        'author = "Tester"',
        'license = "MIT"',
        'min_app_version = "1.16.0"',
        "api_version = 1",
        f'tier = "{tier}"',
        "",
    ]
    files: Dict[str, str | bytes] = {"LICENSE.md": DEFAULT_MIT_LICENSE}

    read_perms = ["sessions"] if include_macro else []
    write_perms = ["sessions.message"] if include_macro else []
    net_perms = []
    if include_channel:
        host = webhook_url.split("://", 1)[1].split("/", 1)[0].split(":", 1)[0]
        net_perms.append(f'{{ host = "{host}", methods = ["POST"], reason = "Deliver declarative alerts" }}')
    if read_perms or write_perms or net_perms:
        lines.append("[permissions]")
        if read_perms:
            lines.append(f"read = {json.dumps(read_perms)}")
        if write_perms:
            lines.append(f"write = {json.dumps(write_perms)}")
        if net_perms:
            lines.append(f"network = [{', '.join(net_perms)}]")
        lines.append("")

    if include_widget:
        lines += [
            "[ui.widget]",
            f'title = "{plugin_id} Widget"',
            'sizes = ["medium", "large"]',
            f'document = {{ schema = 1, root = {{ type = "text", value = "{plugin_id} declarative" }} }}',
            "",
        ]

    if include_macro:
        lines += [
            "[[ui.commands]]",
            'id = "send_ping"',
            'title = "Send Ping"',
            "steps = [",
            '  { method = "sessions.message", params = { ref = "{{session_ref}}", line = "hello from macro" } }',
            "]",
            "",
        ]

    if include_channel:
        lines += [
            "[channels.alerts]",
            f'url = "{webhook_url}"',
            'method = "POST"',
            'body_template = \'{"msg":"{{text}}"}\'',
            "",
        ]

    if include_harness:
        harness_file = f"{plugin_id}_cli.toml"
        lines += [
            "[harnesses]",
            f'files = ["{harness_file}"]',
            "",
        ]
        files[harness_file] = f"""
            id = "{plugin_id}_cli"
            version = "1"
            aliases = ["{plugin_id}a"]

            [[rules]]
            id = "busy"
            state = "working"
            priority = 10
            region = "bottom_lines(3)"
            contains = ["thinking"]
        """

    files["carnivore.toml"] = "\n".join(lines) + "\n"
    return write_plugin_files(folder, files)
