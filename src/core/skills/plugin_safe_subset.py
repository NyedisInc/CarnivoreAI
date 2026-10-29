
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Mapping, Optional

CODE_MANIFEST_KEYS = ("hooks", "mcpServers", "lspServers", "monitors", "settings")

CODE_PATHS = (
    "hooks/hooks.json",
    ".mcp.json",
    ".lsp.json",
    "monitors",
    "settings.json",
    "workflows",
)

_CODE_TOP_SEGMENTS = frozenset({"monitors", "bin", "workflows"})
_CODE_ROOT_FILES = frozenset({"settings.json", ".mcp.json", ".lsp.json"})
_MAX_MD_BYTES = 1024 * 1024
_SHELL_RE = re.compile(r"!`|```!")
_FRONT_CODE_RE = re.compile(
    r"^\s*(?:-\s+)*[\"']?(hooks|allowed-tools|permissionMode|mcpServers)[\"']?\s*:",
    re.IGNORECASE | re.MULTILINE,
)
_HIDING_FRONT_RE = re.compile(
    r"""^\s*(?:-\s+)*(?:["'?!&*]|<<)|(?:^|[:\-\[,])[ \t]*[{&*!]""", re.MULTILINE
)
_FENCE_RE = re.compile(r"^---[^\S\n]*$", re.MULTILINE)


def _markdown_runs_code(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            text = handle.read(_MAX_MD_BYTES + 1).decode("utf-8", "replace")
    except OSError:
        return True
    if len(text) > _MAX_MD_BYTES or _SHELL_RE.search(text):
        return True
    text = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    if text.startswith("---"):
        end = _FENCE_RE.search(text, 3)
        block = text[: end.end()] if end else text
        return bool(_FRONT_CODE_RE.search(block) or _HIDING_FRONT_RE.search(block[3:]))
    return False


SCRIPT_EXTENSIONS = frozenset({
    ".py", ".sh", ".bash", ".zsh", ".fish", ".js", ".mjs", ".cjs", ".ts",
    ".rb", ".pl", ".php", ".ps1", ".bat", ".cmd", ".lua", ".r", ".tcl",
    ".awk", ".command",
})


def staged_has_script_members(root: Path) -> bool:
    failed: List[OSError] = []
    for dirpath, _dirs, files in os.walk(root, followlinks=False, onerror=failed.append):
        for name in files:
            if os.path.splitext(name)[1].lower() in SCRIPT_EXTENSIONS:
                return True
            full = os.path.join(dirpath, name)
            if os.path.islink(full):
                continue
            try:
                with open(full, "rb") as handle:
                    if handle.read(2) == b"#!":
                        return True
            except OSError:
                return True
    return bool(failed)


def folder_declares_code(folder: Path, *, plugin: bool = False, exclude: FrozenSet[str] = frozenset()) -> bool:
    failed = []
    for root, dirs, files in os.walk(folder, onerror=failed.append):
        parts = [part.lower() for part in Path(root).relative_to(folder).parts]
        for name in dirs + files:
            low = name.lower()
            if not parts and (low in _CODE_TOP_SEGMENTS or (low in _CODE_ROOT_FILES and low not in exclude)):
                return True
            if low == ".claude-plugin" and not plugin:
                return True
            if low == "hooks.json" and "hooks" in parts:
                return True
        if any(n.lower().endswith(".md") and _markdown_runs_code(Path(root) / n) for n in files):
            return True
    return bool(failed)


def plugin_declares_code(manifest: Mapping[str, Any], folder: Path) -> bool:
    if any(key in manifest for key in CODE_MANIFEST_KEYS):
        return True
    if any(os.path.lexists(folder / rel) for rel in CODE_PATHS):
        return True
    if folder_declares_code(folder, plugin=True):
        return True
    return _bin_declares_code(folder)


def _bin_declares_code(folder: Path) -> bool:
    bin_dir = folder / "bin"
    if os.path.islink(bin_dir):
        return True
    try:
        return bin_dir.is_dir() and any(bin_dir.iterdir())
    except OSError:
        return True


def plugin_declares_nonmcp_code(manifest: Mapping[str, Any], folder: Path) -> bool:
    if any(key in manifest for key in CODE_MANIFEST_KEYS if key != "mcpServers"):
        return True
    if any(os.path.lexists(folder / rel) for rel in CODE_PATHS if rel != ".mcp.json"):
        return True
    if folder_declares_code(folder, plugin=True, exclude=frozenset({".mcp.json"})):
        return True
    return _bin_declares_code(folder)


MAX_MCP_SERVERS = 16
MAX_MCP_BYTES = 16 * 1024
MCP_ENTRY_KEYS = frozenset({"command", "args", "env"})


def _servers_of(value: Any) -> Any:
    if isinstance(value, dict) and "mcpServers" in value:
        return value["mcpServers"]
    return value


def mcp_problems(manifest: Mapping[str, Any], mcp_file: Optional[bytes]) -> List[str]:
    problems: List[str] = []
    sources: List[tuple] = []
    if "mcpServers" in manifest:
        sources.append(("plugin.json mcpServers", manifest["mcpServers"]))
    if mcp_file is not None:
        try:
            if len(mcp_file) > MAX_MCP_BYTES:
                problems.append(".mcp.json is larger than 16 KiB")
            else:
                sources.append((".mcp.json", _servers_of(json.loads(mcp_file.decode("utf-8")))))
        except (UnicodeDecodeError, ValueError):
            problems.append(".mcp.json is not utf-8 json")
    for label, servers in sources:
        if not isinstance(servers, dict):
            problems.append(f"{label} must be an object of servers")
            continue
        if len(servers) > MAX_MCP_SERVERS:
            problems.append(f"{label} declares more than {MAX_MCP_SERVERS} servers")
        if len(json.dumps(servers)) > MAX_MCP_BYTES:
            problems.append(f"{label} is larger than 16 KiB")
        for name, entry in servers.items():
            if not isinstance(entry, dict) or not isinstance(entry.get("command"), str) or not entry["command"].strip():
                problems.append(f"{label} server {str(name)[:40]!r} needs a command string")
                continue
            extra = sorted(str(k)[:20] for k in entry if k not in MCP_ENTRY_KEYS)
            if extra:
                problems.append(f"{label} server {str(name)[:40]!r} has unsupported keys {extra}")
            args, env = entry.get("args", []), entry.get("env", {})
            if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
                problems.append(f"{label} server {str(name)[:40]!r} args must be a list of strings")
            if not isinstance(env, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in env.items()):
                problems.append(f"{label} server {str(name)[:40]!r} env must map strings to strings")
    return problems


def _read_json_file(path: Path) -> Any:
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_MCP_BYTES * 4:
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None


def staged_mcp_servers(staged_path: Path) -> List[Dict[str, Any]]:
    found: List[Dict[str, Any]] = []
    manifest = _read_json_file(Path(staged_path) / ".claude-plugin" / "plugin.json")
    mcp = _read_json_file(Path(staged_path) / ".mcp.json")
    declared = []
    if isinstance(manifest, dict) and "mcpServers" in manifest:
        declared.append(manifest["mcpServers"])
    if mcp is not None:
        declared.append(_servers_of(mcp))
    for servers in declared:
        if not isinstance(servers, dict):
            continue
        for name, entry in servers.items():
            if not isinstance(entry, dict):
                continue
            args, env = entry.get("args"), entry.get("env")
            found.append({
                "name": str(name),
                "command": str(entry.get("command", "")),
                "args": [str(a) for a in args] if isinstance(args, list) else [],
                "env_keys": sorted(str(k) for k in env) if isinstance(env, dict) else [],
            })
    return found
