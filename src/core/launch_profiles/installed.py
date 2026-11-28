
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Callable, Optional

from src.core.agent_families import AGENT_FAMILY_BY_NAME
from src.core.sessions.agent_update import CLAUDE_INSTALL_CANDIDATES
from src.core.sessions.codex_update import CODEX_INSTALL_CANDIDATES

_TRANSPARENT = ("command", "exec")

_ALWAYS_INSTALLED = ("shell", "custom")

Locator = Callable[[str], Optional[str]]


def family_binary(harness: str) -> Optional[str]:
    spec = AGENT_FAMILY_BY_NAME.get(harness)
    if spec is None:
        return None
    for word in spec.default_script.split():
        if word not in _TRANSPARENT:
            return word.strip("\"'")
    return None


def _locate(name: str) -> Optional[str]:
    found = shutil.which(name)
    if found:
        return found
    candidates = (
        CLAUDE_INSTALL_CANDIDATES if name == "claude"
        else CODEX_INSTALL_CANDIDATES if name == "codex"
        else ()
    )
    for candidate in candidates:
        path = Path(candidate).expanduser()
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    return None


def harness_installed(harness: str, locate: Locator = _locate) -> bool:
    if harness in _ALWAYS_INSTALLED:
        return True
    binary = family_binary(harness)
    return binary is not None and locate(binary) is not None


def path_with_install_dirs(path: str) -> str:
    have = path.split(os.pathsep) if path else []
    for candidate in CLAUDE_INSTALL_CANDIDATES + CODEX_INSTALL_CANDIDATES:
        folder = Path(candidate).expanduser().parent
        if str(folder) not in have and folder.is_dir():
            have.append(str(folder))
    return os.pathsep.join(have)
