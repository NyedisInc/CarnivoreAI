
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import structlog
from fastapi import FastAPI

from src.api.phone_link_routes import pair_router, router
from src.core.phone_link.manager import PhoneLinkManager

logger = structlog.get_logger()


def include_routers(app: FastAPI) -> None:
    app.include_router(router, prefix="/api/v1")
    app.include_router(pair_router)


def start(app: FastAPI, relay_config: Any, state_dir: Path, db_path: Path, version: str,
          account: Any = None) -> None:
    app.state.phone_link = None
    if not relay_config.enabled:
        return
    try:
        manager = PhoneLinkManager(app=app, config=relay_config, state_dir=state_dir,
                                   db_path=db_path, version=version, account=account)
    except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
        logger.warning("phone_link_boot_failed", error_type=type(exc).__name__)
        return
    app.state.phone_link = manager
    manager.start_in_background()


async def stop(app: FastAPI) -> None:
    manager = getattr(app.state, "phone_link", None)
    if manager is not None:
        await manager.aclose()
