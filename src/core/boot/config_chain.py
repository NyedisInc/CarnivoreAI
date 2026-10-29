
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from src.api import version_routes
from src.config import settings
from src.core.boot.steps import BootStep
from src.core.version import resolve_version

if TYPE_CHECKING:
    from src.core.boot.context import BootContext

logger = structlog.get_logger()


def read_config_version(config_path: Path) -> object:
    from src.core.db_state import CANNOT_DETERMINE

    try:
        with open(config_path) as handle:
            raw = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return CANNOT_DETERMINE
    value = raw.get("config_version") if isinstance(raw, dict) else None
    return value if isinstance(value, int) else CANNOT_DETERMINE


def _install_old_name_counter(_ctx: "BootContext") -> None:
    from src.core.mcp_usage import old_names as _old_name_counter

    _old_name_counter.install()


def _migrate_config(_ctx: "BootContext") -> None:
    from src.core.config_migration import ensure_config_migrated
    from src.core.config_writer import tighten_existing as _tighten_config_modes

    config_path = Path(settings.auth_config_file).expanduser()
    _tighten_config_modes(config_path)
    ensure_config_migrated(config_path)
    from src.core.swarm.legacy_pack_migration import migrate as migrate_legacy_pack

    migrate_legacy_pack(config_path, settings.get_state_dir())
    from src.core.browser_pages import open_pages as _open_pages

    _open_pages.configure(settings.get_state_dir())
    from src.core.open_files import open_list as _open_files

    _open_files.configure(settings.get_state_dir())
    from src.core import row_looks as _row_looks

    _row_looks.configure(settings.get_state_dir())
    settings.ensure_wrapper_defaults()


def _migrate_datastore(ctx: "BootContext") -> None:
    from src.core.db_migration import ensure_db_migrated

    datastore_state = ensure_db_migrated(
        settings.get_state_dir(),
        read_config_version(Path(settings.auth_config_file).expanduser()),
        resolve_version() or None,
    )
    ctx.datastore_state = datastore_state
    ctx.app.state.datastore_state = datastore_state
    version_routes.set_datastore_state(datastore_state)
    if not datastore_state.healthy:
        logger.warning(
            "datastore_degraded",
            status=datastore_state.status,
            schema_version=datastore_state.schema_version,
            message=datastore_state.message,
        )


async def _prepare_work_store(ctx: "BootContext") -> None:
    from src.core.work import boot as work_boot

    await asyncio.to_thread(work_boot.prepare, settings.get_state_dir(), ctx.datastore_state.healthy)


async def _recover_pack_jobs(ctx: "BootContext") -> None:
    if ctx.datastore_state.healthy:
        from src.api import project_pack_routes

        await asyncio.to_thread(project_pack_routes.recover_interrupted_jobs)


def steps() -> list[BootStep]:
    return [
        BootStep(name="mcp_old_name_counter", order=10, start=_install_old_name_counter),
        BootStep(name="config_migrations", order=20, start=_migrate_config),
        BootStep(name="datastore", order=30, start=_migrate_datastore),
        BootStep(name="work_store", order=40, start=_prepare_work_store),
        BootStep(name="pack_job_recovery", order=50, start=_recover_pack_jobs),
    ]
