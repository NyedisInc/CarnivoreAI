
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional

import structlog

from src.core import config_writer
from src.plugins.host import registry_store

logger = structlog.get_logger()

TYPE_RENAMES = (("pack.alert", "swarm.alert"), ("pack.flash", "swarm.flash"), ("pack.question_climbed", "swarm.question_climbed"))


def _rename_key(block: Dict[str, Any], old: str, new: str) -> bool:
    if old not in block:
        return False
    value = block.pop(old)
    block.setdefault(new, value)
    return True


def _rename_routing_paths(doc: Dict[str, Any]) -> bool:
    changed = False
    for part in ("global", "local"):
        entries = doc.get(part)
        if not isinstance(entries, dict):
            continue
        for path in list(entries):
            for old, new in TYPE_RENAMES:
                if path.endswith("/" + old):
                    _rename_key(entries, path, path[: -len(old)] + new)
                    changed = True
    return changed


def _mutate_config(doc: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    changed = False
    block = doc.get("pack")
    if isinstance(block, dict):
        if "flash_per_pack_per_hour" in block:
            block["flash_per_swarm_per_hour"] = block.pop("flash_per_pack_per_hour")
        if "swarm" in doc:
            doc.pop("pack")
        else:
            doc["swarm"] = doc.pop("pack")
        changed = True
    if _rename_key(doc, "pack_node_order", "swarm_node_order"):
        changed = True
    profiles = (doc.get("launch_profiles") or {}).get("profiles") if isinstance(doc.get("launch_profiles"), dict) else None
    if isinstance(profiles, list):
        for profile in profiles:
            if isinstance(profile, dict) and profile.get("id") == "pack-upper":
                profile["id"] = "swarm-upper"
                changed = True
    routing = doc.get("notification_routing")
    if isinstance(routing, dict) and _rename_routing_paths(routing):
        changed = True
    return doc if changed else None


def _move_folder(state_dir: Path) -> bool:
    old, new = state_dir / "pack", state_dir / "swarm"
    if old.is_dir() and not new.exists():
        os.rename(old, new)
        return True
    return False


def _move_grant(state_dir: Path) -> bool:
    def rewrite(docs: registry_store.Documents) -> bool:
        cplugs = docs.load("state").get("cplugs")
        changed = False
        for entry in (cplugs or {}).values():
            grants = entry.get("grants") if isinstance(entry, dict) else None
            if isinstance(grants, list) and "pack" in grants:
                entry["grants"] = ["swarm" if g == "pack" else g for g in grants if g != "pack" or "swarm" not in grants]
                changed = True
        return changed

    if not registry_store.cplugs_dir(state_dir).is_dir():
        return False
    try:
        return registry_store.commit(state_dir, rewrite, log_event="swarm_legacy_grant_write_failed")
    except OSError as exc:
        logger.error("swarm_legacy_grant_move_failed", state_dir=str(state_dir), error_type=type(exc).__name__, error=str(exc)[:200])
        return False


def migrate(config_path: Path, state_dir: Path) -> Dict[str, bool]:
    done = {"config": False, "folder": False, "grant": False}
    try:
        if config_path.exists():
            done["config"] = config_writer.commit(config_path, _mutate_config).wrote
    except Exception as exc:  # noqa: BLE001
        logger.error("swarm_legacy_config_migration_failed", error=f"{type(exc).__name__}: {exc}")
    for key, step in (("folder", _move_folder), ("grant", _move_grant)):
        try:
            done[key] = step(state_dir)
        except (OSError, ValueError) as exc:
            logger.error("swarm_legacy_migration_failed", part=key, error=f"{type(exc).__name__}: {exc}")
    if any(done.values()):
        logger.info("swarm_legacy_pack_migrated", **done)
    return done
