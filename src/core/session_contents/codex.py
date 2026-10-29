
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.core.session_contents import constants as C
from src.core.session_contents.entries import (Item, folder_chain, from_found, item, read_toml, section, top_level_keys)
from src.core.session_contents.mcp import server_items
from src.core.slash_command_discovery_scan import _scan_command_files, _scan_skill_dirs, discover_codex_user_scope

AGENTS_NAMES = ("AGENTS.override.md", "AGENTS.md")
CONFIG_NAME = "config.toml"


def codex_home(profile_dir: Optional[str]) -> Path:
    raw = profile_dir or os.environ.get("CODEX_HOME")
    return Path(raw).expanduser() if raw and raw.strip() else Path.home() / ".codex"


def _instructions(home: Path, chain: List[Path]) -> List[Item]:
    paths = [(home / n, C.SCOPE_GLOBAL) for n in AGENTS_NAMES]
    for folder in chain:
        paths += [(folder / n, C.SCOPE_PROJECT) for n in AGENTS_NAMES]
    out: List[Item] = []
    for path, scope in paths:
        if path.is_file():
            out.append(item(path.name, scope, path))
    return out


def _profiles(doc: Dict[str, Any], path: Path) -> List[Item]:
    table = doc.get("profiles")
    if not isinstance(table, dict):
        return []
    out: List[Item] = []
    for name, entry in table.items():
        model = entry.get("model") if isinstance(entry, dict) else None
        out.append(item(str(name), C.SCOPE_GLOBAL, path, detail=model if isinstance(model, str) else ""))
    return out


def gather(profile_dir: Optional[str], working_dir: Optional[str]) -> List[Dict[str, Any]]:
    home = codex_home(profile_dir)
    chain = folder_chain(working_dir, stop_at_git=True)
    config_path = home / CONFIG_NAME
    config = read_toml(config_path)
    project_configs = [(f / ".codex" / CONFIG_NAME, read_toml(f / ".codex" / CONFIG_NAME)) for f in chain
                       if (f / ".codex" / CONFIG_NAME).is_file()]
    skills = from_found(discover_codex_user_scope(home / "skills"), C.SCOPE_GLOBAL)
    agents_skills = Path.home() / ".agents" / "skills"
    skills += from_found(_scan_skill_dirs(agents_skills, "x"), C.SCOPE_GLOBAL)
    for folder in chain:
        skills += from_found(_scan_skill_dirs(folder / ".agents" / "skills", "x"), C.SCOPE_PROJECT)
    settings = [item(config_path.name, C.SCOPE_GLOBAL, config_path, detail=top_level_keys(config))] if config_path.is_file() else []
    mcp = server_items(config.get("mcp_servers"), C.SCOPE_GLOBAL, config_path)
    for path, doc in project_configs:
        settings.append(item(f".codex/{path.name}", C.SCOPE_PROJECT, path, detail=top_level_keys(doc)))
        mcp += server_items(doc.get("mcp_servers"), C.SCOPE_PROJECT, path)
    built = {
        C.KIND_INSTRUCTIONS: _instructions(home, chain),
        C.KIND_SKILLS: skills,
        C.KIND_PROMPTS: from_found(_scan_command_files(home / "prompts", "x"), C.SCOPE_GLOBAL),
        C.KIND_SETTINGS: settings,
        C.KIND_PROFILES: _profiles(config, config_path),
        C.KIND_MCP: mcp,
    }
    return [section(kind, built[kind]) for kind in C.SECTIONS_BY_FAMILY[C.FAMILY_CODEX]]
