
from __future__ import annotations

import socket
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import structlog

from src.config.errors import StateDirUnavailableError
from src.core import product_identity

StateFilePin = Tuple[Path, str]

LOCATION_STATE_DIR = "state_dir"
LOCATION_LEGACY_STATE_DIR = "legacy_state_dir"
LOCATION_LOG_DIRECTORY = "log_directory"

_state_dir_legacy_note: Optional[str] = None

_legacy_migration_outcomes: Dict[Path, Path] = {}


def state_dir_legacy_note() -> Optional[str]:
    return _state_dir_legacy_note


def allowed_origins(
    override: Optional[str], host: Optional[str], port: int
) -> List[str]:
    if override:
        parts = [p.strip() for p in override.split(",")]
        return [p for p in parts if p]

    origins: List[str] = []

    try:
        hostname = socket.gethostname()
    except OSError:
        hostname = ""
    hostname_bare = hostname[:-6] if hostname.endswith(".local") else hostname

    if host and host != "0.0.0.0":
        origins.append(f"http://{host}:{port}")

    origins.append(f"http://localhost:{port}")
    origins.append(f"http://127.0.0.1:{port}")

    if hostname_bare:
        origins.append(f"http://{hostname_bare}:{port}")
        origins.append(f"http://{hostname_bare}.local:{port}")

    seen = set()
    deduped: List[str] = []
    for o in origins:
        if o not in seen:
            seen.add(o)
            deduped.append(o)
    return deduped


def working_dir(configured: str) -> Path:
    path = Path(configured).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path


def state_dir_is_explicit(override: Optional[str]) -> bool:
    return bool(override)


def state_dir(override: Optional[str]) -> Path:
    if state_dir_is_explicit(override):
        path = Path(override).expanduser()
    else:
        app_support = Path.home() / "Library" / "Application Support"
        path = app_support / product_identity.STATE_DIR_NAME
        if product_identity.LEGACY_STATE_DIR_NAMES and not path.exists():
            legacy_path = app_support / product_identity.LEGACY_STATE_DIR_NAMES[0]
            if legacy_path.exists():
                if path not in _legacy_migration_outcomes:
                    _legacy_migration_outcomes[path] = _migrate_legacy_state_dir_once(legacy_path, path)
                path = _legacy_migration_outcomes[path]
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise StateDirUnavailableError(path, exc) from exc
    return path


def _migrate_legacy_state_dir_once(legacy_path: Path, new_path: Path) -> Path:
    global _state_dir_legacy_note

    from src.core.db_models import TRAIL_STATUS_COMPLETED, TRAIL_STATUS_FAILED
    from src.core.migration_trail import MigrationTrail

    logger = structlog.get_logger()
    pre_trail = MigrationTrail(legacy_path)
    try:
        started = pre_trail.open_step(
            "state_dir",
            from_version=legacy_path.name,
            to_version=new_path.name,
            detail=f"renaming state directory {legacy_path} to {new_path}",
        )
    except OSError as exc:
        note = (
            f"using the legacy state directory {legacy_path} - could not "
            f"record the rename attempt in its upgrade trail: {exc}"
        )
        logger.warning(
            "state_dir_legacy_rename_trail_open_failed",
            legacy_path=str(legacy_path),
            new_path=str(new_path),
            error=str(exc),
        )
        _state_dir_legacy_note = note
        return legacy_path

    try:
        legacy_path.rename(new_path)
    except OSError as exc:
        note = (
            f"using the legacy state directory {legacy_path} - could not "
            f"rename it to {new_path}: {exc}"
        )
        logger.warning(
            "state_dir_legacy_rename_failed",
            legacy_path=str(legacy_path),
            new_path=str(new_path),
            error=str(exc),
        )
        try:
            pre_trail.close_step(started, TRAIL_STATUS_FAILED, error=str(exc))
        except OSError as trail_exc:
            logger.warning(
                "state_dir_legacy_rename_trail_close_failed",
                error=str(trail_exc),
            )
        _state_dir_legacy_note = note
        return legacy_path

    post_trail = MigrationTrail(new_path)
    try:
        post_trail.close_step(started, TRAIL_STATUS_COMPLETED)
    except OSError as exc:
        logger.warning(
            "state_dir_legacy_rename_trail_close_failed",
            new_path=str(new_path),
            error=str(exc),
        )
    _state_dir_legacy_note = None
    logger.info(
        "state_dir_legacy_renamed",
        legacy_path=str(legacy_path),
        new_path=str(new_path),
    )
    return new_path


def state_file_pin(
    filename: str,
    *,
    pins: Dict[tuple, StateFilePin],
    resolved_state_dir: Path,
    state_dir_override: Optional[str],
    log_directory: Optional[str],
    state_dir_explicit: bool,
) -> StateFilePin:
    state_key = state_dir_override or ""
    log_key = log_directory or ""
    key = (filename, state_key, log_key, state_dir_explicit)

    pinned = pins.get(key)
    if pinned is not None:
        return pinned

    new_path = resolved_state_dir / filename
    decision: StateFilePin = (new_path, LOCATION_STATE_DIR)

    if not state_dir_explicit and product_identity.LEGACY_STATE_DIR_NAMES:
        legacy_named_dir = (
            Path.home() / "Library" / "Application Support"
            / product_identity.LEGACY_STATE_DIR_NAMES[0]
        )
        if legacy_named_dir != resolved_state_dir:
            legacy_named_path = legacy_named_dir / filename
            current_exists = decision[0].exists()
            legacy_named_exists = legacy_named_path.exists()
            if current_exists and legacy_named_exists:
                structlog.get_logger().warning(
                    "state_file_present_in_both_locations",
                    filename=filename,
                    using=str(decision[0]),
                    old_path_retained=str(legacy_named_path),
                )
            elif legacy_named_exists:
                decision = (legacy_named_path, LOCATION_LEGACY_STATE_DIR)

    if log_key and not state_dir_explicit:
        old_path = Path(log_key).expanduser() / filename
        new_exists = decision[0].exists()
        old_exists = old_path.exists()
        if new_exists and old_exists:
            structlog.get_logger().warning(
                "state_file_present_in_both_locations",
                filename=filename,
                using=str(decision[0]),
                old_path_retained=str(old_path),
            )
        elif old_exists:
            decision = (old_path, LOCATION_LOG_DIRECTORY)
    elif log_key and state_dir_explicit:
        old_path = Path(log_key).expanduser() / filename
        if old_path.exists():
            structlog.get_logger().info(
                "state_file_legacy_copy_left_behind",
                filename=filename,
                using=str(new_path),
                legacy_path=str(old_path),
            )

    pins[key] = decision
    return decision
