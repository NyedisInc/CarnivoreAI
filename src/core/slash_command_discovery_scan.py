from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import structlog
import yaml

logger = structlog.get_logger()


_DESCRIPTION_LINE_RX = re.compile(r"^\*\*Description\*\*:\s*(.+)$", re.IGNORECASE)


_HEADING_LINE_RX = re.compile(r"^#{1,6}\s+(.+)$")


_FRONTMATTER_RX = re.compile(r"^---\s*\n(.*?\n)---\s*\n", re.DOTALL)


MAX_DESCRIPTION_LENGTH = 240


@dataclass
class DiscoveredCommand:
    command: str
    description: str
    type: str
    args: str = ""
    alias_of: Optional[str] = None
    source_path: str = ""


def read_skill_frontmatter(text: str) -> dict:
    match = _FRONTMATTER_RX.match(text)
    if not match:
        return {}
    try:
        data = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        logger.warning("slash_command_frontmatter_parse_failed", error=str(exc))
        return {}
    return data if isinstance(data, dict) else {}


def _read_frontmatter_description(text: str) -> Optional[str]:
    desc = read_skill_frontmatter(text).get("description")
    if isinstance(desc, str) and desc.strip():
        return desc.strip()
    return None


def _first_meaningful_line(text: str, skip_frontmatter: bool) -> Optional[str]:
    body = text
    if skip_frontmatter:
        match = _FRONTMATTER_RX.match(text)
        if match:
            body = text[match.end():]

    lines = [l.strip() for l in body.splitlines() if l.strip()]
    if not lines:
        return None

    for line in lines[:15]:
        m = _DESCRIPTION_LINE_RX.match(line)
        if m:
            return m.group(1).strip()[:MAX_DESCRIPTION_LENGTH]

    for line in lines[:5]:
        m = _HEADING_LINE_RX.match(line)
        if m:
            return m.group(1).strip()[:MAX_DESCRIPTION_LENGTH]

    return lines[0][:MAX_DESCRIPTION_LENGTH]


def describe_text(text: str, fallback: str) -> str:
    return (
        _read_frontmatter_description(text)
        or _first_meaningful_line(text, skip_frontmatter=True)
        or fallback
    )


def _describe_file(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        logger.warning("slash_command_file_unreadable", path=str(path), error=str(exc))
        return path.stem
    return describe_text(text, path.stem)


def _namespaced_name(rel_parts: tuple) -> str:
    return ":".join(rel_parts)


def _scan_command_files(root: Path, cmd_type: str) -> list[DiscoveredCommand]:
    if not root.is_dir():
        return []
    results = []
    for md_path in sorted(root.rglob("*.md")):
        if md_path.name.startswith("."):
            continue
        rel = md_path.relative_to(root).with_suffix("")
        name = _namespaced_name(rel.parts)
        results.append(DiscoveredCommand(
            command=f"/{name}",
            description=_describe_file(md_path),
            type=cmd_type,
            source_path=str(md_path),
        ))
    return results


def _scan_skill_dirs(root: Path, cmd_type: str) -> list[DiscoveredCommand]:
    if not root.is_dir():
        return []
    results = []
    for skill_md in sorted(root.rglob("SKILL.md")):
        rel_dir = skill_md.parent.relative_to(root)
        if any(part.startswith(".") for part in rel_dir.parts):
            continue
        name = _namespaced_name(rel_dir.parts)
        results.append(DiscoveredCommand(
            command=f"/{name}",
            description=_describe_file(skill_md),
            type=cmd_type,
            source_path=str(skill_md),
        ))
    return results


def discover_codex_user_scope(
    skills_root: Path | None = None,
) -> list[DiscoveredCommand]:
    if skills_root is None:
        raw = os.environ.get("CODEX_HOME")
        codex_home = (
            Path(raw).expanduser()
            if raw and raw.strip()
            else Path.home() / ".codex"
        )
        skills_root = codex_home / "skills"
    return _scan_skill_dirs(skills_root, "codex-skill")


def discover_project_scope(project_path: str) -> list[DiscoveredCommand]:
    if not project_path:
        return []
    root = Path(project_path)
    return (
        _scan_command_files(root / ".claude" / "commands", "project-command")
        + _scan_skill_dirs(root / ".claude" / "skills", "project-skill")
    )
