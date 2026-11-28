
from __future__ import annotations

import json
import os
import shlex
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import structlog

from src.config import mcp_launch
from src.core.agy.state import state_folder
from src.core.safe_file_write import SafeFileWriteError, UnsafeFileTargetError, write_private_file

logger = structlog.get_logger()

SCRIPT_NAME = "agy_statusline.py"
AGY_HOME = Path.home() / ".gemini" / "antigravity-cli"
PLUGIN_NAME = "carnivore-agy"
PLUGIN_SOURCE = Path(__file__).with_name("plugin")
PLUGIN_FILES = ("plugin.json", "hooks.json", "carnivore_launch_line_hook.py", "carnivore_precheck_hook.py", "rules/carnivore.md")
DEFAULT_VERBOSITY = "medium"


def statusline_command(state_dir: Path, python: str = sys.executable) -> str:
    script = Path(state_dir) / "bin" / SCRIPT_NAME
    return "%s -I -S %s %s \"$PPID\"" % (shlex.quote(python), shlex.quote(str(script)), shlex.quote(str(state_folder(state_dir))))


def merged_settings(current: Dict[str, Any], command: str) -> Optional[Dict[str, Any]]:
    existing = current.get("statusLine")
    if isinstance(existing, dict) and existing.get("command") and SCRIPT_NAME not in str(existing["command"]):
        return None
    wanted = {"type": "command", "command": command, "padding": 0}
    if isinstance(existing, dict) and all(existing.get(k) == v for k, v in wanted.items()):
        return None
    return dict(current, statusLine=dict(existing or {}, **wanted))


def with_verbosity(current: Dict[str, Any]) -> Dict[str, Any]:
    return current if "verbosity" in current else dict(current, verbosity=DEFAULT_VERBOSITY)


def _other_carnivore_server(plugins_dir: Path, config_dir: Path) -> bool:
    candidates = [config_dir / "mcp_config.json"]
    if plugins_dir.is_dir():
        candidates += [d / "mcp_config.json" for d in sorted(plugins_dir.iterdir()) if d.is_dir() and d.name != PLUGIN_NAME]
    for path in candidates:
        try:
            servers = json.loads(path.read_text(encoding="utf-8")).get("mcpServers")
        except (OSError, ValueError, AttributeError):
            continue
        if isinstance(servers, dict) and mcp_launch.SERVER_NAME in servers:
            return True
    return False


def install_plugin(config_dir: Path, source: Path = PLUGIN_SOURCE) -> str:
    plugins_dir = config_dir / "plugins"
    dest = plugins_dir / PLUGIN_NAME
    try:
        if not config_dir.is_dir():
            return "no_agy"
        if dest.is_symlink():
            return "foreign"
        if dest.is_dir():
            try:
                owned = json.loads((dest / "plugin.json").read_text(encoding="utf-8")).get("name") == PLUGIN_NAME
            except (OSError, ValueError, AttributeError):
                owned = False
            if not owned:
                logger.warning("agy_plugin_folder_not_ours")
                return "foreign"
        wanted = {name: (source / name).read_bytes() for name in PLUGIN_FILES}
        doc = None if _other_carnivore_server(plugins_dir, config_dir) else mcp_launch.agy_server_doc()
        if doc is not None:
            wanted["mcp_config.json"] = (json.dumps({"mcpServers": {mcp_launch.SERVER_NAME: doc}}, indent=2) + "\n").encode("utf-8")
        changed = False
        for name, data in wanted.items():
            target = dest / name
            if target.is_file() and not target.is_symlink() and target.read_bytes() == data:
                continue
            write_private_file(target.parent, target.name, data, 0o644)
            changed = True
        stale = dest / "mcp_config.json"
        if "mcp_config.json" not in wanted and stale.is_file() and not stale.is_symlink():
            stale.unlink()
            changed = True
    except (OSError, SafeFileWriteError, UnsafeFileTargetError) as exc:
        logger.warning("agy_plugin_install_failed", error=type(exc).__name__)
        return "failed"
    return "installed" if changed else "unchanged"


def install(state_dir: Path, agy_home: Path = AGY_HOME, config_dir: Optional[Path] = None) -> str:
    if not agy_home.is_dir():
        return "no_agy"
    source = Path(__file__).with_name("statusline_bridge.py")
    try:
        write_private_file(Path(state_dir) / "bin", SCRIPT_NAME, source.read_bytes(), 0o600)
        path = agy_home / "settings.json"
        try:
            current = json.loads(path.read_text(encoding="utf-8") or "{}")
        except FileNotFoundError:
            current = {}
        if not isinstance(current, dict):
            logger.warning("agy_statusline_settings_not_object")
            return "failed"
        merged = merged_settings(current, statusline_command(state_dir))
        owner = merged is None and isinstance(current.get("statusLine"), dict) and SCRIPT_NAME not in str(current["statusLine"].get("command"))
        outcome = "installed" if merged is not None else ("owner_command" if owner else "unchanged")
        merged = with_verbosity(current if merged is None else merged)
        if merged == current:
            install_plugin(config_dir or agy_home.parent / "config")
            return outcome
        mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
        write_private_file(agy_home, "settings.json", (json.dumps(merged, indent=2) + "\n").encode("utf-8"), mode)
    except (OSError, ValueError, SafeFileWriteError, UnsafeFileTargetError) as exc:
        logger.warning("agy_statusline_install_failed", error=type(exc).__name__)
        return "failed"
    logger.info("agy_statusline_installed")
    install_plugin(config_dir or agy_home.parent / "config")
    return outcome if outcome != "unchanged" else "installed"
