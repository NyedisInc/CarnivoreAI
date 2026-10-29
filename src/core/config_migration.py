
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import structlog

from src.core import config_writer
from src.core.config_migration_steps import (
    _step_v0_to_v1,
    _step_v1_to_v2,
    _step_v2_to_v3,
    _step_v3_to_v4,
    _step_v4_to_v5,
    build_seed_wrappers,
    probe_shell_function,
)
from src.core.launch_profiles.fold_local_host import fold_local_host
from src.core.launch_profiles.seed_from_wrappers import seed_launch_profiles
from src.core.launch_wrappers.legacy_fold import fold_legacy_commands

logger = structlog.get_logger()

CURRENT_CONFIG_VERSION = 8

def migrate_config_dict(
    data: Dict, has_cld: bool, has_cldor: bool
) -> Tuple[Dict, bool]:
    """Pure migration: run every version step the config still needs.

    Description: fail-safe by construction - a step that can't confidently
      proceed makes this return ``(data, False)`` with the input
      completely untouched (no partial mutation, no config_version
      stamped), never raises. Steps run in order and only for versions the
      config hasn't reached, so a v0 config runs 0->1, 1->2, 2->3 then
      3->4, a v3 config runs only 3->4, and a v4 config does nothing at
      all.
    Inputs:
      data (dict) - the parsed config.json.
      has_cld (bool) / has_cldor (bool) - environment probe results (see
        ``probe_shell_function``); pass explicitly so this function stays
        pure/deterministic and trivially testable without shelling out.
    Output: (dict, bool) - (possibly-new dict, whether anything changed).
      The returned dict is always a NEW object when changed=True (the
      input ``data`` is never mutated in place), so a caller holding a
      reference to the original can still inspect the pre-migration
      state.
    Raises: never - logs a warning and returns (data, False) instead.
    Example: migrate_config_dict({"agents": {}}, True, False) ->
      ({..., "agents": {..., "wrappers": [claude, keyc]},
        "config_version": 4}, True)
    """
    try:
        existing_version = data.get("config_version", 0)
        if not isinstance(existing_version, int):
            logger.warning(
                "config_migration_skipped_bad_version_type",
                raw=existing_version,
            )
            return data, False

        if existing_version >= CURRENT_CONFIG_VERSION:
            return data, False

        working = data
        if existing_version < 1:
            stepped = _step_v0_to_v1(working, has_cld, has_cldor)
            if stepped is None:
                return data, False
            working = stepped
        if existing_version < 2:
            working = _step_v1_to_v2(working)
        if existing_version < 3:
            working = _step_v2_to_v3(working)
        if existing_version < 4:
            working = _step_v3_to_v4(working)
        if existing_version < 5:
            working = _step_v4_to_v5(working)
        if existing_version < 6:
            working = fold_legacy_commands(working)
        if existing_version < 7:
            working = seed_launch_profiles(working)
        if existing_version < 8:
            working = fold_local_host(working)

        new_data = dict(working)
        new_data["config_version"] = CURRENT_CONFIG_VERSION
        logger.info(
            "config_migration_version_advanced",
            from_version=existing_version,
            to_version=CURRENT_CONFIG_VERSION,
        )
        return new_data, True

    except Exception as e:
        logger.warning("config_migration_unexpected_error", error=str(e))
        return data, False


def migrate_config_file(config_path: Path) -> Dict:
    if not config_path.exists():
        raise FileNotFoundError(f"config.json not found: {config_path}")

    migrated: Dict = {}

    def migrate(data: Dict) -> Optional[Dict]:
        version = data.get("config_version", 0) if isinstance(data, dict) else None
        needs_probe = isinstance(version, int) and version < 1
        has_cld = probe_shell_function("keyc") if needs_probe else False
        has_cldor = probe_shell_function("clxor") if needs_probe else False
        new_data, changed = migrate_config_dict(data, has_cld, has_cldor)
        if not changed:
            return None
        migrated.clear()
        migrated.update(new_data)
        return new_data

    outcome = config_writer.commit(config_path, migrate, backup_required=True)

    if not outcome.wrote:
        if outcome.status == config_writer.BACKUP_UNAVAILABLE:
            logger.warning("config_migration_backup_failed", path=str(config_path))
        return {"migrated": False, "changed": False, "wrapper_ids": []}

    wrapper_ids = [
        w["id"] for w in (migrated.get("agents", {}) or {}).get("wrappers", []) or []
    ]
    logger.info("config_migration_applied", wrapper_ids=wrapper_ids)
    return {"migrated": True, "changed": True, "wrapper_ids": wrapper_ids}


def ensure_config_migrated(config_path: Path) -> None:
    try:
        result = migrate_config_file(config_path)
        if result["changed"]:
            logger.info(
                "config_migration_startup_applied",
                wrapper_ids=result["wrapper_ids"],
            )
    except FileNotFoundError:
        pass
    except Exception as e:
        logger.warning("config_migration_startup_failed", error=str(e))
