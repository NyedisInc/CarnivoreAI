
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List, Optional

URL_ENV = "CARNIVORE_MCP_URL"
SERVER_NAME = "carnivore"
CODEX_TOOL_TIMEOUT_SEC = 120

CLAUDE_MCP_CONFIG_FLAG = "--mcp-config"

CLAUDE_DEV_CHANNELS_FLAG = "--dangerously-load-development-channels"
CHANNEL_HEADER = "X-Carnivore-Channel"
CHANNEL_HEADER_VALUE = "1"

BRIDGE_SCRIPT = Path(__file__).resolve().parents[1] / "core" / "mcp_bridge" / "stdio_bridge.py"
BRIDGE_COMMAND = "python3"
PAYLOAD_PYTHON_ENV = "CARNIVORE_PAYLOAD_PYTHON"
BRIDGE_CHANNEL_ENV = "CARNIVORE_MCP_CHANNEL"
BYTECODE_ENVS = ("PYTHONPYCACHEPREFIX", "PYTHONDONTWRITEBYTECODE")

APP_INJECTED_CLAUDE_FLAGS = frozenset({CLAUDE_MCP_CONFIG_FLAG, CLAUDE_DEV_CHANNELS_FLAG})


def bridge_command() -> str:
    candidate = os.environ.get(PAYLOAD_PYTHON_ENV)
    if candidate and os.path.isabs(candidate) and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
        return candidate
    return BRIDGE_COMMAND


def mcp_url(port: int) -> str:
    return f"http://127.0.0.1:{port}/mcp"


def spawn_env(port: int) -> Dict[str, str]:
    return {URL_ENV: mcp_url(port)}


def registration_url(pane_launch: bool, enabled: bool, port: Optional[int]) -> Optional[str]:
    if not (pane_launch and enabled and port):
        return None
    return mcp_url(port)


def _http_server_doc(channel: bool) -> dict:
    headers = {"Authorization": "Bearer ${CLOUDECODE_HOOK_TOKEN}",
               "X-Carnivore-Session": "${CLOUDECODE_SESSION_ID}"}
    if channel:
        headers[CHANNEL_HEADER] = CHANNEL_HEADER_VALUE
    return {"type": "http", "url": "${" + URL_ENV + "}", "headers": headers}


def _stdio_server_doc(channel: bool, script: Path) -> dict:
    env = {URL_ENV: "${" + URL_ENV + "}", "CLOUDECODE_HOOK_TOKEN": "${CLOUDECODE_HOOK_TOKEN}",
           "CLOUDECODE_SESSION_ID": "${CLOUDECODE_SESSION_ID}"}
    if channel:
        env[BRIDGE_CHANNEL_ENV] = "1"
    command = bridge_command()
    if command != BRIDGE_COMMAND:
        env.update({k: os.environ[k] for k in BYTECODE_ENVS if os.environ.get(k)})
    return {"type": "stdio", "command": command, "args": [str(script)], "env": env}


def claude_args(channel: bool = False, bridge_script: Optional[Path] = BRIDGE_SCRIPT) -> List[str]:
    use_bridge = bridge_script is not None and bridge_script.is_file()
    server = _stdio_server_doc(channel, bridge_script) if use_bridge else _http_server_doc(channel)
    doc = {"mcpServers": {SERVER_NAME: server}}
    args = [CLAUDE_MCP_CONFIG_FLAG + "=" + json.dumps(doc, separators=(",", ":"))]
    if channel:
        args.append(f"{CLAUDE_DEV_CHANNELS_FLAG}=server:{SERVER_NAME}")
    return args


def codex_args(url: str) -> List[str]:
    p = f"mcp_servers.{SERVER_NAME}."
    return [
        "-c", f"{p}url={json.dumps(url)}",
        "-c", f'{p}bearer_token_env_var="CLOUDECODE_HOOK_TOKEN"',
        "-c", f'{p}env_http_headers={{"X-Carnivore-Session"="CLOUDECODE_SESSION_ID"}}',
        "-c", f"{p}tool_timeout_sec={CODEX_TOOL_TIMEOUT_SEC}",
    ]
