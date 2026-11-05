
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import structlog

from src.core import slash_command_discovery
from src.core.live_install_roots import MODS_DIR_NAME
from src.core.mods.inventory import declares_modules
from src.core.catalog.publish_prepare_kinds import KIND_MOD, KIND_PLUGIN, PLUGIN_MANIFEST, is_mod_folder

logger = structlog.get_logger()

_MARKETPLACE_MANIFEST = ".claude-plugin/marketplace.json"


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        logger.warning("publish_plugin_source_unreadable", path=str(path), error=str(exc))
        return None


def _plugin_folders(root: Path) -> List[Path]:
    found: List[Path] = []
    if (root / PLUGIN_MANIFEST).is_file():
        found.append(root)
    manifest = _read_json(root / _MARKETPLACE_MANIFEST)
    entries = manifest.get("plugins") if isinstance(manifest, dict) else None
    for entry in entries if isinstance(entries, list) else []:
        source = entry.get("source") if isinstance(entry, dict) else None
        if not isinstance(source, str) or not source.startswith("./"):
            continue
        folder = root / source
        try:
            inside = folder.resolve().is_relative_to(root.resolve())
        except OSError:
            continue
        if inside and folder.is_dir() and not folder.is_symlink() and (folder / PLUGIN_MANIFEST).is_file():
            found.append(folder)
    return found


def _location(folder: Path, kind: str) -> Dict[str, Any]:
    return {
        "location_id": f"{kind}:{folder.name}", "kind": kind, "name": folder.name,
        "harness": "", "scope": "personal", "path": str(folder), "description": "",
        "description_tokens_est": 0, "is_symlink": False, "read_only": False,
        "plugin": None, "managed": None,
    }


def _local_mod_folders(installed_mod_names: set) -> List[Path]:
    root = slash_command_discovery.CLAUDE_HOME / MODS_DIR_NAME
    try:
        children = sorted(root.iterdir())
    except OSError:
        return []
    return [
        c for c in children
        if not c.name.startswith(".") and c.name not in installed_mod_names
        and c.is_dir() and not c.is_symlink() and declares_modules(str(c))
    ]


def own_plugin_locations(installed_names: set, installed_mod_names: set = frozenset()) -> List[Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    known = _read_json(slash_command_discovery.CLAUDE_HOME / "plugins" / "known_marketplaces.json")
    for entry in known.values() if isinstance(known, dict) else []:
        source = entry.get("source") if isinstance(entry, dict) else None
        raw = source.get("path") if isinstance(source, dict) and source.get("source") == "directory" else None
        root = Path(raw) if isinstance(raw, str) and raw else None
        if root is None or not root.is_dir():
            continue
        for folder in _plugin_folders(root):
            if folder.name.startswith(".") or folder.name in installed_names or folder.name in out:
                continue
            out[folder.name] = _location(folder, KIND_MOD if is_mod_folder(folder) else KIND_PLUGIN)
    for folder in _local_mod_folders(installed_mod_names):
        out.setdefault(folder.name, _location(folder, KIND_MOD))
    return sorted(out.values(), key=lambda loc: loc["name"].lower())
