
import json
import os

from src.core.mcp_health import cached_files
from src.core.mcp_health.config_argv import mcp_config_values
from src.core.mcp_health.config_claude import claude_servers
from src.core.mcp_health.config_codex import codex_servers, overrides

SECRET = "sk-test-not-a-real-secret-1678"


def _write(path, doc):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(doc if isinstance(doc, str) else json.dumps(doc))


def _claude_fixture(tmp_path):
    cached_files.reset()
    home = tmp_path / "profile"
    cwd = str(tmp_path / "My Project")
    _write(str(home / ".claude.json"), {
        "mcpServers": {
            "context7": {"type": "http", "url": "https://mcp.example.com/mcp?key=" + SECRET,
                         "headers": {"Authorization": "Bearer " + SECRET}},
            "memory": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-memory"], "env": {"K": SECRET}},
            "toggled": {"command": "toggled-server"},
        },
        "projects": {cwd: {"mcpServers": {"memory": {"command": "local-memory"}},
                           "disabledMcpServers": ["toggled"]}},
    })
    _write(os.path.join(cwd, ".mcp.json"), {"mcpServers": {
        "approved": {"type": "sse", "url": "http://127.0.0.1:5011/sse"},
        "unapproved": {"type": "http", "url": "http://127.0.0.1:5012/mcp"},
        "higgsfield": {"type": "http", "url": "https://mcp.higgsfield.ai/"},
    }})
    _write(os.path.join(cwd, ".claude", "settings.local.json"),
           {"enabledMcpjsonServers": ["approved", "higgsfield"], "disabledMcpjsonServers": ["higgsfield"]})
    shared = tmp_path / "shared dir" / "carnivore-mcp.json"
    _write(str(shared), {"mcpServers": {"seq": {"command": "npx", "args": ["-y", "seq-thinking"]}}})
    inline = json.dumps({"mcpServers": {"carnivore": {"type": "http", "url": "${CARNIVORE_MCP_URL}",
                                                      "headers": {"Authorization": "Bearer ${TOKEN}"}}}})
    command = f"claude --dangerously-skip-permissions --mcp-config={inline} --mcp-config={shared} --resume x"
    return command, cwd, str(home)


def test_claude_scopes_approval_disable_and_precedence(tmp_path):
    command, cwd, home = _claude_fixture(tmp_path)
    config = claude_servers(command, cwd, home)
    by = {s.name: s for s in config.servers}
    assert sorted(by) == ["approved", "carnivore", "context7", "memory", "seq"]
    assert by["memory"].command == "local-memory" and by["memory"].scope == "local"
    assert by["context7"].url == "https://mcp.example.com/mcp"
    assert by["approved"].transport == "sse" and by["carnivore"].url is None
    assert by["seq"].scope == "mcp-config-file" and by["carnivore"].scope == "mcp-config"
    assert {"toggled", "unapproved", "higgsfield"} <= config.excluded
    assert SECRET not in repr(config)


def test_claude_strict_flag_and_variadic_values(tmp_path):
    command, cwd, home = _claude_fixture(tmp_path)
    strict = claude_servers(command + " --strict-mcp-config", cwd, home)
    assert sorted(s.name for s in strict.servers) == ["carnivore", "seq"]
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    _write(str(a), {"mcpServers": {}})
    _write(str(b), {"mcpServers": {}})
    assert mcp_config_values(f"claude --mcp-config {a} {b} --resume") == [str(a), str(b)]


def test_codex_layers_overrides_and_enabled_false(tmp_path):
    cached_files.reset()
    home = tmp_path / "codex home"
    cwd = str(tmp_path / "proj")
    _write(str(home / "config.toml"), (
        '[mcp_servers.docs]\nurl = "https://docs.example.com/mcp?token=' + SECRET + '"\n'
        'bearer_token_env_var = "DOCS_TOKEN"\nhttp_headers = { "X-Key" = "' + SECRET + '" }\n\n'
        '[mcp_servers.files]\ncommand = "npx"\nargs = ["-y", "@mcp/files"]\nenv = { K = "' + SECRET + '" }\n\n'
        '[mcp_servers.off]\ncommand = "off-server"\nenabled = false\n'
    ))
    _write(os.path.join(cwd, ".codex", "config.toml"), '[mcp_servers.files]\nargs = ["@mcp/files-project"]\n')
    command = ('/opt/homebrew/bin/codex -c mcp_servers.carnivore.url="http://127.0.0.1:8000/mcp" '
               '-c mcp_servers.carnivore.bearer_token_env_var="CLOUDECODE_HOOK_TOKEN" '
               '-c mcp_servers.carnivore.env_http_headers={"X-Carnivore-Session"="CLOUDECODE_SESSION_ID"} '
               '-c mcp_servers.carnivore.tool_timeout_sec=120 --yolo')
    by = {s.name: s for s in codex_servers(command, cwd, str(home))}
    assert sorted(by) == ["carnivore", "docs", "files"]
    assert by["docs"].url == "https://docs.example.com/mcp" and by["docs"].transport == "http"
    assert by["files"].args == ("@mcp/files-project",)
    assert by["carnivore"].url == "http://127.0.0.1:8000/mcp" and by["carnivore"].scope == "override"
    assert SECRET not in repr(by)
    assert set(overrides(command)["carnivore"]) == {"url"}
