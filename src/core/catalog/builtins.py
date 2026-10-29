
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

from src.cplugs.registry import MANIFEST_FILE, PLUGINS_ROOT, plugin_folders
from src.core.skills.bundled_install import BundledSkillError, bundled_digest, bundled_version
from src.core.skills.required import REQUIRED_SKILLS
from src.models.catalog_builtins import BuiltinEntry

logger = structlog.get_logger()

THEMES_ROOT = Path(__file__).resolve().parents[3] / "client" / "css" / "themes"
FIRST_PARTY_PUBLISHER = "nyedis"
SIDECAR_FILE = "carnivore.json"


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("builtins_manifest_unreadable", path=str(path), error=type(exc).__name__)
        return None
    return doc if isinstance(doc, dict) else None


def plugin_entries(root: Path) -> List[BuiltinEntry]:
    out: List[BuiltinEntry] = []
    for folder in plugin_folders(root):
        manifest = _read_json(root / folder / MANIFEST_FILE)
        if manifest is None or not manifest.get("version"):
            continue
        sidecar = _read_json(root / folder / SIDECAR_FILE) if (root / folder / SIDECAR_FILE).is_file() else None
        name = (sidecar or {}).get("name") or manifest.get("name") or folder
        out.append(BuiltinEntry(id=f"{FIRST_PARTY_PUBLISHER}/{folder}", kind="cplug", name=str(name), version=str(manifest["version"]),
                                since_app_version=manifest.get("min_app_version")))
    return sorted(out, key=lambda e: e.id)


def theme_entries(root: Path) -> List[BuiltinEntry]:
    out: List[BuiltinEntry] = []
    for manifest_path in sorted(root.glob("*/theme.json")):
        manifest = _read_json(manifest_path)
        if manifest is None or not manifest.get("version"):
            continue
        folder = manifest_path.parent.name
        out.append(BuiltinEntry(id=f"{FIRST_PARTY_PUBLISHER}/{folder}", kind="theme", name=str(manifest.get("name") or folder),
                                version=str(manifest["version"])))
    return sorted(out, key=lambda e: e.id)


def skill_entries() -> List[BuiltinEntry]:
    out: List[BuiltinEntry] = []
    for skill in REQUIRED_SKILLS:
        try:
            version = bundled_version(bundled_digest(skill.folder))
        except BundledSkillError as exc:
            logger.warning("builtins_skill_missing", item_id=skill.item_id, code=exc.code)
            continue
        out.append(BuiltinEntry(id=skill.item_id, kind="skill", name=skill.folder, version=version))
    return sorted(out, key=lambda e: e.id)


def build_builtins() -> List[BuiltinEntry]:
    return plugin_entries(PLUGINS_ROOT) + theme_entries(THEMES_ROOT) + skill_entries()
