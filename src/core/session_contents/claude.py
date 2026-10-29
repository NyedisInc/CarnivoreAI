
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from src.core.session_contents import constants as C
from src.core.session_contents import claude_files as F
from src.core.session_contents.entries import (Item, drop_seen, folder_chain, from_found, item, read_json, section, top_level_keys)
from src.core.session_contents.mcp import server_items
from src.core.slash_command_discovery_scan import _scan_command_files, _scan_skill_dirs


def default_config_dir() -> Path:
    return Path.home() / ".claude"


def _state_file(config_dir: Path) -> Path:
    if F.same_dir(config_dir, default_config_dir()):
        return Path.home() / C.CLAUDE_JSON
    return config_dir / C.CLAUDE_JSON


def _scan(kind_dir: str, config_dir: Path, claude_dirs: List[Path], plugins: List[tuple], skills: bool) -> List[Item]:
    scan = _scan_skill_dirs if skills else _scan_command_files
    seen: set[str] = set()
    out = drop_seen(from_found(scan(config_dir / kind_dir, "x"), C.SCOPE_GLOBAL), seen)
    for folder in claude_dirs:
        out += drop_seen(from_found(scan(folder / kind_dir, "x"), C.SCOPE_PROJECT), seen)
    for name, root, enabled in plugins:
        out += drop_seen(from_found(scan(root / kind_dir, "x"), C.SCOPE_PLUGIN,
                                    f"plugin {name}" + ("" if enabled else " (disabled)")), seen)
    return out


def _mcp_items(config_dir: Path, working_dir: Optional[str], chain: List[Path], plugins: List[tuple]) -> List[Item]:
    state_path = _state_file(config_dir)
    state = read_json(state_path)
    out = server_items(state.get("mcpServers"), C.SCOPE_GLOBAL, state_path)
    projects = state.get("projects")
    entry = projects.get(working_dir) if isinstance(projects, dict) and working_dir else None
    if isinstance(entry, dict):
        out += server_items(entry.get("mcpServers"), C.SCOPE_PROJECT, state_path, "local")
    for folder in chain:
        doc = read_json(folder / C.PROJECT_MCP_FILE)
        out += server_items(doc.get("mcpServers"), C.SCOPE_PROJECT, folder / C.PROJECT_MCP_FILE)
    for name, root, enabled in plugins:
        doc = read_json(root / C.PROJECT_MCP_FILE)
        out += server_items(doc.get("mcpServers", doc), C.SCOPE_PLUGIN, root / C.PROJECT_MCP_FILE,
                            f"plugin {name}" + ("" if enabled else ", disabled"))
    return out


def gather(config_dir: Optional[str], working_dir: Optional[str]) -> List[Dict[str, Any]]:
    home = Path(config_dir).expanduser() if config_dir else default_config_dir()
    chain = folder_chain(working_dir)
    claude_dirs = F.project_claude_dirs(chain, home)
    layers = F.settings_layers(home, claude_dirs)
    enabled = F.enabled_plugins(layers)
    installed = F.installed_plugins(home)
    plugins = [(F.plugin_label(key), root, enabled.get(key, False)) for key, root, _ in installed]
    settings = [item(path.name, scope, path, detail=top_level_keys(doc)) for path, scope, doc in layers]
    plugin_items = [item(F.plugin_label(key), C.SCOPE_PLUGIN, root, detail=_plugin_detail(version, enabled.get(key, False)))
                    for key, root, version in installed]
    built = {
        C.KIND_INSTRUCTIONS: F.instruction_items(home, chain),
        C.KIND_SKILLS: _scan("skills", home, claude_dirs, plugins, True),
        C.KIND_AGENTS: _scan("agents", home, claude_dirs, plugins, False),
        C.KIND_COMMANDS: _scan("commands", home, claude_dirs, plugins, False),
        C.KIND_HOOKS: F.hook_items(layers, plugins),
        C.KIND_OUTPUT_STYLES: _scan("output-styles", home, claude_dirs, plugins, False),
        C.KIND_SETTINGS: settings,
        C.KIND_MCP: _mcp_items(home, working_dir, chain, plugins),
        C.KIND_PLUGINS: plugin_items,
    }
    return [section(kind, built[kind]) for kind in C.SECTIONS_BY_FAMILY[C.FAMILY_CLAUDE]]


def _plugin_detail(version: str, enabled: bool) -> str:
    return " ".join(p for p in (f"v{version}" if version else "", "enabled" if enabled else "not enabled") if p)
