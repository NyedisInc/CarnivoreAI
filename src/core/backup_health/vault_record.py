
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

import structlog

from src.core.attention.registry_file_cache import RegistryFileCache

logger = structlog.get_logger()

HEALTH_FILE: str = "vault-health.json"
DEFAULT_DIR_NAME: str = "vault"
MANIFESTS_DIR: str = "manifests"
SAVE_PLUGIN_ID: str = "save"
LOCATION_SETTING: str = "vaultLocation"
OPT_OUT_SETTING: str = "vaultFolderOptOut"
LOCATION_CONFIG_BLOCK: str = "save_pipeline"
LOCATION_CONFIG_FIELD: str = "vault_location"
STALE_HOURS: float = 6.0
COVERAGE_GRACE_HOURS: float = 2.0


def location_of(config: Dict[str, Any]) -> str:
    block = config.get(LOCATION_CONFIG_BLOCK)
    value = block.get(LOCATION_CONFIG_FIELD) if isinstance(block, dict) else None
    return value.strip() if isinstance(value, str) else ""


def opt_out_units(value: Any) -> frozenset:
    if not isinstance(value, str):
        return frozenset()
    return frozenset(part for part in value.replace(",", " ").split() if part)


def opt_out_text(units: Any) -> str:
    return ",".join(sorted(set(units)))


def location_value(config: Dict[str, Any], save_settings: Optional[Mapping[str, Any]]) -> str:
    if save_settings is not None and LOCATION_SETTING in save_settings:
        value = save_settings[LOCATION_SETTING]
        return value.strip() if isinstance(value, str) else ""
    return location_of(config)


def root_for(state_dir: Path, config: Dict[str, Any], save_settings: Optional[Mapping[str, Any]] = None) -> Path:
    from src.cplugs.host.data_roots import setting_root  # noqa: PLC0415

    return setting_root(state_dir, location_value(config, save_settings), DEFAULT_DIR_NAME) or Path(state_dir) / DEFAULT_DIR_NAME


def _load_config(path: str, _name: str) -> Optional[Dict[str, Any]]:
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        logger.warning("vault_location_config_unreadable", path=path, error_type=type(exc).__name__)
        return None
    return data if isinstance(data, dict) else None


_CONFIG_CACHE = RegistryFileCache()


def read_config(config_path: Path) -> Dict[str, Any]:
    path = str(Path(config_path))
    config = _CONFIG_CACHE.load(path, path, _load_config, keep=lambda parsed: parsed is not None)
    return config if config is not None else {}


def configured_location(state_dir: Path, config_path: Path) -> str:
    from src.cplugs.host.data_roots import stored_settings  # noqa: PLC0415

    return location_value(read_config(config_path), stored_settings(state_dir, SAVE_PLUGIN_ID))


def resolve_root(state_dir: Path, config_path: Path) -> Path:
    from src.cplugs.host.data_roots import setting_root  # noqa: PLC0415

    return setting_root(state_dir, configured_location(state_dir, config_path), DEFAULT_DIR_NAME) or Path(state_dir) / DEFAULT_DIR_NAME


def health_path(state_dir: Path) -> Path:
    return Path(state_dir) / HEALTH_FILE


def read(state_dir: Path) -> Dict[str, Any]:
    try:
        data = json.loads(health_path(state_dir).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        logger.warning("vault_health_unreadable", error=str(exc))
        return {}
    return data if isinstance(data, dict) else {}


def update(state_dir: Path, **fields: Any) -> Dict[str, Any]:
    from src.core.json_artifact import atomic_write_json

    merged = {**read(state_dir), **fields}
    atomic_write_json(health_path(state_dir), merged, log_event="vault_health_write_failed")
    return merged


def evaluate(record: Dict[str, Any], *, now: Optional[float] = None, stale_hours: float = STALE_HOURS,
             grace_hours: float = COVERAGE_GRACE_HOURS) -> Dict[str, Any]:
    stamp = time.time() if now is None else now
    since = record.get("last_ok_at") or record.get("started_at")
    age_h = (stamp - since) / 3600.0 if isinstance(since, (int, float)) else None
    known = record.get("swept_at") is not None
    uncovered = record.get("uncovered") if known else None
    first = record.get("uncovered_since")
    overdue = uncovered if (uncovered and isinstance(first, (int, float)) and stamp - first > grace_hours * 3600.0) else None
    return {
        "known": known,
        "active": bool(record.get("active", True)) if record else False,
        "uncovered": uncovered,
        "on_disk": record.get("on_disk") if known else None,
        "uncovered_overdue": overdue,
        "stale_hours": int(age_h) if age_h is not None and age_h > stale_hours else None,
        "unavailable": record.get("unavailable") or None,
        "over_cap": bool(record.get("over_cap")),
        "damaged": int(record.get("damaged") or 0),
        "pending": int(record.get("pending") or 0),
        "legacy_unmigrated": int(record.get("legacy_unmigrated") or 0),
        "folders": [row for row in record.get("folders") or [] if isinstance(row, dict)],
    }
