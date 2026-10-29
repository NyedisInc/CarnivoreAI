from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import structlog

from src.core.slash_command_discovery_scan import (
    MAX_DESCRIPTION_LENGTH,  # noqa: F401  re
    DiscoveredCommand,
    _scan_command_files,
    _scan_skill_dirs,
    discover_codex_user_scope,
    discover_project_scope,
)

logger = structlog.get_logger()

CLAUDE_HOME = Path.home() / ".claude"
SCRAPED_COMMANDS_PATH = Path(__file__).resolve().parent.parent / "data" / "slash-commands.json"






@dataclass
class CommandGroup:
    id: str
    label: str
    commands: list = field(default_factory=list)














def discover_user_scope(root: Path | None = None) -> list[DiscoveredCommand]:
    home = root if root is not None else CLAUDE_HOME
    return (
        _scan_command_files(home / "commands", "user-command")
        + _scan_skill_dirs(home / "skills", "user-skill")
    )






def _plugin_display_name(plugin_root: Path) -> str:
    return plugin_root.parent.name


def discover_plugin_scope(root: Path | None = None) -> dict[str, list[DiscoveredCommand]]:
    cache_root = (root if root is not None else CLAUDE_HOME) / "plugins" / "cache"
    if not cache_root.is_dir():
        return {}

    by_plugin: dict[str, list[DiscoveredCommand]] = {}
    for marketplace_dir in sorted(p for p in cache_root.iterdir() if p.is_dir()):
        for plugin_dir in sorted(p for p in marketplace_dir.iterdir() if p.is_dir()):
            for version_dir in sorted(p for p in plugin_dir.iterdir() if p.is_dir()):
                plugin_name = _plugin_display_name(version_dir)
                found = (
                    _scan_command_files(version_dir / "commands", "plugin-command")
                    + _scan_skill_dirs(version_dir / "skills", "plugin-skill")
                )
                if found:
                    by_plugin.setdefault(plugin_name, []).extend(found)
    return by_plugin


def _load_scraped_commands() -> list[dict]:
    try:
        data = json.loads(SCRAPED_COMMANDS_PATH.read_text(encoding="utf-8"))
        return data.get("commands", [])
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("scraped_slash_commands_load_failed", path=str(SCRAPED_COMMANDS_PATH), error=str(exc))
        return []


def _group_user_scope(discovered: list[DiscoveredCommand]) -> list[CommandGroup]:
    root_commands = []
    by_namespace: dict[str, list] = {}
    for cmd in discovered:
        body = cmd.command.lstrip("/")
        if ":" in body:
            namespace = body.split(":", 1)[0]
            by_namespace.setdefault(namespace, []).append(cmd)
        else:
            root_commands.append(cmd)

    groups = []
    if root_commands:
        groups.append(CommandGroup(id="user", label="your commands", commands=root_commands))
    for namespace in sorted(by_namespace):
        groups.append(CommandGroup(
            id=f"user:{namespace}",
            label=f"your commands ({namespace})",
            commands=by_namespace[namespace],
        ))
    return groups


def build_command_groups(
    project_path: Optional[str] = None,
    *,
    claude_home: Optional[Path] = None,
    codex_skills_root: Optional[Path] = None,
) -> list[CommandGroup]:
    groups: list[CommandGroup] = []

    scraped = _load_scraped_commands()
    builtin = [c for c in scraped if c.get("type") == "builtin"]
    skill = [c for c in scraped if c.get("type") == "skill"]
    workflow = [c for c in scraped if c.get("type") == "workflow"]
    if builtin:
        groups.append(CommandGroup(id="builtin", label="built-in commands", commands=builtin))
    if skill:
        groups.append(CommandGroup(id="skill", label="bundled skills", commands=skill))
    if workflow:
        groups.append(CommandGroup(id="workflow", label="bundled workflows", commands=workflow))

    groups.extend(_group_user_scope(discover_user_scope(claude_home)))

    codex_skills = discover_codex_user_scope(codex_skills_root)
    if codex_skills:
        groups.append(CommandGroup(
            id="codex",
            label="codex skills",
            commands=codex_skills,
        ))

    for plugin_name, commands in sorted(discover_plugin_scope(claude_home).items()):
        groups.append(CommandGroup(
            id=f"plugin:{plugin_name}",
            label=f"{plugin_name} (plugin)",
            commands=commands,
        ))

    if project_path:
        project_commands = discover_project_scope(project_path)
        if project_commands:
            groups.append(CommandGroup(id="project", label="project commands", commands=project_commands))

    return groups


def command_groups_to_dict(groups: list[CommandGroup]) -> list[dict]:
    def _cmd_to_dict(c) -> dict:
        if isinstance(c, DiscoveredCommand):
            return {
                "command": c.command,
                "args": c.args,
                "description": c.description,
                "type": c.type,
                "alias_of": c.alias_of,
            }
        return {
            "command": c.get("command", ""),
            "args": c.get("args", ""),
            "description": c.get("description", ""),
            "type": c.get("type", "builtin"),
            "alias_of": c.get("alias_of"),
        }

    return [
        {"id": g.id, "label": g.label, "commands": [_cmd_to_dict(c) for c in g.commands]}
        for g in groups
    ]
