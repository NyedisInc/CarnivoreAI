
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Optional

import structlog

from src.core.claude_folder_trust import claude_json_path

logger = structlog.get_logger()

_QUESTION = re.compile(r"New MCP server found in this project:\s*(\S+)")


def server_name(question: str) -> Optional[str]:
    found = _QUESTION.fullmatch(" ".join(str(question).split()))
    return found.group(1) if found else None


def _read(path: Path) -> Optional[Dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            document = json.load(fh)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        logger.info("auto_answer_mcp_unreadable", path=path.name, error=type(exc).__name__)
        return None
    return document if isinstance(document, dict) else None


def installed_for(folder: str, name: str, *, claude_json: Optional[Path] = None) -> bool:
    own = _read(claude_json or claude_json_path())
    project = _read(Path(folder) / ".mcp.json")
    if own is None or project is None:
        return False
    wanted = (project.get("mcpServers") or {}).get(name) if isinstance(project.get("mcpServers"), dict) else None
    if not isinstance(wanted, dict):
        return False
    scopes = [own.get("mcpServers")]
    projects = own.get("projects")
    if isinstance(projects, dict):
        for spelling in {folder, os.path.realpath(folder)}:
            entry = projects.get(spelling)
            scopes.append(entry.get("mcpServers") if isinstance(entry, dict) else None)
    return any(isinstance(scope, dict) and scope.get(name) == wanted for scope in scopes)
